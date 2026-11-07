"""檢索：輸入檢索計畫，輸出分好組的證據。

每個子查詢：
- space：用景點階層解析成節點（先比別名，再用名稱 embedding 找最近的），節點和所有子孫的片段都算；留空不限地點。
  一筆都沒過門檻時退一層到母節點再查，證據標成退讓；還是沒有就回傳空結果，附上最接近的時段。
- time：轉成時間分布，跟片段的時間分布算時空重疊度；留空不限時間。
- 語意分數：aspect（沒有就用原問題）跟片段內容的 embedding cosine。
- 分數 = 語意分數 × (ε + 時空重疊度)。片段有任何一個時間維度是 `不明` 時，再乘上 unknown_discount。
- 門檻：時空重疊度 ≥ overlap_min，且語意分數 ≥ 該子查詢最高分 − δ；兩個都過才取，全部取。

各子查詢的證據再依計畫的 compose 和 group_by 整理成段和分組（見 `group.py`）。
"""
import sqlite3

from .embedding import Embedder, cosine
from .evidence import Evidence, Section, SubQueryResult
from .group import build_sections
from .hierarchy import Hierarchy
from .nearest import nearest_times
from .params import DEFAULT, Params
from .plan import Plan, SubQuery
from .store import Content, contents, place_names
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
        places = self.hierarchy.with_places(place_names(self.conn))
        results = [self._retrieve_one(sq, question, places) for sq in plan.sub_queries]
        return build_sections(plan, results, places, self.params)

    def _retrieve_one(self, sq: SubQuery, question: str, places: Hierarchy) -> SubQueryResult:
        """先查 space 的節點；一筆都沒過門檻時退一層到母節點再查，取回的證據標成退讓。

        還是沒有就回傳空結果，附上查過的範圍裡最接近的時段。時間門檻不放寬。
        space 留空時不限地點（範圍是 None）。
        """
        scopes = [None] if sq.space is None else places.scopes(sq.space, self.embedder, self.params.place_min_sim)
        pool: list[Content] = []
        for backoff, scope in zip((False, True), scopes):
            pool = contents(self.conn, scope)
            if evidence := self._run(sq, question, pool, backoff):
                return SubQueryResult(sq, evidence)
        return SubQueryResult(sq, [], nearest=nearest_times(pool, sq.time, self.params))

    def _run(self, sq: SubQuery, question: str, pool: list[Content], backoff: bool) -> list[Evidence]:
        p = self.params
        qdist = to_dist(sq.time, p)
        candidates = [(c, ov) for c in pool if (ov := overlap(qdist, to_dist(c.time, p))) >= p.overlap_min]
        if not candidates:
            return []

        qvec, *cvecs = self.embedder.embed([sq.aspect or question] + [c.text for c, _ in candidates])
        sems = [cosine(qvec, v) for v in cvecs]
        floor = max(sems) - p.delta

        out = [
            Evidence(c.id, c.article_id, c.place, c.time, c.text, overlap=ov, semantic=sem,
                     score=sem * (p.epsilon + ov) * (p.unknown_discount if has_unknown(c.time) else 1.0),
                     backoff=backoff)
            for (c, ov), sem in zip(candidates, sems) if sem >= floor
        ]
        out.sort(key=lambda e: (-e.score, e.content_id))
        return out
