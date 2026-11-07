"""DB 讀取：片段。檢索只讀 content 表，寫入在 `extract/store.py`；地點的查詢在 `place.py`。"""
import sqlite3
from dataclasses import dataclass

from .timematch import TimeSpec


@dataclass(frozen=True)
class Content:
    """一個片段：DB `content` 表的一列。"""
    id: int
    article_id: str
    place_id: int
    # 地點的顯示名稱：第一次抽到的繁中名稱，沒有就用 OSM 上的名稱
    place: str
    time: TimeSpec
    text: str


def contents(conn: sqlite3.Connection, place_ids: frozenset[int] | None) -> list[Content]:
    """地點在 place_ids 裡的片段，依 id 排序；place_ids 是 None 時不限地點。"""
    sql = ("SELECT c.id, c.article_id, c.poi_id, COALESCE(p.name_zh, p.name_ja), c.month, c.day_type, c.time, c.content"
           " FROM content c JOIN place p ON p.id = c.poi_id")
    args: tuple = ()
    if place_ids is not None:
        sql += f" WHERE c.poi_id IN ({', '.join('?' * len(place_ids))})"
        args = tuple(sorted(place_ids))
    return [Content(cid, aid, pid, place, TimeSpec(month, day_type, time), text or "")
            for cid, aid, pid, place, month, day_type, time, text in conn.execute(sql + " ORDER BY c.id", args)]
