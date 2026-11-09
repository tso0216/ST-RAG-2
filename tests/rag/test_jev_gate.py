"""檢索 seam：gate=jev（預設）時，時間硬過濾後的每個候選片段交給 JEV 判斷相關。假 TypeSafe client，不打外部 API。"""
import sqlite3

from strag_v3.rag.params import Params
from strag_v3.rag.relevance import CACHE_SCHEMA


def ids(sections):
    return [e.content_id for s in sections for e in s.evidence]


def test_every_passage_judged_relevant_passes_without_a_cap(add, retrieve, sub, typesafe):
    rows = [add(content=f"排隊狀況 {i}") for i in range(12)]
    ramen = add(content="附近的拉麵店")
    typesafe.nouls = {"排隊狀況 0": 0.5, "排隊狀況 1": 0.49}

    got = ids(retrieve(sub(month="1")))

    assert sorted(got) == [rows[0], *rows[2:]]
    assert ramen not in got and rows[1] not in got


def test_ranked_by_noul_with_unknown_time_discounted_for_ordering_only(add, retrieve, sub, typesafe):
    unknown_high = add(time="不明", content="排隊 A")
    explicit_mid = add(time="早上", content="排隊 B")
    explicit_low = add(time="早上", content="排隊 C")
    unknown_low = add(time="不明", content="排隊 D")
    typesafe.nouls = {"排隊 A": 0.9, "排隊 B": 0.8, "排隊 C": 0.6, "排隊 D": 0.55}

    sections = retrieve(sub(month="1"))
    got = {e.content_id: e for e in sections[0].evidence}

    # 0.9×0.8=0.72 排在 0.8 之後；0.55×0.8=0.44 雖然低於 jev_pass 還是通過
    assert ids(sections) == [explicit_mid, unknown_high, explicit_low, unknown_low]
    assert got[unknown_high].relevance == 0.9 and got[unknown_high].time_unknown
    assert abs(got[unknown_high].score - 0.72) < 1e-9


def test_state_has_question_aspect_and_passage_but_no_time_labels(add, retrieve, sub, typesafe):
    add(content="排隊狀況", month="1", time="早上", day_type="平日")

    retrieve(sub(aspect="排隊", month="1"), question="平日早上排隊要多久")
    retrieve(sub(aspect=None, month="1"), question="排隊要多久")

    with_aspect, without_aspect = (c["state"] for c in typesafe.calls)
    assert with_aspect == {"question": "平日早上排隊要多久", "aspect": "排隊", "passage": "排隊狀況"}
    assert without_aspect == {"question": "排隊要多久", "passage": "排隊狀況"}
    assert {c["model"] for c in typesafe.calls} == {"jev-1.14.0"}


def test_one_request_per_candidate_passage(add, retrieve, sub, typesafe):
    add(content="排隊 A")
    add(content="排隊 B")
    add(content="排隊 C", month="7")  # 時間硬過濾掉，不問

    retrieve(sub(month="1"))

    assert sorted(c["state"]["passage"] for c in typesafe.calls) == ["排隊 A", "排隊 B"]


def test_cached_judgement_is_reused_without_calling_jev(add, retrieve, sub, typesafe):
    row = add(content="排隊狀況")
    first = ids(retrieve(sub(month="1")))
    calls = len(typesafe.calls)
    typesafe.nouls = {"排隊狀況": 0.1}  # 就算 JEV 這次會改判，也只讀快取

    again = ids(retrieve(sub(month="1")))

    assert len(typesafe.calls) == calls == 1
    assert again == first == [row]


def test_cache_is_keyed_by_model_question_and_aspect(add, retrieve, sub, typesafe):
    add(content="排隊狀況")
    retrieve(sub(month="1"))
    retrieve(sub(month="1"), params=Params(jev_model="jev-other"))
    retrieve(sub(month="1"), question="排隊會很久嗎")
    retrieve(sub(aspect="排隊人潮", month="1"))
    retrieve(sub(aspect=None, month="1"))

    assert len(typesafe.calls) == 5


def test_nothing_relevant_counts_as_no_evidence_and_backs_off_in_time(add, retrieve, sub):
    add(content="附近的拉麵", month="12")
    nov = add(content="排隊很久", month="11")

    [s] = retrieve(sub(month="12"))

    assert ids([s]) == [nov]
    assert s.evidence[0].time_backoff and not s.evidence[0].space_backoff


def test_then_backs_off_in_space_with_new_candidates_judged_by_jev(add, retrieve, sub, typesafe):
    add(content="附近的拉麵", month="12")
    add(content="拉麵也不錯", month="11")
    town = add("晴空塔城", content="排隊很久", month="12")
    add("晴空塔城", content="拉麵很好吃", month="12")

    [s] = retrieve(sub(month="12"))

    assert ids([s]) == [town]
    assert s.evidence[0].space_backoff and s.evidence[0].backoff_area == "押上一丁目"
    assert "拉麵很好吃" in [c["state"]["passage"] for c in typesafe.calls]


def test_nothing_relevant_anywhere_returns_empty_with_available(add, retrieve, sub):
    add(content="附近的拉麵", month="12", time="早上")
    add(content="拉麵也不錯", month="11", time="早上")
    add("晴空塔城", content="拉麵很好吃", month="12")

    [s] = retrieve(sub(month="12"))
    [r] = s.results

    assert r.evidence == [] and not r.place_unresolved
    assert r.available.month == (("11", 1), ("12", 1))
    assert r.available.time == (("早上", 2),)


def test_main_db_script_creates_the_same_jev_cache_table(conn):
    fresh = sqlite3.connect(":memory:")
    fresh.execute(CACHE_SCHEMA)
    cols = "SELECT name, type, \"notnull\", pk FROM pragma_table_info('jev_cache')"
    assert conn.execute(cols).fetchall() == fresh.execute(cols).fetchall() != []
