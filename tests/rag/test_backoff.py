"""檢索 seam：時間退讓、空間退讓、兩種都退完還是沒有的空結果。不打外部 API。"""
import pytest

from strag_v3.place import AREA, SPOT
from strag_v3.rag.params import Params


@pytest.fixture
def result(retrieve, sub):
    """只有一個子查詢的計畫：回傳那個子查詢的結果。"""
    def result(space="晴空塔", params=Params(), kind=SPOT, **time):
        [section] = retrieve(sub(space=space, kind=kind, **time), params=params)
        [r] = section.results
        return r
    return result


def ids(r):
    return sorted(e.content_id for e in r.evidence)


def test_time_backoff_takes_neighbouring_months_and_slots_and_marks_them(add, result):
    nov_noon = add(month="11", time="中午")
    jan_night = add(month="1", time="晚上")
    jan_morning = add(month="1", time="早上")
    oct_morning = add(month="10", time="早上")     # 隔兩個月
    jan_afternoon = add(month="1", time="下午")    # 隔兩個時段
    weekend = add(month="12", time="早上", day_type="假日")  # 平日／假日不擴

    r = result(month="12", time="早上", day_type="平日")

    assert ids(r) == [nov_noon, jan_night, jan_morning]
    assert all(e.time_backoff and not e.space_backoff for e in r.evidence)


def test_time_backoff_wraps_around_the_year_and_the_day(add, result):
    jan = add(month="1", time="早上")
    nov_night = add(month="11", time="晚上")

    assert ids(result(month="12", time="早上")) == [jan, nov_night]


def test_no_time_backoff_when_the_asked_time_has_evidence(add, result):
    dec = add(month="12")
    jan = add(month="1")

    r = result(month="12")

    assert ids(r) == [dec]
    assert not any(e.time_backoff for e in r.evidence)


def test_time_backoff_can_be_switched_off(add, result):
    add(month="1")
    add(month="11", time="中午")

    assert result(month="12", time="早上", params=Params(time_backoff=False, space_backoff=False)).evidence == []


def test_space_backoff_only_after_time_backoff_finds_nothing(add, result):
    tower_jan = add("晴空塔", month="1")
    town_dec = add("晴空塔城", month="12")  # 同一個行政區（押上一丁目）的另一個景點

    r = result(space="晴空塔", month="12")

    assert ids(r) == [tower_jan]  # 時間退讓先找到一月，不退到外圍行政區
    assert all(e.time_backoff and not e.space_backoff for e in r.evidence)


def test_space_backoff_goes_to_the_outer_admin_area_with_the_original_time(add, result):
    tower_may = add("晴空塔", month="5")
    town_dec = add("晴空塔城", month="12")
    area_dec = add("押上一丁目", month="12", kind=AREA)  # 外圍行政區本身的片段
    town_jan = add("晴空塔城", month="1")    # 時間退讓的月份，空間退讓時不用
    river_dec = add("北十間川", month="12")  # 押上二丁目，在外圍行政區之外
    oshiage_dec = add("押上", month="12", kind=AREA)  # 再外一層，只退一層

    r = result(space="晴空塔", month="12")

    assert ids(r) == [town_dec, area_dec]
    assert all(e.space_backoff and not e.time_backoff for e in r.evidence)
    assert {e.backoff_area for e in r.evidence} == {"押上一丁目"}


def test_area_backs_off_to_the_admin_area_one_level_up(add, result):
    river = add("北十間川", month="12")       # 押上二丁目，在押上裡
    flower = add("向島百花園", month="12")    # 向島，在墨田区裡、押上外
    asakusa = add("淺草寺", month="12")       # 台東区

    r = result(space="押上一丁目", kind=AREA, month="12")

    assert ids(r) == [river]
    assert r.evidence[0].backoff_area == "押上"


def test_space_backoff_runs_when_the_place_has_no_content_at_all(add, result):
    town = add("晴空塔城", month="12")

    r = result(space="晴空塔", month="12")

    assert ids(r) == [town]
    assert r.evidence[0].space_backoff


def test_space_backoff_can_be_switched_off_on_its_own(add, result):
    tower_jan = add("晴空塔", month="1")
    town_jul = add("晴空塔城", month="7")
    off = Params(space_backoff=False)

    assert ids(result(month="12", params=off)) == [tower_jan]  # 時間退讓照做
    assert result(month="7", params=off).evidence == []
    assert ids(result(month="7")) == [town_jul]


def test_empty_result_lists_the_places_slots_and_months_with_counts(add, result):
    add("晴空塔", month="5", time="早上")
    add("晴空塔", month="5", time="晚上", article="a2")
    add("晴空塔", month="夏", time="早上", article="a3")
    add("晴空塔", month="不明", time="不明", day_type="假日")  # 假日，問平日時過濾掉，但仍算有資料
    add("晴空塔城", month="8")  # 空間退讓查過的地點，不列進有資料的時段

    r = result(month="1", day_type="平日")

    assert r.evidence == []
    assert r.available.time == (("早上", 2), ("晚上", 1), ("不明", 1))
    assert r.available.month == (("5", 2), ("夏", 1), ("不明", 1))


def test_empty_result_for_an_area_counts_the_places_inside(add, result):
    add("晴空塔", month="5")
    add("北十間川", month="7", time="下午")
    add("押上", month="8", time="晚上", kind=AREA)
    add("向島百花園", month="9")  # 押上外

    r = result(space="押上", kind=AREA, month="1")

    assert r.available.time == (("早上", 1), ("下午", 1), ("晚上", 1))
    assert r.available.month == (("5", 1), ("7", 1), ("8", 1))


def test_place_that_does_not_resolve_returns_empty_without_backoff_or_available_times(add, result):
    add("晴空塔")
    add("晴空塔城")

    r = result(space="晴空塔展望台")

    assert r.evidence == []
    assert r.available.time == () and r.available.month == ()
    assert r.place_unresolved


def test_resolved_place_without_evidence_is_not_marked_unresolved(add, result):
    add("晴空塔", month="5")

    r = result(month="1", params=Params(time_backoff=False, space_backoff=False))

    assert r.evidence == [] and not r.place_unresolved


def test_no_space_backoff_when_the_place_itself_has_evidence(add, result):
    tower = add("晴空塔", month="12")
    town = add("晴空塔城", month="12")

    r = result(month="12")

    assert ids(r) == [tower]
    assert not any(e.space_backoff for e in r.evidence)
