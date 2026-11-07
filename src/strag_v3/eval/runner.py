"""系統設定和逐題執行。

- `full`：完整系統（規劃器 → 檢索含兩種退讓 → 生成器）。
- `dense`：dense retrieval baseline，不經規劃器，只用原問題的語意分數取 top-k（見 `rag/dense.py`）。
- `hard`：硬過濾 baseline，跟完整系統一樣的規劃、時間比對和地點解析，但時間退讓和空間退讓都關掉。
- `oracle`：可以疊在 `full` 或 `hard` 上，用題目的 `when` 取代規劃器解析出來的時間；
  計畫有多個子查詢時，每個子查詢的時間都換成 `when`，`when` 沒填的維度不限。
"""
import asyncio
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from typing import Awaitable, Callable

from ..place import Nominatim
from ..rag import llm
from ..rag.dense import dense_retrieve
from ..rag.embedding import Embedder
from ..rag.evidence import Section
from ..rag.params import Params
from ..rag.plan import Plan, PlanError
from ..rag.retrieve import Retriever
from .metrics import Outcome
from .questions import Question

SYSTEMS = ("full", "dense", "hard")

Planner = Callable[[str], Awaitable[Plan]]
Answerer = Callable[[str, list[Section]], Awaitable[str]]


@dataclass(frozen=True)
class Config:
    system: str = "full"
    oracle: bool = False
    # dense 取幾筆
    k: int = 5
    # 要不要呼叫生成器產生答案
    answer: bool = True
    # full 和 hard 的檢索參數；hard 會再把兩種退讓關掉
    params: Params = field(default_factory=Params)

    def __post_init__(self):
        if self.system not in SYSTEMS:
            raise ValueError(f"系統設定只能是 {'、'.join(SYSTEMS)}，不是「{self.system}」")
        if self.oracle and self.system == "dense":
            raise ValueError("dense 不經規劃器，不能開 oracle")
        if self.k < 1:
            raise ValueError("k 至少是 1")

    @property
    def name(self) -> str:
        return self.system + ("+oracle" if self.oracle else "")

    @property
    def retrieval_params(self) -> Params:
        return replace(self.params, time_backoff=False, space_backoff=False) if self.system == "hard" else self.params

    def to_dict(self) -> dict:
        d = {"name": self.name, "system": self.system, "oracle": self.oracle, "answer": self.answer}
        if self.system == "dense":
            d["k"] = self.k
        else:
            d["params"] = asdict(self.retrieval_params)
        return d


def with_time(plan: Plan, when) -> Plan:
    """oracle：每個子查詢的時間都換成題目的 `when`。"""
    return replace(plan, sub_queries=tuple(replace(sq, time=when) for sq in plan.sub_queries))


class Runner:
    """用一個系統設定跑題目。規劃器和生成器預設呼叫 Opus，測試時可以換掉。"""

    def __init__(self, conn: sqlite3.Connection, embedder: Embedder, config: Config,
                 nominatim: Nominatim | None = None, planner: Planner = llm.plan, answerer: Answerer = llm.answer):
        self.conn = conn
        self.embedder = embedder
        self.config = config
        self.retriever = Retriever(conn, embedder, config.retrieval_params, nominatim)
        self.planner = planner
        self.answerer = answerer

    async def run(self, q: Question) -> Outcome:
        c = self.config
        plan = None
        if c.system == "dense":
            sections = dense_retrieve(self.conn, self.embedder, q.question, c.k)
        else:
            try:
                plan = await self.planner(q.question)
            except PlanError as e:
                return Outcome(error=f"計畫看不懂：{e}")
            if c.oracle:
                plan = with_time(plan, q.when)
            sections = self.retriever.retrieve(plan, q.question)
        answer = await self.answerer(q.question, sections) if c.answer else None
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
