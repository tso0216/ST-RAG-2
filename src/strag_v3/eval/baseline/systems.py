"""五個系統：同一個介面，輸入一題、輸出 `Outcome`（答案、取回的片段與文章、成本、錯誤）。生成都用 `claude-opus-5-5`，不快取。

| 名稱 | 做法 | 取回 |
|---|---|---|
| `llm` | 不檢索，只給問題（`prompts/llm.md`） | 沒有 |
| `dense_raw` | 原問題對原文段的 cosine top-k（`chunks.py`） | 文章 |
| `dense_frag` | 原問題對片段的 cosine top-k（`dense.py`） | 片段 |
| `dense_filter` | Opus 產生過濾條件（`prompts/filter.md`），過濾片段後 cosine top-k（`dense.py`） | 片段 |
| `strag` | 主系統：規劃器 → 檢索（含兩種退讓、JEV 相關判斷和它的快取）→ 生成器，全部預設參數 | 片段 |

三個 dense 系統共用精簡版的生成提示詞（`prompts/dense.md`）；`strag` 用主系統原本的生成器提示詞。
"""
import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from service.jev import JEVClient
from service.llm import call_with_usage
from service.nominatim import NominatimClient

from ...extract.paths import TIME_SLOTS_MARK, TIME_SLOTS_PATH
from ...rag import llm as rag_llm
from ...rag.embedding import Embedder
from ...rag.params import DEFAULT
from ...rag.retrieve import Retriever
from ...rag.timematch import DAY_TYPES, QUERY_SLOTS
from .chunks import Chunk, chunk_top_k
from .dense import Filter, dense_top_k, filter_top_k
from .fragments import Fragment
from .questions import Question
from .results import Cost, Outcome

MODEL = rag_llm.MODEL  # 跟主系統同一個生成模型
PROMPTS = Path(__file__).resolve().parent / "prompts"
ANSWER_SCHEMA = rag_llm.ANSWER_SCHEMA

# 系統名稱 → （取回的粒度, 預設 k）
SYSTEMS = {
    "llm": ("none", None),
    "dense_raw": ("article", 5),
    "dense_frag": ("fragment", 10),
    "dense_filter": ("fragment", 10),
    "strag": ("fragment", None),
}

_NULLABLE_LIST = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
FILTER_SCHEMA = {
    "type": "object",
    "properties": {"filters": {"type": "array", "minItems": 1, "items": {
        "type": "object",
        "properties": {
            "place": {"anyOf": [{"type": "object", "properties": {"name": {"type": "string"},
                                                                  "name_ja": {"type": "string"}},
                                 "required": ["name", "name_ja"], "additionalProperties": False},
                                {"type": "null"}]},
            "month": _NULLABLE_LIST,
            "day_type": {"anyOf": [{"type": "string", "enum": list(DAY_TYPES)}, {"type": "null"}]},
            "time": {"anyOf": [{"type": "array", "items": {"type": "string", "enum": list(QUERY_SLOTS)}},
                               {"type": "null"}]},
        },
        "required": ["place", "month", "day_type", "time"],
        "additionalProperties": False,
    }}},
    "required": ["filters"],
    "additionalProperties": False,
}


class System(Protocol):
    name: str
    retrieval: str

    async def answer(self, q: Question) -> Outcome: ...


async def generate(system_prompt: str, user: str) -> tuple[str, int]:
    """回傳答案和輸入 token 數。"""
    out, tokens = await call_with_usage(system_prompt, user, ANSWER_SCHEMA, MODEL)
    assert isinstance(out, dict)
    return out["answer"], tokens


def fragment_passage(f: Fragment) -> dict:
    return {"出處 id": f.id, "文章": f.article_id, "地點": f.place, "月份": f.time.month,
            "平日／假日": f.time.day_type, "時段": f.time.time, "內容": f.text}


def chunk_passage(c: Chunk) -> dict:
    return {"出處 id": c.id, "文章": c.article_id, "內容": c.text}


def dense_prompt(question: str, passages: list[dict]) -> str:
    body = f"```json\n{json.dumps(passages, ensure_ascii=False, indent=2)}\n```" if passages else "沒有"
    return f"旅客的問題：{question}\n\n證據（{len(passages)} 筆）：\n{body}"


async def dense_answer(question: str, passages: list[dict]) -> tuple[str, int]:
    return await generate((PROMPTS / "dense.md").read_text(), dense_prompt(question, passages))


@dataclass
class Llm:
    name: str = "llm"
    retrieval: str = "none"

    async def answer(self, q: Question) -> Outcome:
        answer, tokens = await generate((PROMPTS / "llm.md").read_text(), q.question)
        return Outcome(q.id, answer=answer, cost=Cost(tokens, 1, 0))


@dataclass
class DenseFrag:
    embedder: Embedder
    fragments: list[Fragment]
    k: int
    name: str = "dense_frag"
    retrieval: str = "fragment"

    async def answer(self, q: Question) -> Outcome:
        got = [f for _, f in dense_top_k(self.embedder, q.question, self.fragments, self.k)]
        answer, tokens = await dense_answer(q.question, [fragment_passage(f) for f in got])
        return Outcome(q.id, answer=answer, contents=[f.id for f in got],
                       articles=list(dict.fromkeys(f.article_id for f in got)), cost=Cost(tokens, 1, 0))


@dataclass
class DenseFilter:
    embedder: Embedder
    fragments: list[Fragment]
    k: int
    name: str = "dense_filter"
    retrieval: str = "fragment"

    async def filters(self, question: str) -> list[dict]:
        system = (PROMPTS / "filter.md").read_text().replace(TIME_SLOTS_MARK, TIME_SLOTS_PATH.read_text().strip())
        out, _ = await call_with_usage(system, question, FILTER_SCHEMA, MODEL)
        assert isinstance(out, dict)
        return out["filters"]

    async def answer(self, q: Question) -> Outcome:
        raw = await self.filters(q.question)
        extra = {"filters": raw}
        try:
            filters = [Filter.from_dict(d) for d in raw]
        except ValueError as e:  # 看不懂的時間標籤
            return Outcome(q.id, error=f"{type(e).__name__}: {e}", cost=Cost(0, 1, 0), extra=extra)
        scored, unmatched = filter_top_k(self.embedder, q.question, self.fragments, filters, self.k)
        got = [f for _, f in scored]
        answer, tokens = await dense_answer(q.question, [fragment_passage(f) for f in got])
        return Outcome(q.id, answer=answer, contents=[f.id for f in got],
                       articles=list(dict.fromkeys(f.article_id for f in got)), cost=Cost(tokens, 2, 0),
                       place_unresolved=unmatched, extra=extra)


@dataclass
class DenseRaw:
    embedder: Embedder
    chunks: list[Chunk]
    k: int
    name: str = "dense_raw"
    retrieval: str = "article"

    async def answer(self, q: Question) -> Outcome:
        got = [c for _, c in chunk_top_k(self.embedder, q.question, self.chunks, self.k)]
        answer, tokens = await dense_answer(q.question, [chunk_passage(c) for c in got])
        return Outcome(q.id, answer=answer, articles=list(dict.fromkeys(c.article_id for c in got)),
                       cost=Cost(tokens, 1, 0), extra={"chunks": [c.id for c in got]})


@dataclass
class Strag:
    """主系統，預設參數。conn 要可寫：相關判斷的快取（`jev_cache`）和地點解析的快取是系統原本的行為。"""
    conn: sqlite3.Connection
    embedder: Embedder
    jev: JEVClient
    nominatim: NominatimClient | None = None
    name: str = "strag"
    retrieval: str = "fragment"
    # 所有題目共用的 JEV 同時請求上限（跟單題時的 jev_concurrency 一樣）
    _sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(DEFAULT.jev_concurrency))

    async def answer(self, q: Question) -> Outcome:
        plan = await rag_llm.plan(q.question)
        retriever = Retriever(self.conn, self.embedder, DEFAULT, nominatim=self.nominatim, jev=self.jev)
        gate = retriever.jev_gate
        assert gate is not None  # 預設參數是 gate=jev
        gate.sem = self._sem
        judged = 0
        nouls = gate.nouls

        async def counted(question, aspect, candidates):
            nonlocal judged
            judged += len(candidates)
            return await nouls(question, aspect, candidates)
        gate.nouls = counted  # type: ignore[method-assign]  # 數相關判斷了幾個片段（含讀快取的）

        sections = await retriever.retrieve(plan, q.question)
        evidence = [e for s in sections for e in s.evidence]
        system = (rag_llm.PROMPT_DIR / "generator.md").read_text()
        answer, tokens = await generate(system, rag_llm.build_answer_prompt(q.question, sections))
        return Outcome(
            q.id, answer=answer,
            contents=list(dict.fromkeys(e.content_id for e in evidence)),
            articles=list(dict.fromkeys(e.article_id for e in evidence)),
            backoff=sorted({e.content_id for e in evidence if e.time_backoff or e.space_backoff}),
            cost=Cost(tokens, 2, judged),
            place_unresolved=any(r.place_unresolved for s in sections for r in s.results),
            extra={"plan": plan.to_dict()},
        )


async def run_all(system: System, questions: list[Question], concurrency: int = 4) -> list[Outcome]:
    """依題目順序回傳；某題出錯只記那題的錯誤，其他題繼續跑。"""
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(q: Question) -> Outcome:
        nonlocal done
        async with sem:
            try:
                o = await system.answer(q)
            except Exception as e:  # noqa: BLE001  一題失敗不毀掉整批
                o = Outcome(q.id, error=f"{type(e).__name__}: {e}")
        done += 1
        print(f"[{done}/{len(questions)}] {q.id}" + (f"  錯誤：{o.error}" if o.error else ""), flush=True)
        return o

    return list(await asyncio.gather(*(one(q) for q in questions)))
