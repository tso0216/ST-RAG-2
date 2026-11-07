"""檢索 seam：輸入檢索計畫，看取回哪些片段、怎麼排序。不打外部 API。"""
import pytest

from strag_v3.rag.embedding import CachedEmbedder
from strag_v3.rag.params import Params


def ids(sections):
    return [e.content_id for s in sections for e in s.evidence]


def test_dusk_query_takes_17_and_16_17_but_blocks_morning(add, retrieve, sub):
    at17 = add("晴空塔", "假日", "17", "1")
    at16_17 = add("晴空塔", "假日", "16-17", "1")
    morning = add("晴空塔", "假日", "早上", "1")

    got = ids(retrieve(sub(time="16-18")))

    assert at17 in got and at16_17 in got
    assert morning not in got


def test_evening_period_word_is_soft_matched_by_dusk(add, retrieve, sub):
    evening = add("晴空塔", "不明", "晚上", "1")
    assert ids(retrieve(sub(time="16-18"))) == [evening]


@pytest.mark.parametrize("month", ["12-2", "冬"])
def test_cross_year_range_and_winter_match_january(add, retrieve, sub, month):
    jan = add("晴空塔", "平日", "10", "1")
    may = add("晴空塔", "平日", "10", "5")

    got = ids(retrieve(sub(month=month)))

    assert jan in got
    assert may not in got


def test_january_query_matches_winter_content(add, retrieve, sub):
    winter = add("晴空塔", "平日", "10", "冬")
    summer = add("晴空塔", "平日", "10", "夏")
    assert ids(retrieve(sub(month="1"))) == [winter]


def test_hour_range_wraps_past_midnight(add, retrieve, sub):
    late = add("晴空塔", "假日", "0", "8")
    noon = add("晴空塔", "假日", "12", "8")
    assert ids(retrieve(sub(time="22-1"))) == [late]


def test_empty_time_does_not_limit_time(add, retrieve, sub):
    rows = [add("晴空塔", d, t, m) for d, t, m in
            [("平日", "7", "1"), ("假日", "晚上", "8"), ("不明", "不明", "不明")]]
    assert sorted(ids(retrieve(sub()))) == rows


def test_omitted_time_dimension_does_not_limit_it(add, retrieve, sub):
    weekday = add("晴空塔", "平日", "7", "1")
    weekend_night = add("晴空塔", "假日", "21", "1")
    other_month = add("晴空塔", "平日", "7", "6")

    assert sorted(ids(retrieve(sub(month="1")))) == [weekday, weekend_night]


def test_day_type_must_match(add, retrieve, sub):
    weekday = add("晴空塔", "平日", "10", "1")
    weekend = add("晴空塔", "假日", "10", "1")
    assert ids(retrieve(sub(day_type="平日"))) == [weekday]


def test_empty_space_does_not_limit_place(add, retrieve, sub):
    a = add("晴空塔", "平日", "10", "1")
    b = add("淺草寺", "平日", "10", "1")
    assert sorted(ids(retrieve(sub(space=None, month="1")))) == [a, b]


def test_space_matches_exact_place_name_only(add, retrieve, sub):
    tower = add("晴空塔", "平日", "10", "1")
    town = add("晴空塔城", "平日", "10", "1")
    assert ids(retrieve(sub(month="1"))) == [tower]


def test_semantic_relative_threshold_drops_off_topic_content(add, retrieve, sub):
    fuji = add("晴空塔", "平日", "10", "1", content="早上看得到富士山")
    ramen = add("晴空塔", "平日", "10", "1", content="附近的拉麵店")

    assert ids(retrieve(sub(aspect="富士山", month="1"))) == [fuji]


def test_aspect_falls_back_to_question(add, retrieve, sub):
    fuji = add("晴空塔", "平日", "10", "1", content="早上看得到富士山")
    ramen = add("晴空塔", "平日", "10", "1", content="附近的拉麵店")

    assert ids(retrieve(sub(aspect=None), question="看得到富士山嗎")) == [fuji]


def test_better_time_match_ranks_first_and_evidence_carries_scores(add, retrieve, sub):
    exact = add("晴空塔", "平日", "10", "1")
    vague = add("晴空塔", "平日", "10", "冬", article="a2")  # 三分之一落在一月

    unsmoothed = Params(month_bandwidth=0, hour_bandwidth=0)
    [section] = retrieve(sub(month="1"), question="排隊", params=unsmoothed)
    first, second = section.evidence

    assert (first.content_id, second.content_id) == (exact, vague)
    assert first.overlap == pytest.approx(1.0)
    assert second.overlap == pytest.approx(1 / 3)
    assert first.semantic == pytest.approx(second.semantic)
    assert second.article_id == "a2"
    assert not first.backoff


def test_no_candidates_returns_empty(add, retrieve, sub):
    add("晴空塔", "平日", "10", "5")
    assert ids(retrieve(sub(month="1"))) == []


def test_embedding_cache_skips_repeated_texts(conn, embedder):
    cached = CachedEmbedder(embedder, conn)

    first = cached.embed(["富士山", "排隊"])
    second = cached.embed(["排隊", "富士山", "富士山"])

    assert len(embedder.calls) == 1
    assert second == [first[1], first[0], first[0]]


def test_embedding_cache_is_keyed_by_model(conn, embedder):
    CachedEmbedder(embedder, conn).embed(["富士山"])
    embedder.model = "other-model"
    CachedEmbedder(embedder, conn).embed(["富士山"])
    assert len(embedder.calls) == 2
