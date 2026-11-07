"""檢索 seam：輸入檢索計畫，看取回哪些片段、怎麼排序。不打外部 API。"""
import pytest

from strag_v3.rag.embedding import CachedEmbedder
from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan
from strag_v3.rag.retrieve import Retriever


class KeywordEmbedder:
    """假的 embedding：每個關鍵字一維，文字含該字就是 1；全部沒命中時給一個共同的底。"""

    model = "fake-keyword"

    def __init__(self, keywords=("富士山", "排隊", "夕陽", "拉麵")):
        self.keywords = keywords
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0 if k in t else 0.0 for k in self.keywords] + [0.1] for t in texts]


def add(conn, place, day_type, time, month, content="排隊狀況", article="a1"):
    pid = conn.execute("SELECT id FROM place WHERE name = ?", (place,)).fetchone()
    pid = pid[0] if pid else conn.execute("INSERT INTO place (name) VALUES (?)", (place,)).lastrowid
    return conn.execute(
        "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)", (article, pid, place, day_type, time, month, content)).lastrowid


def plan(space="晴空塔", aspect="排隊", **time):
    return Plan.from_dict({"sub_queries": [{"space": space, "time": time or None, "aspect": aspect}]})


def ids(conn, p, params=Params(), question="排隊要多久"):
    [result] = Retriever(conn, KeywordEmbedder(), params).retrieve(p, question)
    return [e.content_id for e in result.evidence]


def test_dusk_query_takes_17_and_16_17_but_blocks_morning(conn):
    at17 = add(conn, "晴空塔", "假日", "17", "1")
    at16_17 = add(conn, "晴空塔", "假日", "16-17", "1")
    morning = add(conn, "晴空塔", "假日", "早上", "1")

    got = ids(conn, plan(time="16-18"))

    assert at17 in got and at16_17 in got
    assert morning not in got


def test_evening_period_word_is_soft_matched_by_dusk(conn):
    evening = add(conn, "晴空塔", "不明", "晚上", "1")
    assert ids(conn, plan(time="16-18")) == [evening]


@pytest.mark.parametrize("month", ["12-2", "冬"])
def test_cross_year_range_and_winter_match_january(conn, month):
    jan = add(conn, "晴空塔", "平日", "10", "1")
    may = add(conn, "晴空塔", "平日", "10", "5")

    got = ids(conn, plan(month=month))

    assert jan in got
    assert may not in got


def test_january_query_matches_winter_content(conn):
    winter = add(conn, "晴空塔", "平日", "10", "冬")
    summer = add(conn, "晴空塔", "平日", "10", "夏")
    assert ids(conn, plan(month="1")) == [winter]


def test_hour_range_wraps_past_midnight(conn):
    late = add(conn, "晴空塔", "假日", "0", "8")
    noon = add(conn, "晴空塔", "假日", "12", "8")
    assert ids(conn, plan(time="22-1")) == [late]


def test_empty_time_does_not_limit_time(conn):
    rows = [add(conn, "晴空塔", d, t, m) for d, t, m in
            [("平日", "7", "1"), ("假日", "晚上", "8"), ("不明", "不明", "不明")]]
    assert sorted(ids(conn, plan())) == rows


def test_omitted_time_dimension_does_not_limit_it(conn):
    weekday = add(conn, "晴空塔", "平日", "7", "1")
    weekend_night = add(conn, "晴空塔", "假日", "21", "1")
    other_month = add(conn, "晴空塔", "平日", "7", "6")

    assert sorted(ids(conn, plan(month="1"))) == [weekday, weekend_night]


def test_day_type_must_match(conn):
    weekday = add(conn, "晴空塔", "平日", "10", "1")
    weekend = add(conn, "晴空塔", "假日", "10", "1")
    assert ids(conn, plan(day_type="平日")) == [weekday]


def test_empty_space_does_not_limit_place(conn):
    a = add(conn, "晴空塔", "平日", "10", "1")
    b = add(conn, "淺草寺", "平日", "10", "1")
    assert sorted(ids(conn, plan(space=None, month="1"))) == [a, b]


def test_space_matches_exact_place_name_only(conn):
    tower = add(conn, "晴空塔", "平日", "10", "1")
    town = add(conn, "晴空塔城", "平日", "10", "1")
    assert ids(conn, plan(month="1")) == [tower]


def test_semantic_relative_threshold_drops_off_topic_content(conn):
    fuji = add(conn, "晴空塔", "平日", "10", "1", content="早上看得到富士山")
    ramen = add(conn, "晴空塔", "平日", "10", "1", content="附近的拉麵店")

    assert ids(conn, plan(aspect="富士山", month="1")) == [fuji]


def test_aspect_falls_back_to_question(conn):
    fuji = add(conn, "晴空塔", "平日", "10", "1", content="早上看得到富士山")
    ramen = add(conn, "晴空塔", "平日", "10", "1", content="附近的拉麵店")

    assert ids(conn, plan(aspect=None), question="看得到富士山嗎") == [fuji]


def test_better_time_match_ranks_first_and_evidence_carries_scores(conn):
    exact = add(conn, "晴空塔", "平日", "10", "1")
    vague = add(conn, "晴空塔", "平日", "10", "冬", article="a2")  # 三分之一落在一月

    unsmoothed = Params(month_bandwidth=0, hour_bandwidth=0)
    [result] = Retriever(conn, KeywordEmbedder(), unsmoothed).retrieve(plan(month="1"), "排隊")
    first, second = result.evidence

    assert (first.content_id, second.content_id) == (exact, vague)
    assert first.overlap == pytest.approx(1.0)
    assert second.overlap == pytest.approx(1 / 3)
    assert first.semantic == pytest.approx(second.semantic)
    assert second.article_id == "a2"
    assert not first.backoff


def test_no_candidates_returns_empty(conn):
    add(conn, "晴空塔", "平日", "10", "5")
    assert ids(conn, plan(month="1")) == []


def test_embedding_cache_skips_repeated_texts(conn):
    inner = KeywordEmbedder()
    cached = CachedEmbedder(inner, conn)

    first = cached.embed(["富士山", "排隊"])
    second = cached.embed(["排隊", "富士山", "富士山"])

    assert len(inner.calls) == 1
    assert second == [first[1], first[0], first[0]]


def test_embedding_cache_is_keyed_by_model(conn):
    a, b = KeywordEmbedder(), KeywordEmbedder()
    b.model = "other-model"
    CachedEmbedder(a, conn).embed(["富士山"])
    CachedEmbedder(b, conn).embed(["富士山"])
    assert len(b.calls) == 1
