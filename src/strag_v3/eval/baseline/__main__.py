"""baseline 比較實驗的命令列（從專案根目錄跑，`PYTHONPATH=.:src`）。

    python -m strag_v3.eval.baseline build-chunks              # 248 篇原文 → 原文段和 embedding，寫進 chunks.db
    python -m strag_v3.eval.baseline run --system <名稱> [--k N]  # 跑 50 題，存結果檔到 runs/
    python -m strag_v3.eval.baseline judge <結果檔> [--n N]      # 評審，存評審檔，印不一致和一致率
    python -m strag_v3.eval.baseline report <評審檔>...          # 印比較表（markdown）
    python -m strag_v3.eval.baseline calibrate [--n N]          # 用校準的正反向答案驗評審
"""
import argparse
import asyncio
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from service.env import load_env
from service.jev import JEVClient
from service.nominatim import NominatimClient

from ...rag.embedding import CachedEmbedder, OpenAIEmbedder
from . import chunks
from .calibrate import calibrate
from .fragments import load_fragments
from .judge import Judge, Verdict, agreement, disagreements
from .metrics import score_run
from .questions import PTT_V2, load_negatives, load_questions
from .report import Row, label, report
from .results import load_judge, load_run, save_judge, save_run
from .systems import MODEL, SYSTEMS, DenseFilter, DenseFrag, DenseRaw, Llm, Strag, System, run_all

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "data" / "ptt.db"


def read_only(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def fragments_of(db: Path):
    with closing(read_only(db)) as conn:
        return load_fragments(conn)


def baseline_embedder(conn: sqlite3.Connection) -> CachedEmbedder:
    """baseline 的 embedding（原文段、片段、問題）都快取在 chunks.db，不寫進 ptt.db。"""
    return CachedEmbedder(OpenAIEmbedder(), conn)


def build_chunks_cmd(db: Path) -> int:
    with closing(read_only(db)) as conn:
        article_ids = [a for (a,) in conn.execute("SELECT DISTINCT article_id FROM content ORDER BY article_id")]
    with closing(chunks.connect()) as conn:
        try:
            n = chunks.build(conn, baseline_embedder(conn), article_ids)
        except FileNotFoundError as e:
            print(f"錯誤：{e}", file=sys.stderr)
            return 1
    print(f"{chunks.CHUNKS_DB.name}：{len(article_ids)} 篇文章，{n} 個原文段")
    return 0


async def run_cmd(name: str, k: int | None, db: Path, concurrency: int) -> int:
    retrieval, default_k = SYSTEMS[name]
    k = k if k is not None else default_k
    if default_k is None and k is not None:
        print(f"錯誤：{name} 沒有 k", file=sys.stderr)
        return 1
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    questions = load_questions()
    cache = chunks.connect()
    jev = None
    main_conn = None
    system: System
    try:
        if name == "llm":
            system = Llm()
        elif name in ("dense_frag", "dense_filter"):
            frags = list(fragments_of(db).values())
            assert k is not None
            system = (DenseFrag if name == "dense_frag" else DenseFilter)(baseline_embedder(cache), frags, k)
        elif name == "dense_raw":
            loaded = chunks.load_chunks(cache)
            if not loaded:
                print("錯誤：chunks.db 沒有原文段，先跑 build-chunks", file=sys.stderr)
                return 1
            assert k is not None
            system = DenseRaw(baseline_embedder(cache), loaded, k)
        else:
            main_conn = sqlite3.connect(db)  # 主系統會寫相關判斷和地點解析的快取，這是它原本的行為
            jev = JEVClient()
            system = Strag(main_conn, baseline_embedder(cache), jev, NominatimClient())
        outcomes = await run_all(system, questions, concurrency)
    finally:
        cache.close()
        if main_conn is not None:
            main_conn.close()
        if jev is not None:
            await jev.aclose()
    config = {"system": name, "k": k, "retrieval": retrieval, "model": MODEL, "questions": str(PTT_V2.name),
              "db": str(db.name), "started_at": started,
              "finished_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    path = save_run(config, outcomes)
    errors = sum(o.error is not None for o in outcomes)
    print(f"結果檔：{path}（{len(outcomes)} 題，出錯 {errors} 題）")
    return 0


def report_cmd(paths: list[Path], db: Path) -> int:
    questions = load_questions()
    fragments = fragments_of(db)
    rows = []
    for p in paths:
        data, run_path = load_judge(p)
        config, outcomes = load_run(run_path)
        verdicts = [Verdict(**v) for v in data["questions"]]
        rows.append(Row(label(config), config["retrieval"],
                        score_run(questions, outcomes, verdicts, fragments, config["retrieval"])))
    print(report(rows))
    return 0


def _rate(x: float | None) -> str:
    return "—" if x is None else f"{x:.1%}"


def print_disagreements(items: list[dict], agree: dict) -> None:
    print(f"## 不一致（{len(items)} 筆）")
    for d in items:
        print(f"{d['system']}\t{d['id']}\t{d['item']}\t" + " ".join(f"{n:.2f}" for n in d["nouls"]))
    print(f"一致率：覆蓋 {_rate(agree['coverage'])}，無支持 {_rate(agree['unsupported'])}")


async def judge_cmd(run_path: Path, n: int, db: Path, concurrency: int) -> int:
    config, outcomes = load_run(run_path)
    fragments = fragments_of(db)
    client = JEVClient()
    try:
        judge = Judge(client, n=n, concurrency=concurrency)
        verdicts = await judge.judge(load_questions(), fragments, outcomes)
    finally:
        await client.aclose()
    items = disagreements(config["system"], verdicts)
    agree = agreement(verdicts)
    skipped = sum(v.skipped for v in verdicts)
    print(f"{run_path.name}：評了 {len(verdicts) - skipped} 題，沒有答案不送評審 {skipped} 題")
    print_disagreements(items, agree)
    path = save_judge(run_path, {"config": judge.config(), "run_config": config,
                                 "questions": [asdict(v) for v in verdicts],
                                 "disagreements": items, "agreement": agree})
    print(f"評審檔：{path}")
    return 0


async def calibrate_cmd(n: int, db: Path, concurrency: int) -> int:
    fragments = fragments_of(db)
    questions = load_questions()
    client = JEVClient()
    try:
        result = await calibrate(Judge(client, n=n, concurrency=concurrency), questions, fragments, load_negatives())
    finally:
        await client.aclose()
    types = list(dict.fromkeys(q.type for q in questions))
    print("## 沒過的條目")
    for _, line in result.coverage_failures + result.unsupported_failures:
        print(line)
    print("\n## 各題型沒過的條目數")
    print("| 題型 | 覆蓋 | 無支持 |\n|---|---|---|")
    type_of = {q.id: q.type for q in questions}
    for t in types:
        cov = sum(type_of[qid] == t for qid, _ in result.coverage_failures)
        uns = sum(type_of[qid] == t for qid, _ in result.unsupported_failures)
        print(f"| {t} | {cov} | {uns} |")
    print(f"| 合計 | {len(result.coverage_failures)} / {result.coverage_total} "
          f"| {len(result.unsupported_failures)} / {result.unsupported_total} |")
    if n > 1:
        print()
        print_disagreements(disagreements("正向", result.positive) + disagreements("反向", result.negative),
                            agreement(result.positive + result.negative))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.eval.baseline", description="baseline 比較實驗")
    ap.add_argument("--db", type=Path, default=DB, help=f"片段所在的 DB（預設 {DB.relative_to(ROOT)}）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-chunks", help="原文 → 原文段和 embedding，寫進 chunks.db")
    s = sub.add_parser("run", help="跑 50 題，存結果檔")
    s.add_argument("--system", choices=list(SYSTEMS), required=True)
    s.add_argument("--k", type=int, default=None, help="取回幾筆（dense_raw 預設 5，dense_frag／dense_filter 預設 10）")
    s.add_argument("--concurrency", type=int, default=4, help="同時跑幾題")
    s = sub.add_parser("report", help="印比較表")
    s.add_argument("judges", type=Path, nargs="+")
    s = sub.add_parser("judge", help="評審一份結果檔")
    s.add_argument("run", type=Path)
    s.add_argument("--n", type=int, default=1, help="同一個判斷重問幾次（分數只用第 1 次）")
    s.add_argument("--concurrency", type=int, default=8)
    s = sub.add_parser("calibrate", help="用校準的正反向答案驗評審")
    s.add_argument("--n", type=int, default=1)
    s.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args(argv)
    load_env()
    if a.cmd == "build-chunks":
        return build_chunks_cmd(a.db)
    if a.cmd == "run":
        return asyncio.run(run_cmd(a.system, a.k, a.db, a.concurrency))
    if a.cmd == "report":
        return report_cmd(a.judges, a.db)
    if a.cmd == "judge":
        return asyncio.run(judge_cmd(a.run, a.n, a.db, a.concurrency))
    if a.cmd == "calibrate":
        return asyncio.run(calibrate_cmd(a.n, a.db, a.concurrency))
    return 1


if __name__ == "__main__":
    sys.exit(main())
