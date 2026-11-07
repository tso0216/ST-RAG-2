"""檢索：輸入檢索計畫，輸出每個子查詢取回的證據。

每個子查詢：
- space：用景點階層解析成節點（先比別名，再用名稱 embedding 找最近的），節點和所有子孫的片段都算；留空不限地點。
  一筆都沒過門檻時退一層到母節點再查，證據標成退讓；還是沒有就回傳空結果，附上最接近的時段。
- time：轉成時間分布，跟片段的時間分布算時空重疊度；留空不限時間。
- 語意分數：aspect（沒有就用原問題）跟片段內容的 embedding cosine。
- 分數 = 語意分數 × (ε + 時空重疊度)。片段有任何一個時間維度是 `不明` 時，再乘上 unknown_discount。
- 門檻：時空重疊度 ≥ overlap_min，且語意分數 ≥ 該子查詢最高分 − δ；兩個都過才取，全部取。
"""
import sqlite3
from dataclasses import replace

from .embedding import Embedder, cosine
from .evidence import Evidence, Section, SubQueryResult
from .group import build_sections
from .hierarchy import Hierarchy
from .nearest import nearest_times
from .params import DEFAULT, Params
from .plan import Plan, SubQuery, TimeSpec
from .timedist import has_unknown, overlap, to_dist


class Retriever:
    def __init__(self, conn: sqlite3.Connection, embedder: Embedder, params: Params = DEFAULT,
                 hierarchy: Hierarchy | None = None):
        self.conn = conn
        self.embedder = embedder
        self.params = params
        self.hierarchy = hierarchy or Hierarchy()

    def retrieve(self, plan: Plan, question: str) -> list[Section]:
        """依計畫逐一跑子查詢，再依 compose 和 group_by 把證據整理成交給生成器的段和分組。"""
        places = self.hierarchy.with_places(name for (name,) in self.conn.execute("SELECT name FROM place ORDER BY id"))
        results = [self._retrieve_one(sq, question, places) for sq in plan.sub_queries]
        return build_sections(plan, results, places, self.params)

    def _retrieve_one(self, sq: SubQuery, question: str, places: Hierarchy) -> SubQueryResult:
        """先查 space 的節點；一筆都沒過門檻時退一層到母節點再查，取回的證據標成退讓。

        還是沒有就回傳空結果，附上查過的範圍裡最接近的時段。時間門檻不放寬。
        space 留空時不限地點（範圍是 None）。
        """
        scopes = [None] if sq.space is None else places.scopes(sq.space, self.embedder, self.params.place_min_sim)
        evidence = self._run(sq, question, scopes[0])
        if not evidence and len(scopes) > 1:
            evidence = [replace(e, backoff=True) for e in self._run(sq, question, scopes[1])]
        if evidence:
            return SubQueryResult(sq, evidence)
        return SubQueryResult(sq, [], nearest=nearest_times(self.conn, scopes[-1], sq.time, self.params))

    def _run(self, sq: SubQuery, question: str, places: frozenset[str] | None = None) -> list[Evidence]:
        p = self.params
        t = sq.time or TimeSpec()
        qdist = to_dist(t.month, t.day_type, t.time, p)

        sql = "SELECT id, article_id, poi_name, month, day_type, time, content FROM content"
        args: tuple = ()
        if places is not None:
            sql += f" WHERE poi_name IN ({', '.join('?' * len(places))})"
            args = tuple(sorted(places))
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
                     overlap=ov, semantic=sem, score=sem * (p.epsilon + ov)
                     * (p.unknown_discount if has_unknown(row[3], row[4], row[5]) else 1.0))
            for (row, ov), sem in zip(candidates, sems) if sem >= floor
        ]
        out.sort(key=lambda e: (-e.score, e.content_id))
        return out
