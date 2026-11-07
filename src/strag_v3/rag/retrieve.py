"""檢索：輸入檢索計畫，輸出分好組的證據。

每個子查詢：
- space：用日文名稱、城市、種類解析成 OSM 物件（見 `place.py`），解析不到就當作沒有這個地點，回傳空結果；留空不限地點。
  景點只取它本身的片段；區域取它本身的片段，加上範圍裡所有地點的片段。
- time：月份、平日／假日、時段三個維度硬過濾（見 `timematch.py`）；留空的維度不限。
- 語意分數：aspect（沒有就用原問題）跟片段內容的 embedding cosine。
- 分數 = 語意分數；片段有任何一個時間維度是 `不明` 時，再乘上 unknown_discount。
- 門檻：語意分數 ≥ 該子查詢最高分 − δ，過門檻的全部取。
- 一筆都沒有時依序退讓，各只退一次：
  1. 時間退讓：時段和月份各往外擴一格，同一個地點再查，證據標成時間退讓。
  2. 空間退讓：退到外圍行政區，照區域的規則取片段，時間用原本的條件，證據標成空間退讓。
     地點解析得到、但沒有任何片段時也照常退讓；沒有外圍行政區就不退。
  3. 還是沒有就回傳空結果，附上問的地點有資料的時段和月份，以及各有幾筆。
  兩種退讓可以各自用 Params 關掉。

各子查詢的證據再依計畫的 compose 和 group_by 整理成段和分組（見 `group.py`）。
"""
import sqlite3
from collections import Counter

from .embedding import Embedder, cosine
from .evidence import Available, Evidence, Section, SubQueryResult
from .group import build_sections
from ..place import Nominatim, Places
from .params import DEFAULT, Params
from .plan import Plan, SubQuery
from .store import Content, contents
from .timematch import CONTENT_SLOTS, TimeQuery, month_order


class Retriever:
    def __init__(self, conn: sqlite3.Connection, embedder: Embedder, params: Params = DEFAULT,
                 nominatim: Nominatim | None = None):
        """nominatim 是 None 時，地點只從快取解析。"""
        self.conn = conn
        self.embedder = embedder
        self.params = params
        self.places = Places(conn, nominatim)

    def retrieve(self, plan: Plan, question: str) -> list[Section]:
        """依計畫逐一跑子查詢，再依 compose 和 group_by 把證據整理成交給生成器的段和分組。"""
        results = [self._retrieve_one(sq, question) for sq in plan.sub_queries]
        return build_sections(plan, results)

    def _retrieve_one(self, sq: SubQuery, question: str) -> SubQueryResult:
        """原本的條件 → 時間退讓 → 空間退讓，哪一步有證據就停。space 留空時不限地點，也不做空間退讓。"""
        p = self.params
        outer = None
        if sq.space is None:
            own = contents(self.conn, None)
        else:
            place = self.places.resolve(sq.space.name_ja, sq.space.city, sq.space.kind)
            if place is None:
                return SubQueryResult(sq, [])
            own = contents(self.conn, self.places.scope(place))
            outer = self.places.outer(place)
        attempts: list[tuple[list[Content], TimeQuery | None, bool, str | None]] = [(own, sq.time, False, None)]
        if p.time_backoff and sq.time and (wide := sq.time.widened()):
            attempts.append((own, wide, True, None))
        if p.space_backoff and outer:
            attempts.append((contents(self.conn, self.places.scope(outer)), sq.time, False, outer.name))
        for pool, time, time_backoff, backoff_area in attempts:
            if evidence := self._run(sq, question, pool, time, time_backoff, backoff_area):
                return SubQueryResult(sq, evidence)
        return SubQueryResult(sq, [], available=_available(own))

    def _run(self, sq: SubQuery, question: str, pool: list[Content], time: TimeQuery | None,
             time_backoff: bool, backoff_area: str | None) -> list[Evidence]:
        candidates = [c for c in pool if time is None or time.matches(c.time)]
        if not candidates:
            return []

        p = self.params
        qvec, *cvecs = self.embedder.embed([sq.aspect or question] + [c.text for c in candidates])
        sems = [cosine(qvec, v) for v in cvecs]
        floor = max(sems) - p.delta

        out = [
            Evidence(c.id, c.article_id, c.place_id, c.place, c.time, c.text, semantic=sem,
                     score=sem * (p.unknown_discount if c.time.unknown else 1.0),
                     time_backoff=time_backoff, space_backoff=backoff_area is not None,
                     backoff_area=backoff_area, time_unknown=c.time.unknown)
            for c, sem in zip(candidates, sems) if sem >= floor
        ]
        out.sort(key=lambda e: (-e.score, e.content_id))
        return out


def _available(pool: list[Content]) -> Available:
    """問的地點（區域含底下的地點）有資料的時段和月份，各有幾筆。時段照固定順序，月份照起始月份。"""
    slots = Counter(c.time.time for c in pool)
    months = Counter(c.time.month for c in pool)
    return Available(
        time=tuple((s, slots[s]) for s in CONTENT_SLOTS if slots[s]),
        month=tuple((m, months[m]) for m in sorted(months, key=month_order)),
    )
