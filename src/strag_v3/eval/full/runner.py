"""主系統（full）的設定和逐題執行：規劃器 → 檢索含兩種退讓 → 生成器。"""
import asyncio
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

from ...place import Nominatim
from ...rag import llm
from ...rag.embedding import Embedder
from ...rag.evidence import Section
from ...rag.params import Params
from ...rag.plan import Plan, PlanError
from ...rag.retrieve import Retriever
from ..metrics import Outcome
from ..questions import Question

Planner = Callable[[str], Awaitable[Plan]]
Answerer = Callable[[str, list[Section]], Awaitable[str]]


@dataclass(frozen=True)
class Config:
    # 要不要呼叫生成器產生答案
    answer: bool = True
    # 檢索參數
    params: Params = field(default_factory=Params)

    name = "full"

    def to_dict(self) -> dict:
        return {"name": self.name, "answer": self.answer, "params": asdict(self.params)}


class Runner:
    """用主系統跑題目。規劃器和生成器預設呼叫 Opus，測試時可以換掉。"""

    def __init__(self, conn: sqlite3.Connection, embedder: Embedder, config: Config,
                 nominatim: Nominatim | None = None, planner: Planner = llm.plan, answerer: Answerer = llm.answer):
        self.config = config
        self.retriever = Retriever(conn, embedder, config.params, nominatim)
        self.planner = planner
        self.answerer = answerer

    async def run(self, q: Question) -> Outcome:
        try:
            plan = await self.planner(q.question)
        except PlanError as e:
            return Outcome(error=f"計畫看不懂：{e}")
        sections = self.retriever.retrieve(plan, q.question)
        answer = await self.answerer(q.question, sections) if self.config.answer else None
        return Outcome(sections, plan, answer)

    async def run_all(self, questions: list[Question], concurrency: int = 4,
                      progress: Callable[[Question, Outcome], None] | None = None) -> dict[str, Outcome]:
        """逐題跑，最多同時 concurrency 題在等 LLM。LLM 本身的錯誤（例如額度用完）讓整批停下。"""
        sem = asyncio.Semaphore(concurrency)

        async def one(q: Question) -> tuple[str, Outcome]:
            async with sem:
                out = await self.run(q)
            if progress:
                progress(q, out)
            return q.key, out

        return dict(await asyncio.gather(*(one(q) for q in questions)))
