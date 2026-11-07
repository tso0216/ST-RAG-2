"""評估命令列。

    python -m strag_v3.eval run ../data/mock_article/eval --system full [--oracle] [--split dev]
    python -m strag_v3.eval compare ../data/eval_runs/*.json

`run` 印出彙總表，並把設定、彙總和每題的紀錄（計畫、取回集合、證據、答案、指標）存成一個 JSON 檔；
`compare` 讀幾個結果檔，把同一組的指標並排列出。
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from ..extract.paths import DB_PATH
from ..place import NominatimClient, PlaceError
from ..rag import llm
from ..rag.embedding import CachedEmbedder, EmbeddingError, OpenAIEmbedder
from .metrics import evaluate
from .questions import SPLITS, QuestionError, load_questions
from .runner import SYSTEMS, Config, Runner

RUNS_DIR = DB_PATH.parent / "eval_runs"

COLUMNS = (("n", "題數"), ("recall", "R"), ("precision", "P"), ("f1", "F1"),
           ("time_violation_rate", "時間違規率"), ("answered_rate", "有回答率"), ("errors", "錯誤"))


def _cell(v) -> str:
    if v is None:
        return "—"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def _table(rows: list[tuple[str, dict]]) -> str:
    """rows：(列名, 指標)。用 markdown 表格，方便貼進筆記。"""
    head = ["", *(label for _, label in COLUMNS)]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join([name, *(_cell(m.get(k)) for k, _ in COLUMNS)]) + " |" for name, m in rows]
    return "\n".join(lines)


def _groups(summary: dict) -> list[tuple[str, dict]]:
    return ([("整體", summary["overall"])]
            + [(f"split={k}", v) for k, v in summary["by_split"].items()]
            + [(f"type={k}", v) for k, v in summary["by_type"].items()])


async def _run(a) -> dict:
    questions = load_questions(a.questions)
    if a.split:
        questions = [q for q in questions if q.split == a.split]
        if not questions:
            raise QuestionError(f"沒有 split={a.split} 的題目")
    config = Config(system=a.system, oracle=a.oracle, k=a.k, answer=not a.no_answer)
    conn = sqlite3.connect(a.db)
    try:
        runner = Runner(conn, CachedEmbedder(OpenAIEmbedder(), conn), config, nominatim=NominatimClient())

        def progress(q, out):
            status = f"錯誤：{out.error}" if out.error else f"取回 {len(out.evidence)} 筆"
            print(f"[{config.name}] {q.key} {status}", file=sys.stderr)

        outcomes = await runner.run_all(questions, a.concurrency, progress)
    finally:
        conn.close()
    return {
        "config": config.to_dict(),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "questions_path": str(a.questions),
        "split": a.split,
        "db": str(a.db),
        **evaluate(questions, outcomes),
    }


def cmd_run(a) -> int:
    try:
        result = asyncio.run(_run(a))
    except (QuestionError, ValueError, llm.LLMError, EmbeddingError, PlaceError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    name = result["config"]["name"] + (f"_{a.split}" if a.split else "")
    out = a.out or RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"## {name}\n\n{_table(_groups(result['summary']))}\n\n結果存在 {out}")
    return 0


def cmd_compare(a) -> int:
    runs = []
    for p in a.runs:
        r = json.loads(p.read_text())
        runs.append((f"{r['config']['name']}（{p.stem}）", dict(_groups(r["summary"]))))
    group_names = list(dict.fromkeys(g for _, groups in runs for g in groups))
    for g in group_names:
        print(f"## {g}\n\n{_table([(name, groups[g]) for name, groups in runs if g in groups])}\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.eval", description="跑 eval 題目，輸出檢索指標的彙總")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="用一個系統設定跑題目，印出彙總並存檔")
    r.add_argument("questions", type=Path, help="題目檔，或放題目檔的資料夾（讀裡面所有 *.json）")
    r.add_argument("--system", choices=SYSTEMS, default="full",
                   help="full：完整系統；dense：只用語意分數取 top-k；hard：硬過濾、不退讓（預設 full）")
    r.add_argument("--oracle", action="store_true", help="用題目的 when 取代規劃器解析出來的時間（full、hard 可用）")
    r.add_argument("--split", choices=SPLITS, help="只跑 dev 或 test 的題目（預設全部）")
    r.add_argument("--k", type=int, default=5, help="dense 取幾筆（預設 5）")
    r.add_argument("--no-answer", action="store_true", help="不呼叫生成器，只評估檢索")
    r.add_argument("--concurrency", type=int, default=4, help="同時跑幾題（預設 4）")
    r.add_argument("--db", type=Path, default=DB_PATH, help=f"片段所在的 DB（預設 {DB_PATH}）")
    r.add_argument("--out", type=Path, help=f"結果檔路徑（預設 {RUNS_DIR}/<時間>_<設定>.json）")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compare", help="並排比較幾個結果檔的彙總")
    c.add_argument("runs", type=Path, nargs="+", help="run 存下的結果檔")
    c.set_defaults(func=cmd_compare)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
