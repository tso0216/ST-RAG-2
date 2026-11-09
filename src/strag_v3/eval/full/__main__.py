"""主系統（full）評估命令列。

    python -m strag_v3.eval.full run data/mock_article/eval [--split dev] [--no-answer | --judge] [--gate jev|semantic]
    python -m strag_v3.eval.full compare src/strag_v3/eval/full/runs/*.json

只跑完整系統（規劃器 → 檢索含兩種退讓 → 生成器），不跑 baseline 和 oracle。
`run` 印出彙總表（檢索指標，有 `gold_plan` 的題目的規劃器正確率，開 `--judge` 時加上答案指標），
並把設定、彙總和每題的紀錄（計畫、gold_plan、取回集合、證據、答案、評審的逐條判斷、指標）存成一個 JSON 檔；
`compare` 讀幾個結果檔，把同一組的指標並排列出；舊的結果檔 `config` 沒有 `gate`，當作 semantic。
"""
import argparse
import asyncio
import json
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from service.env import load_env
from service.jev import JEVClient, JEVError
from service.nominatim import NominatimClient

from ...extract.paths import DB_PATH
from ...place import PlaceError, Places
from ...rag import llm
from ...rag.embedding import CachedEmbedder, EmbeddingError, OpenAIEmbedder
from ...rag.params import GATE_HELP, GATES, Params
from ..metrics import evaluate
from ..questions import SPLITS, QuestionError, load_questions
from .judge import MODEL as JUDGE_MODEL, Judge, JudgeError
from .runner import Config, Runner

RUNS_DIR = Path(__file__).parent / "runs"

COLUMNS = (("n", "題數"), ("recall", "R"), ("precision", "P"), ("f1", "F1"),
           ("time_violation_rate", "時間違規率"), ("answered_rate", "有回答率"), ("errors", "錯誤"),
           ("unresolved", "地點解析失敗"))
# 規劃器正確率（彙總裡的 `planner`）
PLANNER_COLUMNS = (("n", "題數"), ("accuracy", "整體"), ("sub_queries", "子查詢數"), ("space", "地點"),
                   ("month", "月份"), ("day_type", "平日／假日"), ("time", "時段"), ("aspect", "aspect"),
                   ("group_by", "group_by"), ("compose", "compose"))
# 答案指標（彙總裡的 `answer`）
ANSWER_COLUMNS = (("n", "題數"), ("expect_coverage", "expect 覆蓋率"), ("misattribution_rate", "時間誤植率"),
                  ("claims_n", "講到時間的說法"), ("misattributed", "誤植"))


def _cell(v) -> str:
    if v is None:
        return "—"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def _width(s: str) -> int:
    """終端機顯示寬度：全形字（中日文、全形標點）算 2 格。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, w: int, right: bool) -> str:
    gap = " " * (w - _width(s))
    return gap + s if right else s + gap


def _table(rows: list[tuple[str, dict]], columns=COLUMNS) -> str:
    """rows：(列名, 指標)。對齊欄寬的 markdown 表格（中文以顯示寬度計），數字靠右。"""
    head = ["", *(label for _, label in columns)]
    body = [[name, *(_cell(m.get(k)) for k, _ in columns)] for name, m in rows]
    widths = [max(_width(r[i]) for r in [head, *body]) for i in range(len(head))]

    def line(cells):
        return "| " + " | ".join(_pad(c, widths[i], i > 0) for i, c in enumerate(cells)) + " |"

    sep = "|" + "|".join("-" * (w + 1) + ":" if i > 0 else "-" * (w + 2) for i, w in enumerate(widths)) + "|"
    return "\n".join([line(head), sep, *map(line, body)])


def _run_name(config: dict) -> str:
    """結果的名稱：系統名稱加相關判斷，例如 full-jev。舊的結果檔沒有 `gate`，那時只有語意門檻。"""
    return f"{config['name']}-{config.get('gate', 'semantic')}"


def _groups(summary: dict) -> list[tuple[str, dict]]:
    return ([("整體", summary["overall"])]
            + [(f"split={k}", v) for k, v in summary["by_split"].items()]
            + [(f"type={k}", v) for k, v in summary["by_type"].items()])


def _planner(groups: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """各組的規劃器正確率；沒有題目附 `gold_plan`，或是舊的結果檔沒有這項時是空的。"""
    return [(name, m["planner"]) for name, m in groups if (m.get("planner") or {}).get("n")]


def _answer(groups: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """各組的答案指標；沒開答案評估，或是舊的結果檔沒有這項時是空的。"""
    return [(name, m["answer"]) for name, m in groups if (m.get("answer") or {}).get("n")]


async def _judge_all(judge: Judge, questions, outcomes, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)

    async def one(q):
        async with sem:
            try:
                j = await judge.judge(q, outcomes[q.key])
            except JudgeError as e:  # 評審的格式錯誤只跳過這題；LLM 本身的錯誤照樣讓整批停下
                print(f"[judge] 跳過：{e}", file=sys.stderr)
                return q.key, None
        if j is not None:
            print(f"[judge] {q.key} expect 覆蓋 {j.expect_coverage if j.expect_coverage is not None else '—'}"
                  f"｜誤植 {'—' if j.misattributed is None else j.misattributed}", file=sys.stderr)
        return q.key, j

    pairs = await asyncio.gather(*(one(q) for q in questions))
    return {k: j for k, j in pairs if j is not None}


async def _run(a) -> dict:
    questions = load_questions(a.questions)
    if a.split:
        questions = [q for q in questions if q.split == a.split]
        if not questions:
            raise QuestionError(f"沒有 split={a.split} 的題目")
    config = Config(answer=not a.no_answer, judge=a.judge, params=Params(gate=a.gate))
    conn = sqlite3.connect(a.db)
    jev = JEVClient() if a.gate == "jev" else None
    try:
        runner = Runner(conn, CachedEmbedder(OpenAIEmbedder(), conn), config, nominatim=NominatimClient(), jev=jev)

        def progress(q, out):
            status = f"錯誤：{out.error}" if out.error else f"取回 {len(out.evidence)} 筆"
            if bad := out.unresolved_places:
                status += "｜地點解析不到：" + "、".join(f"{p['name_ja']}（{p['city'] or '不限城市'}）" for p in bad)
            print(f"[{_run_name(config.to_dict())}] {q.key} {status}", file=sys.stderr)

        outcomes = await runner.run_all(questions, a.concurrency, progress)
        judge = Judge(conn) if config.judge else None
        judgements = await _judge_all(judge, questions, outcomes, a.concurrency) if judge else None
        metrics = evaluate(questions, outcomes, Places(conn, NominatimClient()), judgements)
    finally:
        conn.close()
        if jev:
            await jev.aclose()
    return {
        "config": config.to_dict(),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "questions_path": str(a.questions),
        "split": a.split,
        "db": str(a.db),
        **({"judge": {"model": judge.model, "note": judge.note()}} if judge else {}),
        **metrics,
    }


def cmd_run(a) -> int:
    load_env()
    try:
        result = asyncio.run(_run(a))
    except (QuestionError, ValueError, llm.LLMError, EmbeddingError, JEVError, PlaceError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    name = _run_name(result["config"]) + (f"_{a.split}" if a.split else "")
    out = a.out or RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    groups = _groups(result["summary"])
    print(f"## {name}\n\n{_table(groups)}\n")
    if planner := _planner(groups):
        print(f"### 規劃器正確率\n\n{_table(planner, PLANNER_COLUMNS)}\n")
    if answer := _answer(groups):
        print(f"### 答案指標\n\n{_table(answer, ANSWER_COLUMNS)}\n\n註：{result['judge']['note']}\n")
    print(f"結果存在 {out}")
    return 0


def cmd_compare(a) -> int:
    runs = []
    for p in a.runs:
        r = json.loads(p.read_text())
        runs.append((f"{_run_name(r['config'])}（{p.stem}）", dict(_groups(r["summary"]))))
        if judge := r.get("judge"):
            print(f"註：{p.stem} 的答案評估：{judge['note']}")
    group_names = list(dict.fromkeys(g for _, groups in runs for g in groups))
    for g in group_names:
        rows = [(name, groups[g]) for name, groups in runs if g in groups]
        print(f"## {g}\n\n{_table(rows)}\n")
        if planner := _planner(rows):
            print(f"### {g}：規劃器正確率\n\n{_table(planner, PLANNER_COLUMNS)}\n")
        if answer := _answer(rows):
            print(f"### {g}：答案指標\n\n{_table(answer, ANSWER_COLUMNS)}\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.eval.full", description="用主系統（full）跑 eval 題目，輸出各項指標的彙總")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="用主系統跑題目，印出彙總並存檔")
    r.add_argument("questions", type=Path, help="題目檔，或放題目檔的資料夾（讀裡面所有 *.json）")
    r.add_argument("--split", choices=SPLITS, help="只跑 dev 或 test 的題目（預設全部）")
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--no-answer", action="store_true", help="不呼叫生成器，只評估檢索")
    mode.add_argument("--judge", action="store_true",
                      help=f"請評審（{JUDGE_MODEL}）評估答案的 expect 覆蓋率和時間誤植率；評審結果有快取")
    r.add_argument("--gate", choices=GATES, default="jev", help=GATE_HELP)
    r.add_argument("--concurrency", type=int, default=4, help="同時跑幾題（預設 4）")
    r.add_argument("--db", type=Path, default=DB_PATH, help=f"片段所在的 DB（預設 {DB_PATH}）")
    r.add_argument("--out", type=Path, help=f"結果檔路徑（預設 {RUNS_DIR}/<時間>_full-<gate>.json）")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compare", help="並排比較幾個結果檔的彙總")
    c.add_argument("runs", type=Path, nargs="+", help="run 存下的結果檔")
    c.set_defaults(func=cmd_compare)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
