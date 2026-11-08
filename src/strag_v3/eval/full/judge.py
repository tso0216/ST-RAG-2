"""答案評審：呼叫 Opus，逐條判斷答案有沒有涵蓋 `expect`、有沒有時間誤植（規則見 `judge.md`）。

評審預設和生成器用同一個模型（`rag.llm.MODEL`），這是研究者的決定，結果檔裡會註明（`note`）。
評審結果快取在 SQLite（`judge_cache`），以模型和完整 prompt 當 key；prompt、答案或證據變了才重新呼叫。
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Awaitable, Callable

from service.llm import call
from ...rag.llm import MODEL, build_answer_prompt
from ..metrics import Outcome
from ..questions import Question
from .answer import Claim, ExpectCheck, Judgement

SYSTEM_PATH = Path(__file__).with_name("judge.md")

CACHE_SCHEMA = """CREATE TABLE IF NOT EXISTS judge_cache (
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    output TEXT NOT NULL,
    PRIMARY KEY (model, prompt_hash)
)"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "expect": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"covered": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["covered", "reason"],
                "additionalProperties": False,
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "content_ids": {"type": "array", "items": {"type": "integer"}},
                    "misattributed": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["claim", "content_ids", "misattributed", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["expect", "claims"],
    "additionalProperties": False,
}

Call = Callable[[str, str, dict, str], Awaitable[dict]]


class JudgeError(ValueError):
    pass


def build_prompt(q: Question, out: Outcome) -> str:
    """評審看到的跟生成器看到的是同一份輸入（含各段檢索條件和證據的標記），再加上 `when`、`expect` 和答案。"""
    when = q.when_raw if q.when is not None else "不限時間"
    return "\n\n".join([
        f"問題問的時間（when）：{json.dumps(when, ensure_ascii=False)}",
        "答案重點（expect）：\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(q.expect, 1)),
        f"系統的答案：\n{out.answer}",
        f"系統回答時看到的輸入：\n<input>\n{build_answer_prompt(q.question, out.sections)}\n</input>",
    ])


def asks_time(q: Question, out: Outcome) -> bool:
    """題目或計畫有沒有限定任何時間；都沒有時不算時間誤植。"""
    return q.when is not None or any(sq.time is not None for sq in (out.plan.sub_queries if out.plan else ()))


class Judge:
    """評審一題答案；結果快取在 conn。call 預設呼叫 Opus。"""

    def __init__(self, conn: sqlite3.Connection, call: Call = call, model: str = MODEL):
        self.conn = conn
        self.call = call
        self.model = model
        conn.execute(CACHE_SCHEMA)

    def note(self) -> str:
        if self.model == MODEL:
            return f"評審和生成器用同一個模型（{MODEL}），這是研究者的決定。"
        return f"評審用 {self.model}，生成器用 {MODEL}。"

    async def judge(self, q: Question, out: Outcome) -> Judgement | None:
        """沒有答案時（沒開生成、這題出錯）不評，回傳 None。"""
        if out.answer is None:
            return None
        system = SYSTEM_PATH.read_text()
        user = build_prompt(q, out)
        raw = await self._cached(system, user)
        if len(raw["expect"]) != len(q.expect):
            raise JudgeError(f"{q.key}：評審給了 {len(raw['expect'])} 條 expect 判斷，題目有 {len(q.expect)} 條")
        return Judgement(
            tuple(ExpectCheck(p, r["covered"], r["reason"]) for p, r in zip(q.expect, raw["expect"])),
            None if not asks_time(q, out) else tuple(
                Claim(c["claim"], tuple(c["content_ids"]), c["misattributed"], c["reason"]) for c in raw["claims"]),
        )

    async def _cached(self, system: str, user: str) -> dict:
        key = hashlib.sha256(f"{system}\0{user}".encode()).hexdigest()
        row = self.conn.execute("SELECT output FROM judge_cache WHERE model = ? AND prompt_hash = ?",
                                (self.model, key)).fetchone()
        if row:
            return json.loads(row[0])
        out = await self.call(system, user, JUDGE_SCHEMA, self.model)
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO judge_cache (model, prompt_hash, output) VALUES (?, ?, ?)",
                              (self.model, key, json.dumps(out, ensure_ascii=False)))
        return out
