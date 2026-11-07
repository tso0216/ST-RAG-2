"""檢索 seam：週期平滑和「不明」折扣。輸入檢索計畫，看取回哪些片段、怎麼排序。不打外部 API。"""
import pytest

from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan
from strag_v3.rag.retrieve import Retriever


class FlatEmbedder:
    """假的 embedding：每段文字都一樣，語意分數全部相同，排序只看時間。"""

    model = "fake-flat"

    def embed(self, texts):
        return [[1.0, 0.1] for _ in texts]


def add(conn, day_type, time, month, place="晴空塔", article="a1"):
    pid = conn.execute("SELECT id FROM place WHERE name = ?", (place,)).fetchone()
    pid = pid[0] if pid else conn.execute("INSERT INTO place (name) VALUES (?)", (place,)).lastrowid
    return conn.execute(
        "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)", (article, pid, place, day_type, time, month, "排隊狀況")).lastrowid


def evidence(conn, params=Params(), **time):
    plan = Plan.from_dict({"sub_queries": [{"space": "晴空塔", "time": time, "aspect": "排隊"}]})
    [result] = Retriever(conn, FlatEmbedder(), params).retrieve(plan, "排隊要多久")
    return result.evidence


def ids(conn, params=Params(), **time):
    return [e.content_id for e in evidence(conn, params, **time)]


def test_december_query_takes_january_but_ranks_it_after_december(conn):
    jan = add(conn, "平日", "10", "1")
    dec = add(conn, "平日", "10", "12")

    assert ids(conn, month="12") == [dec, jan]


def test_zero_bandwidth_drops_january_from_december_query(conn):
    jan = add(conn, "平日", "10", "1")
    dec = add(conn, "平日", "10", "12")

    assert ids(conn, Params(month_bandwidth=0), month="12") == [dec]


def test_23_oclock_query_takes_midnight_after_23(conn):
    midnight = add(conn, "假日", "0", "8")
    at23 = add(conn, "假日", "23", "8")
    noon = add(conn, "假日", "12", "8")

    assert ids(conn, time="23") == [at23, midnight]


def test_zero_hour_bandwidth_drops_midnight_from_23_oclock_query(conn):
    midnight = add(conn, "假日", "0", "8")
    at23 = add(conn, "假日", "23", "8")

    assert ids(conn, Params(hour_bandwidth=0), time="23") == [at23]


def test_new_years_eve_query_takes_new_years_day_just_after_midnight(conn):
    new_year = add(conn, "假日", "0", "1")
    assert ids(conn, month="12", time="23") == [new_year]


def test_content_with_any_unknown_dimension_ranks_after_explicit_match(conn):
    # 問題只限月份，所以平日／假日、時段不明的片段，時空重疊度跟明確的片段一樣
    unknown_day = add(conn, "不明", "10", "1")
    unknown_time = add(conn, "平日", "不明", "1")
    explicit = add(conn, "平日", "10", "1")

    got = ids(conn, month="1")

    assert got[0] == explicit
    assert sorted(got[1:]) == [unknown_day, unknown_time]


def test_unknown_discount_is_tunable(conn):
    unknown = add(conn, "不明", "10", "1")
    explicit = add(conn, "平日", "10", "1")

    by_id = {e.content_id: e for e in evidence(conn, Params(unknown_discount=0.5), month="1")}

    assert by_id[unknown].score == pytest.approx(by_id[explicit].score * 0.5)
    assert ids(conn, Params(unknown_discount=1.0), month="1") == [unknown, explicit]  # 不折扣就同分，依 id 排
