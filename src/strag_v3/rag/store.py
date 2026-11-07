"""DB 讀取：片段和景點名稱。檢索只讀 DB，寫入在 `extract/store.py`。"""
import sqlite3
from dataclasses import dataclass

from .timedist import TimeSpec


@dataclass(frozen=True)
class Content:
    """一個片段：DB `content` 表的一列。"""
    id: int
    article_id: str
    place: str
    time: TimeSpec
    text: str


def place_names(conn: sqlite3.Connection) -> list[str]:
    """DB `place` 表的景點名稱。"""
    return [name for (name,) in conn.execute("SELECT name FROM place ORDER BY id")]


def contents(conn: sqlite3.Connection, places: frozenset[str] | None) -> list[Content]:
    """景點名稱在 places 裡的片段，依 id 排序；places 是 None 時不限地點。"""
    sql = "SELECT id, article_id, poi_name, month, day_type, time, content FROM content"
    args: tuple = ()
    if places is not None:
        sql += f" WHERE poi_name IN ({', '.join('?' * len(places))})"
        args = tuple(sorted(places))
    return [Content(cid, aid, place, TimeSpec(month, day_type, time), text or "")
            for cid, aid, place, month, day_type, time, text in conn.execute(sql + " ORDER BY id", args)]
