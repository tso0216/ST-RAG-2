import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .paths import DB_PATH
from .pipeline import run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.extract", description="把 Reddit 文章或現成的文章 JSON 抽成 content 表")
    ap.add_argument("sources", nargs="+", metavar="source",
                    help="Reddit 貼文或留言連結、文章 JSON 檔，或內含 *.json 的資料夾")
    ap.add_argument("--cache", action="store_true", help="有快取就直接用，不重新呼叫 LLM")
    ap.add_argument("--force", action="store_true", help="DB 已有的文章也重抽（會刪掉舊片段，content id 會變）")
    ap.add_argument("--ptt", action="store_true", help="PTT 文章 JSON：把 comments（推文）接在本文後面一起抽")
    ap.add_argument("--jobs", type=int, default=1, help="同時抽取的篇數（預設 1）；寫入仍逐篇，輸出順序會亂")
    ap.add_argument("--db", type=Path, default=DB_PATH, help=f"寫入的 DB（預設 {DB_PATH}）；要先用 scripts/db/create_main_db.py 建好")
    a = ap.parse_args(argv)
    if not a.db.exists():
        print(f"找不到 DB：{a.db}，先跑 python scripts/db/create_main_db.py --db {a.db}", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    sources = []
    for s in a.sources:
        p = Path(s)
        sources += sorted(map(str, p.glob("*.json"))) if p.is_dir() else [s]

    r = asyncio.run(run(sources, use_cache=a.cache, force=a.force, ptt=a.ptt, db_path=a.db, jobs=a.jobs))

    print(f"\n處理篇數：{len(r.done)}")
    print(f"寫入筆數：{r.written}")
    print(f"格式不合而丟掉：{r.dropped}")
    print(f"略過：{len(r.skipped)}")
    for url, reason in r.skipped:
        print(f"  {reason}  {url}")
    if r.unresolved:
        print(f"\n地點解析不到，整篇沒有寫入：{len(r.unresolved)} 篇", file=sys.stderr)
        for article_id, names in r.unresolved:
            print(f"  {article_id}：{'、'.join(names)}", file=sys.stderr)
    if r.error:
        print(f"\n錯誤，整批停止：{r.error}", file=sys.stderr)
        print("已完成：", *r.done, sep="\n  ")
        print("未完成：", *r.pending, sep="\n  ")
        return 1
    return 1 if r.unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
