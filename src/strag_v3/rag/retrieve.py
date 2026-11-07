"""檢索：輸入檢索計畫，輸出每個子查詢取回的證據。

每個子查詢：
- space：片段的景點名稱要完全相同；留空不限地點。
- time：轉成時間分布，跟片段的時間分布算時空重疊度；留空不限時間。
- 語意分數：aspect（沒有就用原問題）跟片段內容的 embedding cosine。
- 分數 = 語意分數 × (ε + 時空重疊度)。
- 門檻：時空重疊度 ≥ overlap_min，且語意分數 ≥ 該子查詢最高分 − δ；兩個都過才取，全部取。
"""
import sqlite3
from dataclasses import dataclass

from .embedding import Embedder, cosine
from .params import DEFAULT, Params
from .plan import Plan, SubQuery, TimeSpec
from .timedist import overlap, to_dist


@dataclass(frozen=True)
class Evidence:
    content_id: int
    article_id: str
    place: str
    month: str
    day_type: str
    time: str
    content: str
    overlap: float
    semantic: float
    score: float
    backoff: bool = False


@dataclass(frozen=True)
class SubQueryResult:
    sub_query: SubQuery
    evidence: list[Evidence]


class Retriever:
    def __init__(self, conn: sqlite3.Connection, embedder: Embedder, params: Params = DEFAULT):
        self.conn = conn
        self.embedder = embedder
        self.params = params

    def retrieve(self, plan: Plan, question: str) -> list[SubQueryResult]:
        return [SubQueryResult(sq, self._run(sq, question)) for sq in plan.sub_queries]

    def _run(self, sq: SubQuery, question: str) -> list[Evidence]:
        p = self.params
        t = sq.time or TimeSpec()
        qdist = to_dist(t.month, t.day_type, t.time, p)

        sql = "SELECT id, article_id, poi_name, month, day_type, time, content FROM content"
        args: tuple = ()
        if sq.space:
            sql += " WHERE poi_name = ?"
            args = (sq.space,)
        candidates = []
        for row in self.conn.execute(sql + " ORDER BY id", args):
            cid, aid, place, month, day_type, time, text = row
            ov = overlap(qdist, to_dist(month, day_type, time, p))
            if ov >= p.overlap_min:
                candidates.append((row, ov))
        if not candidates:
            return []

        texts = [sq.aspect or question] + [row[6] or "" for row, _ in candidates]
        qvec, *cvecs = self.embedder.embed(texts)
        sems = [cosine(qvec, v) for v in cvecs]
        floor = max(sems) - p.delta

        out = [
            Evidence(row[0], row[1], row[2], row[3], row[4], row[5], row[6] or "",
                     overlap=ov, semantic=sem, score=sem * (p.epsilon + ov))
            for (row, ov), sem in zip(candidates, sems) if sem >= floor
        ]
        out.sort(key=lambda e: (-e.score, e.content_id))
        return out
