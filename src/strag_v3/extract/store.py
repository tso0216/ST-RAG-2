"""DB 寫入：content 整篇替換。地點由 `place.py` 解析並寫進 place 表，這裡只拿到 place id。"""
import sqlite3
from pathlib import Path

from .paths import DB_PATH


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def has_article(conn: sqlite3.Connection, article_id: str) -> bool:
    return conn.execute("SELECT 1 FROM content WHERE article_id = ? LIMIT 1", (article_id,)).fetchone() is not None


def replace_article(conn: sqlite3.Connection, article_id: str, items: list[dict], place_ids: list[int]) -> int:
    """在一個 transaction 裡刪掉這篇的舊資料再寫入，回傳寫入筆數。place_ids 跟 items 一一對應。"""
    with conn:
        conn.execute("DELETE FROM content WHERE article_id = ?", (article_id,))
        for it, pid in zip(items, place_ids, strict=True):
            conn.execute(
                "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (article_id, pid, it["poi_name"], it["day_type"], it["time"], it["month"], it["content"]),
            )
    return len(items)
