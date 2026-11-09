"""相關判斷（gate=jev）：每個候選片段各問 JEV 一次「是否和問題相關」，回傳 noul。

一次只送一組問題 × 一個片段：`state` 是原問題、aspect（沒有就不放這個 key）和片段內容，不送時間標籤。
結果快取在 DB 的 `jev_cache` 表，以（模型, 判準 hash, 原問題, aspect, 片段 id）為鍵；有快取就只讀快取，不重問——
JEV 同樣的輸入結果不固定，而且模型版本會停用，重現實驗靠快取。
"""
import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime

from service.jev import JEVClient

from .store import Content

INSTRUCTIONS = "片段是否和問題相關？不用判斷時間是否符合。"
CRITERIA = {"true": "片段提到和問題相關的經驗。", "false": "片段和問題無關。"}
CRITERIA_HASH = hashlib.sha256(json.dumps({"instructions": INSTRUCTIONS, "criteria": CRITERIA},
                                          ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]

# aspect 沒有時存空字串；answered_model 是回應裡實際回答的模型版本
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jev_cache (
    model          TEXT    NOT NULL,
    criteria_hash  TEXT    NOT NULL,
    question       TEXT    NOT NULL,
    aspect         TEXT    NOT NULL,
    content_id     INTEGER NOT NULL,
    noul           REAL    NOT NULL,
    answered_model TEXT    NOT NULL,
    created_at     TEXT    NOT NULL,
    PRIMARY KEY (model, criteria_hash, question, aspect, content_id)
)
"""


class JEVGate:
    """最多同時 concurrency 個請求在等 JEV（同一個 gate 的所有子查詢共用）。"""

    def __init__(self, conn: sqlite3.Connection, client: JEVClient, model: str, concurrency: int):
        self.conn = conn
        self.client = client
        self.model = model
        self.sem = asyncio.Semaphore(concurrency)
        conn.execute(CACHE_SCHEMA)

    async def nouls(self, question: str, aspect: str | None, candidates: list[Content]) -> list[float]:
        """其中一個請求失敗時，取消其他還沒問完的請求，再把錯誤往上丟。"""
        tasks = [asyncio.ensure_future(self._one(question, aspect, c)) for c in candidates]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for t in tasks:
                t.cancel()
            raise

    async def _one(self, question: str, aspect: str | None, c: Content) -> float:
        key = (self.model, CRITERIA_HASH, question, aspect or "", c.id)
        if (cached := self._cached(key)) is not None:
            return cached
        state = {"question": question, **({"aspect": aspect} if aspect else {}), "passage": c.text}
        async with self.sem:
            a = await self.client.noul(self.model, state, INSTRUCTIONS, CRITERIA)
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO jev_cache (model, criteria_hash, question, aspect, content_id, noul,"
                " answered_model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*key, a.noul, a.model, datetime.now().astimezone().isoformat(timespec="seconds")))
        # 同一個鍵同時被問兩次時，以先寫進快取的為準，之後重跑才會一致
        cached = self._cached(key)
        return a.noul if cached is None else cached

    def _cached(self, key: tuple) -> float | None:
        row = self.conn.execute(
            "SELECT noul FROM jev_cache WHERE model = ? AND criteria_hash = ? AND question = ? AND aspect = ?"
            " AND content_id = ?", key).fetchone()
        return row[0] if row else None
