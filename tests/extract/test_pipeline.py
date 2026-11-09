"""抽取的寫入：每筆的地點解析成 OSM 物件；有地點解析不到的文章整篇不寫入，並列出解析不到的名稱。不打外部 API。"""
import asyncio
import json
import sqlite3

from strag_v3.extract import llm, pipeline, store
from strag_v3.place import Places
from tests.conftest import SCHEMA
from tests.fake_nominatim import FakeNominatim


def item(poi_name, name_ja, kind="景點", content="排隊狀況"):
    return {"poi_name": poi_name, "name_ja": name_ja, "city": "東京", "kind": kind,
            "day_type": "平日", "time": "早上", "month": "1", "content": content}


def test_articles_with_unresolved_places_are_listed_and_not_written(tmp_path, monkeypatch):
    db = tmp_path / "main.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA)
    monkeypatch.setattr(store, "connect", lambda *_: sqlite3.connect(db))
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


def test_db_path_chooses_where_content_is_written(tmp_path, monkeypatch):
    db = tmp_path / "other.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA)

    async def fake_extract(article, use_cache=False):
        return [item("東京晴空塔", "東京スカイツリー")], False
    monkeypatch.setattr(llm, "extract", fake_extract)
    (p := tmp_path / "a.json").write_text(json.dumps({"id": "a", "text": "遊記"}))

    r = asyncio.run(pipeline.run([str(p)], nominatim=FakeNominatim(), db_path=db))

    assert r.written == 1
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT article_id FROM content").fetchall() == [("a",)]


def test_unresolved_place_is_retried_without_city_and_kind(tmp_path, monkeypatch):
    db = tmp_path / "main.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA)
    # 押上是區域，抽成景點、城市寫錯：照原樣查不到，拿掉城市和種類後取到區域
    wrong = {**item("押上", "押上", "景點"), "city": "大阪"}

    async def fake_extract(article, use_cache=False):
        return [wrong], False
    monkeypatch.setattr(llm, "extract", fake_extract)
    (p := tmp_path / "a.json").write_text(json.dumps({"id": "a", "text": "遊記"}))
    fake = FakeNominatim()

    r = asyncio.run(pipeline.run([str(p)], nominatim=fake, db_path=db))

    assert r.unresolved == [] and r.written == 1
    assert ("押上", "", "不限", False) in fake.calls
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT p.name_ja, p.kind FROM content c JOIN place p ON p.id = c.poi_id").fetchall() \
            == [("押上", "區域")]


def _articles(tmp_path, ids):
    paths = []
    for aid in ids:
        (p := tmp_path / f"{aid}.json").write_text(json.dumps({"id": aid, "text": "遊記"}))
        paths.append(str(p))
    return paths


def _db(tmp_path):
    db = tmp_path / "main.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA)
    return db


def test_jobs_limits_how_many_articles_are_extracted_at_once(tmp_path, monkeypatch):
    running = peak = 0

    async def fake_extract(article, use_cache=False):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return [item("東京晴空塔", "東京スカイツリー")], False
    monkeypatch.setattr(llm, "extract", fake_extract)
    paths = _articles(tmp_path, "abcde")

    r = asyncio.run(pipeline.run(paths, nominatim=FakeNominatim(), db_path=_db(tmp_path), jobs=2))

    assert peak == 2
    assert sorted(r.done) == sorted(paths) and r.written == 5


def test_llm_error_stops_batch_and_lists_unwritten_articles_as_pending(tmp_path, monkeypatch):
    async def fake_extract(article, use_cache=False):
        if article["id"] == "b":
            raise llm.LLMError("額度用完")
        return [item("東京晴空塔", "東京スカイツリー")], False
    monkeypatch.setattr(llm, "extract", fake_extract)
    paths = _articles(tmp_path, "abc")

    r = asyncio.run(pipeline.run(paths, nominatim=FakeNominatim(), db_path=_db(tmp_path)))

    assert r.error == "額度用完"
    assert r.done == [paths[0]] and r.pending == paths[1:]


def test_duplicate_article_is_extracted_once(tmp_path, monkeypatch):
    calls = []

    async def fake_extract(article, use_cache=False):
        calls.append(article["id"])
        return [item("東京晴空塔", "東京スカイツリー")], False
    monkeypatch.setattr(llm, "extract", fake_extract)
    paths = _articles(tmp_path, "a")

    r = asyncio.run(pipeline.run(paths * 2, nominatim=FakeNominatim(), db_path=_db(tmp_path), jobs=2))

    assert calls == ["a"] and r.skipped == [(paths[0], "重複")]


def test_alias_written_in_japanese_or_chinese_resolves_to_its_target(tmp_path, monkeypatch):
    db = _db(tmp_path)
    fake = FakeNominatim()
    with sqlite3.connect(db) as c:
        Places(c, fake).add_alias("上野公園", "上野恩賜公園", "東京", "景點")

    async def fake_extract(article, use_cache=False):
        return [
            item("上野恩賜公園", "上野恩賜公園"),
            item("上野公園", "上野公園"),        # 日文寫成別名
            item("上野公園", "ウエノパーク"),    # 只有繁中寫成別名
            item("上野公園", "上野公園", "區域"),  # 別名指的是景點，區域照常解析
        ], False
    monkeypatch.setattr(llm, "extract", fake_extract)

    r = asyncio.run(pipeline.run(_articles(tmp_path, "a"), nominatim=fake, db_path=db))

    assert r.unresolved == [] and r.written == 4
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT p.osm_id, p.kind FROM content c JOIN place p ON p.id = c.poi_id ORDER BY c.id")
        assert rows.fetchall() == [(7, "景點"), (7, "景點"), (7, "景點"), (202, "區域")]
        # 外圍行政區查的是區域，也不會被景點的別名搶走
        assert c.execute("SELECT o.osm_id FROM place p JOIN place o ON o.id = p.outer_id WHERE p.osm_id = 7"
                         ).fetchall() == [(202,)]
