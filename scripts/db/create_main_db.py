import argparse
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS place (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    lat  REAL CHECK (lat BETWEEN -90 AND 90),     
    lon  REAL CHECK (lon BETWEEN -180 AND 180),   
    UNIQUE (id, name)            
);

CREATE TABLE IF NOT EXISTS content (
    id         INTEGER PRIMARY KEY,
    article_id TEXT    NOT NULL,
    poi_id     INTEGER NOT NULL,
    poi_name   TEXT    NOT NULL,
    day_type   TEXT    NOT NULL CHECK (day_type IN ('平日','假日','不明')),
    time       TEXT    NOT NULL,
    month      TEXT    NOT NULL,
    content    TEXT,
    FOREIGN KEY (poi_id, poi_name) REFERENCES place (id, name)
        ON UPDATE CASCADE ON DELETE CASCADE
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")  
    return conn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/main.db")
    a = ap.parse_args()
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    with connect(a.db) as conn:
        conn.executescript(SCHEMA)
    print(f"已建立資料表於 {a.db}")


if __name__ == "__main__":
    main()
