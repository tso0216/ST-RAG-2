"""檢索 seam：週期平滑和「不明」折扣。輸入檢索計畫，看取回哪些片段、怎麼排序。不打外部 API。

片段內容都一樣，語意分數全部相同，排序只看時間。
"""
import pytest

from strag_v3.rag.params import Params


@pytest.fixture
def evidence(retrieve, sub):
    def evidence(params=Params(), **time):
        [section] = retrieve(sub(**time), params=params)
        return section.evidence
    return evidence


@pytest.fixture
def ids(evidence):
    def ids(params=Params(), **time):
        return [e.content_id for e in evidence(params, **time)]
    return ids


def test_december_query_takes_january_but_ranks_it_after_december(add, ids):
    jan = add(day_type="平日", time="10", month="1")
    dec = add(day_type="平日", time="10", month="12")

    assert ids(month="12") == [dec, jan]


def test_zero_bandwidth_drops_january_from_december_query(add, ids):
    jan = add(day_type="平日", time="10", month="1")
    dec = add(day_type="平日", time="10", month="12")

    assert ids(Params(month_bandwidth=0), month="12") == [dec]


def test_23_oclock_query_takes_midnight_after_23(add, ids):
    midnight = add(day_type="假日", time="0", month="8")
    at23 = add(day_type="假日", time="23", month="8")
    noon = add(day_type="假日", time="12", month="8")

    assert ids(time="23") == [at23, midnight]


def test_zero_hour_bandwidth_drops_midnight_from_23_oclock_query(add, ids):
    midnight = add(day_type="假日", time="0", month="8")
    at23 = add(day_type="假日", time="23", month="8")

    assert ids(Params(hour_bandwidth=0), time="23") == [at23]


def test_new_years_eve_query_takes_new_years_day_just_after_midnight(add, ids):
    new_year = add(day_type="假日", time="0", month="1")
    assert ids(month="12", time="23") == [new_year]


def test_content_with_any_unknown_dimension_ranks_after_explicit_match(add, ids):
    # 問題只限月份，所以平日／假日、時段不明的片段，時空重疊度跟明確的片段一樣
    unknown_day = add(day_type="不明", time="10", month="1")
    unknown_time = add(day_type="平日", time="不明", month="1")
    explicit = add(day_type="平日", time="10", month="1")

    got = ids(month="1")

    assert got[0] == explicit
    assert sorted(got[1:]) == [unknown_day, unknown_time]


def test_unknown_discount_is_tunable(add, evidence, ids):
    unknown = add(day_type="不明", time="10", month="1")
    explicit = add(day_type="平日", time="10", month="1")

    by_id = {e.content_id: e for e in evidence(Params(unknown_discount=0.5), month="1")}

    assert by_id[unknown].score == pytest.approx(by_id[explicit].score * 0.5)
    assert ids(Params(unknown_discount=1.0), month="1") == [unknown, explicit]  # 不折扣就同分，依 id 排
