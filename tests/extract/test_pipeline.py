"""抽取的寫入：每筆的地點解析成 OSM 物件；有地點解析不到的文章整篇不寫入，並列出解析不到的名稱。不打外部 API。"""
import asyncio
import json
import sqlite3

from strag_v3.extract import llm, pipeline, store
from tests.conftest import SCHEMA
from tests.fake_nominatim import FakeNominatim


def item(poi_name, name_ja, kind="景點", content="排隊狀況"):
    return {"poi_name": poi_name, "name_ja": name_ja, "city": "東京", "kind": kind,
            "day_type": "平日", "time": "早上", "month": "1", "content": content}


def test_articles_with_unresolved_places_are_listed_and_not_written(tmp_path, monkeypatch):
    db = tmp_path / "main.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA)
    monkeypatch.setattr(store, "connect", lambda: sqlite3.connect(db))
    extracted = {
        "good": [item("東京晴空塔", "東京スカイツリー"), item("晴空塔", "スカイツリー"), item("押上", "押上", "區域")],
        "bad": [item("東京晴空塔", "東京スカイツリー"), item("晴空塔展望台", "スカイツリー展望台")],
    }

    async def fake_extract(article, use_cache=False):
        return extracted[article["id"]], False
    monkeypatch.setattr(llm, "extract", fake_extract)
    paths = []
    for aid in extracted:
        (p := tmp_path / f"{aid}.json").write_text(json.dumps({"id": aid, "text": "遊記"}))
        paths.append(str(p))

    r = asyncio.run(pipeline.run(paths, nominatim=FakeNominatim()))

    assert r.unresolved == [("bad", ["晴空塔展望台（スカイツリー展望台，東京，景點）"])]
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT c.article_id, c.poi_name, p.name_ja, p.name_zh, p.kind FROM content c"
                         " JOIN place p ON p.id = c.poi_id ORDER BY c.id").fetchall()
    assert rows == [
        ("good", "東京晴空塔", "東京スカイツリー", "東京晴空塔", "景點"),
        ("good", "晴空塔", "東京スカイツリー", "東京晴空塔", "景點"),
        ("good", "押上", "押上", "押上", "區域"),
    ]
