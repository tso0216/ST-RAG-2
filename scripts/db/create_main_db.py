import argparse
import sqlite3
from pathlib import Path

# place：一列一個 OSM 物件
# content.poi_name：抽取時寫的原始名稱，只是紀錄；地點以 poi_id 為準
# embedding、nominatim_cache 兩張快取表和 place_alias 由用到的模組自己建（rag/embedding.py、place.py）；
# --rebuild 不動它們，所以別名重建後照樣有效
SCHEMA = """
CREATE TABLE IF NOT EXISTS place (
    id         INTEGER PRIMARY KEY,
    osm_type   TEXT    NOT NULL,
    osm_id     INTEGER NOT NULL,
    kind       TEXT    NOT NULL CHECK (kind IN ('景點','區域')),
    name_ja    TEXT    NOT NULL,                  -- OSM 上的名稱
    name_zh    TEXT,                              -- 第一次抽到的繁中名稱，顯示用
    city       TEXT    NOT NULL DEFAULT '',
    lat        REAL    NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon        REAL    NOT NULL CHECK (lon BETWEEN -180 AND 180),
    place_rank INTEGER NOT NULL,                  -- Nominatim 的 place_rank，越大越小
    boundary   TEXT,                              -- 區域的範圍（geojson）
    outer_id   INTEGER REFERENCES place (id),     -- 外圍行政區
    UNIQUE (osm_type, osm_id)
);

CREATE TABLE IF NOT EXISTS content (
    id         INTEGER PRIMARY KEY,
    article_id TEXT    NOT NULL,
    poi_id     INTEGER NOT NULL REFERENCES place (id) ON DELETE CASCADE,
    poi_name   TEXT    NOT NULL,
    day_type   TEXT    NOT NULL CHECK (day_type IN ('平日','假日','不明')),
    time       TEXT    NOT NULL,
    month      TEXT    NOT NULL,
    content    TEXT
);

-- 抽取前用 article_id 判斷文章是否已在 DB
CREATE INDEX IF NOT EXISTS idx_content_article ON content (article_id);

-- place 加上片段數：直接指到這個地點的片段，區域不含範圍裡其他地點的片段。查的時候才算，不會跟 content 不同步
CREATE VIEW IF NOT EXISTS place_stats AS
SELECT p.*, count(c.id) AS content_count
FROM place p LEFT JOIN content c ON c.poi_id = p.id
GROUP BY p.id;
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/main.db")
    ap.add_argument("--rebuild", action="store_true",
                    help="刪掉 content 和 place 表再重建（保留 embedding 和 Nominatim 快取），之後要重新抽取")
    a = ap.parse_args()
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    with connect(a.db) as conn:
        if a.rebuild:
            conn.execute("DROP VIEW IF EXISTS place_stats")
            conn.execute("DROP TABLE IF EXISTS content")
            conn.execute("DROP TABLE IF EXISTS place")
        conn.executescript(SCHEMA)
    print(f"已{'重建' if a.rebuild else '建立'}資料表於 {a.db}")


if __name__ == "__main__":
    main()
