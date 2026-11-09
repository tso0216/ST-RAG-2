import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from service.env import load_env
from service.jev import JEVClient, JEVError
from service.nominatim import NominatimClient

from ..extract.paths import DB_PATH
from ..place import PlaceError
from . import llm
from .embedding import CachedEmbedder, EmbeddingError, OpenAIEmbedder
from .params import GATE_HELP, GATES, Params
from .plan import PlanError
from .retrieve import Retriever
from .timematch import LabelError


async def run(question: str, db: Path, params: Params = Params()) -> dict:
    conn = sqlite3.connect(db)
    jev = JEVClient() if params.gate == "jev" else None
    try:
        plan = await llm.plan(question)
        retriever = Retriever(conn, CachedEmbedder(OpenAIEmbedder(), conn), params, nominatim=NominatimClient(), jev=jev)
        sections = await retriever.retrieve(plan, question)
        answer = await llm.answer(question, sections)
    finally:
        conn.close()
        if jev:
            await jev.aclose()
    return {
        "question": question,
        "plan": plan.to_dict(),
        # 交給生成器的段：results 是這段的子查詢（條件、各自取回的證據、沒有證據時有資料的時段和月份），groups 是分好的組
        "sections": [asdict(s) for s in sections],
        "answer": answer,
    }


def _when(t: dict) -> str:
    return f"{t['month']}月 {t['day_type']} {t['time']}"


def _counts(pairs: list) -> str:
    return "、".join(f"{label} {n} 筆" for label, n in pairs) or "無"


FLAGS = {"time_backoff": "時間退讓", "space_backoff": "空間退讓", "time_unknown": "時間不明"}


def show(out: dict) -> None:
    print("## 檢索計畫")
    print(json.dumps(out["plan"], ensure_ascii=False, indent=2))
    for i, s in enumerate(out["sections"], 1):
        print(f"\n## 第 {i} 段：取回 {sum(len(g['evidence']) for g in s['groups'])} 筆")
        for r in s["results"]:
            print("子查詢：" + json.dumps(r["sub_query"], ensure_ascii=False))
            if r["place_unresolved"]:
                sp = r["sub_query"]["space"]
                print(f"  地點解析不到：{sp['name_ja']}（{sp['city'] or '不限城市'}，{sp['kind']}），沒有檢索")
            elif not r["evidence"]:
                print(f"  沒有證據。有資料的時段：{_counts(r['available']['time'])}；月份：{_counts(r['available']['month'])}")
        for g in s["groups"]:
            if g["key"]:
                print("### " + "｜".join(f"{d}={v}" for d, v in g["key"].items()))
            for e in g["evidence"]:
                flags = "".join(f"｜{name}" for key, name in FLAGS.items() if e[key])
                if e["backoff_area"]:
                    flags += f"（{e['backoff_area']}）"
                print(f"[{e['content_id']}] {e['article_id']}｜{e['place']}｜{_when(e['time'])}"
                      f"｜相關 {e['relevance']:.3f} 分數 {e['score']:.3f}{flags}")
                print(f"    {e['content']}")
    print("\n## 答案")
    print(out["answer"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.rag", description="輸入旅客問題，輸出答案、檢索計畫和取回的片段")
    ap.add_argument("question", help="旅客的問題")
    ap.add_argument("--db", type=Path, default=DB_PATH, help=f"片段所在的 DB（預設 {DB_PATH}）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--no-time-backoff", action="store_true", help="關掉時間退讓（消融）")
    ap.add_argument("--no-space-backoff", action="store_true", help="關掉空間退讓（消融）")
    ap.add_argument("--gate", choices=GATES, default="jev", help=GATE_HELP)
    a = ap.parse_args(argv)
    load_env()
    params = Params(gate=a.gate, time_backoff=not a.no_time_backoff, space_backoff=not a.no_space_backoff)
    try:
        out = asyncio.run(run(a.question, a.db, params))
    except (llm.LLMError, EmbeddingError, JEVError, PlanError, PlaceError, LabelError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        show(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
