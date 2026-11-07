"""DB 寫入：place 用名稱找或建，content 整篇替換。"""
import sqlite3
from pathlib import Path

from .paths import DB_PATH


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _place_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM place WHERE name = ? ORDER BY id LIMIT 1", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO place (name) VALUES (?)", (name,)).lastrowid


def has_article(conn: sqlite3.Connection, article_id: str) -> bool:
    return conn.execute("SELECT 1 FROM content WHERE article_id = ? LIMIT 1", (article_id,)).fetchone() is not None


def replace_article(conn: sqlite3.Connection, article_id: str, items: list[dict]) -> int:
    """在一個 transaction 裡刪掉這篇的舊資料再寫入，回傳寫入筆數。"""
    with conn:
        conn.execute("DELETE FROM content WHERE article_id = ?", (article_id,))
        for it in items:
            pid = _place_id(conn, it["poi_name"])
            conn.execute(
                "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (article_id, pid, it["poi_name"], it["day_type"], it["time"], it["month"], it["content"]),
            )
    return len(items)
