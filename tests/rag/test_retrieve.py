"""檢索 seam：時間硬過濾、語意門檻（gate=semantic）、「不明」折扣。輸入檢索計畫，看取回哪些片段、怎麼排序。不打外部 API。

時間過濾的測試走預設的 gate=jev（假 JEV）；gate=jev 本身的規則見 test_jev_gate.py。"""
import pytest

from strag_v3.rag.embedding import CachedEmbedder
from strag_v3.rag.params import Params
from strag_v3.rag.plan import PlanError
from strag_v3.rag.timematch import LabelError


def ids(sections):
    return [e.content_id for s in sections for e in s.evidence]


def evidence(sections):
    return {e.content_id: e for s in sections for e in s.evidence}


def test_december_query_takes_only_december(add, retrieve, sub):
    dec = add(month="12")
    jan = add(month="1")
    nov = add(month="11")

    assert ids(retrieve(sub(month="12"))) == [dec]


@pytest.mark.parametrize("month", ["12-2", "冬"])
def test_cross_year_range_and_winter_match_january(add, retrieve, sub, month):
    jan = add(month="1")
    may = add(month="5")

    assert ids(retrieve(sub(month=month))) == [jan]


@pytest.mark.parametrize("label", ["12-2", "冬"])
def test_january_query_matches_content_labelled_with_a_range_or_season(add, retrieve, sub, label):
    winter = add(month=label)
    summer = add(month="夏")

    assert ids(retrieve(sub(month="1"))) == [winter]


def test_query_with_a_set_of_months_takes_any_of_them(add, retrieve, sub):
    dec = add(month="12")
    jan = add(month="1")
    feb = add(month="2")

    assert sorted(ids(retrieve(sub(month=["12", "1"])))) == [dec, jan]


def test_afternoon_and_evening_query_takes_all_day_and_blocks_morning(add, retrieve, sub):
    afternoon = add(time="下午")
    evening = add(time="晚上")
    all_day = add(time="全天")
    morning = add(time="早上")
    noon = add(time="中午")

    assert sorted(ids(retrieve(sub(time=["下午", "晚上"])))) == [afternoon, evening, all_day]


def test_all_day_query_does_not_limit_time_of_day(add, retrieve, sub):
    rows = [add(time=t) for t in ("早上", "晚上", "全天")]
    assert sorted(ids(retrieve(sub(time="全天")))) == rows


def test_day_type_must_match(add, retrieve, sub):
    weekday = add(day_type="平日")
    weekend = add(day_type="假日")
    assert ids(retrieve(sub(day_type="平日"))) == [weekday]


def test_empty_time_does_not_limit_time(add, retrieve, sub):
    rows = [add(day_type=d, time=t, month=m) for d, t, m in
            [("平日", "早上", "1"), ("假日", "晚上", "8"), ("不明", "不明", "不明")]]
    assert sorted(ids(retrieve(sub()))) == rows


def test_omitted_time_dimension_does_not_limit_it(add, retrieve, sub):
    weekday = add(day_type="平日", time="早上", month="1")
    weekend_night = add(day_type="假日", time="晚上", month="1")
    other_month = add(day_type="平日", time="早上", month="6")

    assert sorted(ids(retrieve(sub(month="1")))) == [weekday, weekend_night]


@pytest.mark.parametrize("dim", ["month", "day_type", "time"])
def test_unknown_dimension_matches_but_is_marked_and_ranks_after_explicit_match(add, retrieve, sub, dim):
    explicit = add(day_type="平日", time="早上", month="1")
    unknown = add(**{"day_type": "平日", "time": "早上", "month": "1", dim: "不明"})
    other = add(day_type="假日", time="晚上", month="7")

    sections = retrieve(sub(day_type="平日", time="早上", month="1"))
    got = evidence(sections)

    assert ids(sections) == [explicit, unknown]
    assert got[unknown].time_unknown and not got[explicit].time_unknown


@pytest.mark.parametrize("gate", ["jev", "semantic"])
def test_unknown_discount_is_tunable(add, retrieve, sub, gate):
    unknown = add(time="不明")
    explicit = add(time="早上")

    got = evidence(retrieve(sub(month="1"), params=Params(gate=gate, unknown_discount=0.5)))

    assert got[unknown].score == pytest.approx(got[explicit].score * 0.5)
    assert got[unknown].relevance == pytest.approx(got[explicit].relevance)
    assert ids(retrieve(sub(month="1"), params=Params(gate=gate, unknown_discount=1.0))) == [unknown, explicit]  # 同分依 id 排


def test_evidence_matching_directly_carries_no_backoff_flags(add, retrieve, sub):
    row = add(month="1", article="a2")
    [e] = retrieve(sub(month="1"))[0].evidence
    assert (e.content_id, e.article_id) == (row, "a2")
    assert not (e.time_backoff or e.space_backoff or e.time_unknown)


def test_empty_space_does_not_limit_place(add, retrieve, sub):
    a = add("晴空塔")
    b = add("淺草寺")
    assert sorted(ids(retrieve(sub(space=None, month="1")))) == [a, b]


def test_space_matches_exact_place_name_only(add, retrieve, sub):
    tower = add("晴空塔")
    town = add("晴空塔城")
    assert ids(retrieve(sub(month="1"))) == [tower]


SEMANTIC = Params(gate="semantic")


def test_semantic_relative_threshold_drops_off_topic_content(add, retrieve, sub):
    fuji = add(content="早上看得到富士山")
    ramen = add(content="附近的拉麵店")

    assert ids(retrieve(sub(aspect="富士山", month="1"), params=SEMANTIC)) == [fuji]


def test_semantic_aspect_falls_back_to_question(add, retrieve, sub):
    fuji = add(content="早上看得到富士山")
    ramen = add(content="附近的拉麵店")

    assert ids(retrieve(sub(aspect=None), question="看得到富士山嗎", params=SEMANTIC)) == [fuji]


def test_semantic_threshold_is_relative_to_the_best_score_and_records_cosine(add, retrieve, sub, typesafe):
    # KeywordEmbedder：「排隊」對到 [0,1,0,0,0.1]；只含「排隊」的 cosine 1，含兩個關鍵字的 ≈0.70，都沒有的 ≈0.01
    queue = add(content="排隊")
    both = add(content="排隊和拉麵")
    ramen = add(content="拉麵")

    sections = retrieve(sub(month="1"), params=SEMANTIC)
    got = evidence(sections)

    assert ids(sections) == [queue, both]  # 0.01 低於 1 − 0.3
    assert got[queue].relevance == pytest.approx(1.0)
    assert got[both].relevance == pytest.approx(0.7, abs=0.01)
    assert ids(retrieve(sub(month="1"), params=Params(gate="semantic", delta=1.0))) == [queue, both, ramen]
    assert typesafe.calls == []  # semantic 不問 JEV


@pytest.mark.parametrize("time", [{"time": "16-17"}, {"time": "不明"}, {"month": "13"}, {"day_type": "週末"}])
def test_plan_rejects_time_labels_outside_the_format(retrieve, sub, time):
    with pytest.raises(PlanError):
        retrieve(sub(**time))


def test_old_hour_labels_in_db_are_rejected(add, retrieve, sub):
    add(time="16-17")
    with pytest.raises(LabelError):
        retrieve(sub(month="1"))


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
