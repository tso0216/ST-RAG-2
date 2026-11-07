import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from ..extract.paths import DB_PATH
from . import llm
from .embedding import CachedEmbedder, EmbeddingError, OpenAIEmbedder
from .plan import PlanError
from .retrieve import Retriever


async def run(question: str, db: Path) -> dict:
    conn = sqlite3.connect(db)
    try:
        plan = await llm.plan(question)
        retriever = Retriever(conn, CachedEmbedder(OpenAIEmbedder(), conn))
        sections = retriever.retrieve_grouped(plan, question)
        results = [r for s in sections for r in s.results]
        answer = await llm.answer(question, sections)
    finally:
        conn.close()
    index = {id(r): i for i, r in enumerate(results)}
    return {
        "question": question,
        "plan": plan.to_dict(),
        "results": [{"sub_query": asdict(r.sub_query), "evidence": [asdict(e) for e in r.evidence]}
                    for r in results],
        # 交給生成器的段落：sub_queries 是 plan 裡子查詢的索引（0 起算）
        "sections": [{"sub_queries": [index[id(r)] for r in s.results],
                      "groups": [{"key": g.key, "evidence": [asdict(e) for e in g.evidence]} for g in s.groups]}
                     for s in sections],
        "answer": answer,
    }


def show(out: dict) -> None:
    print("## 檢索計畫")
    print(json.dumps(out["plan"], ensure_ascii=False, indent=2))
    for s in out["sections"]:
        subs = "、".join(str(i + 1) for i in s["sub_queries"])
        print(f"\n## 子查詢 {subs} 取回 {sum(len(g['evidence']) for g in s['groups'])} 筆")
        for g in s["groups"]:
            if g["key"]:
                print("### " + "｜".join(f"{d}={v}" for d, v in g["key"].items()))
            for e in g["evidence"]:
                print(f"[{e['content_id']}] {e['article_id']}｜{e['place']}｜{e['month']}月 {e['day_type']} {e['time']}"
                      f"｜重疊 {e['overlap']:.3f} 語意 {e['semantic']:.3f} 分數 {e['score']:.3f}")
                print(f"    {e['content']}")
    print("\n## 答案")
    print(out["answer"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.rag", description="輸入旅客問題，輸出答案、檢索計畫和取回的片段")
    ap.add_argument("question", help="旅客的問題")
    ap.add_argument("--db", type=Path, default=DB_PATH, help=f"片段所在的 DB（預設 {DB_PATH}）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    a = ap.parse_args(argv)
    try:
        out = asyncio.run(run(a.question, a.db))
    except (llm.LLMError, EmbeddingError, PlanError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        show(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
