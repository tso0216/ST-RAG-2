"""從 DB 讀片段：評審要片段全文和時間標籤，指標要時間標籤，`dense_frag`、`dense_filter` 要內容和地點名稱。"""
import sqlite3
from dataclasses import dataclass

from ...rag.timematch import UNKNOWN, TimeSpec


@dataclass(frozen=True)
class Fragment:
    id: int
    article_id: str
    # 地點的顯示名稱（繁中，沒有就用日文）
    place: str
    # 片段的地點所有寫法：抽取時寫的名稱、地點的繁中名稱、日文名稱（`dense_filter` 做字串比對用）
    names: tuple[str, ...]
    time: TimeSpec
    text: str


def load_fragments(conn: sqlite3.Connection) -> dict[int, Fragment]:
    rows = conn.execute(
        "SELECT c.id, c.article_id, COALESCE(p.name_zh, p.name_ja), c.poi_name, p.name_zh, p.name_ja,"
        " c.month, c.day_type, c.time, c.content FROM content c JOIN place p ON p.id = c.poi_id ORDER BY c.id")
    out = {}
    for cid, aid, place, poi_name, name_zh, name_ja, month, day_type, time, text in rows:
        names = tuple(dict.fromkeys(n for n in (poi_name, name_zh, name_ja) if n))
        out[cid] = Fragment(cid, aid, place, names, TimeSpec(month, day_type, time), text or "")
    return out


def when_text(t: TimeSpec) -> str:
    """片段的時間標籤寫成一句話，不明的維度不寫（跟出題工具 `qgen.py` 的寫法相同）。"""
    month = "" if t.month == UNKNOWN else f"{t.month} 月" if t.month[0].isdigit() else f"{t.month}天"
    parts = [month, *(x for x in (t.day_type, t.time) if x != UNKNOWN)]
    return " ".join(p for p in parts if p) or "時間沒寫"
