"""評估 seam：題目檔的 `gold_plan` 加上手寫的系統計畫，看規劃器正確率的比對規則和彙總。

地點用假 Nominatim 解析（記憶體內 SQLite），不打外部 API。
"""
import json

import pytest

from strag_v3.eval.metrics import Outcome, evaluate
from strag_v3.eval.questions import QuestionError, load_questions
from strag_v3.place import AREA, SPOT, Places
from strag_v3.rag.plan import Plan
from tests.fake_nominatim import FakeNominatim


@pytest.fixture
def places(conn):
    return Places(conn, FakeNominatim())


def space(name="東京スカイツリー", kind=SPOT, city="東京"):
    return {"name": name, "name_ja": name, "city": city, "kind": kind}


def sq(space_=None, time=None, aspect="排隊"):
    return {"space": space_ if space_ is not None else space(), "time": time, "aspect": aspect}


def plan(*subs, group_by=(), compose="merge") -> dict:
    return {"sub_queries": list(subs) or [sq()], "group_by": list(group_by), "compose": compose}


@pytest.fixture
def run(tmp_path, places):
    """一題：gold_plan 和系統產生的計畫 → 這題的規劃器紀錄和整體彙總。"""
    def run(gold: dict | None, pred: dict | None, **extra):
        d = {"id": "q1", "question": "問題", **extra}
        if gold is not None:
            d["gold_plan"] = gold
        path = tmp_path / "spot_questions.json"
        path.write_text(json.dumps({"questions": [d]}, ensure_ascii=False))
        out = Outcome(plan=None if pred is None else Plan.from_dict(pred))
        result = evaluate(load_questions(path), {"spot/q1": out}, places)
        return result["questions"][0]["planner"], result["summary"]["overall"]["planner"]
    return run


def test_equivalent_month_labels_count_as_correct(run):
    rec, _ = run(plan(sq(time={"month": ["12"]})), plan(sq(time={"month": ["12-12"]})))
    assert rec["fields"]["month"] == [1, 1]
    assert rec["correct"] is True


def test_equivalent_time_labels_count_as_correct(run):
    rec, _ = run(plan(sq(time={"month": ["冬"], "time": ["全天"]})),
                 plan(sq(time={"month": ["12-2"]})))
    assert rec["fields"]["month"] == [1, 1]
    assert rec["fields"]["time"] == [1, 1]


def test_left_empty_versus_filled_is_wrong(run):
    rec, _ = run(plan(sq(time={"month": ["12"]}, aspect=None)),
                 plan(sq(time={"month": ["12"], "day_type": "平日"}, aspect="排隊")))
    assert rec["fields"]["day_type"] == [0, 1]
    assert rec["fields"]["aspect"] == [0, 1]
    assert rec["fields"]["month"] == [1, 1]
    assert rec["correct"] is False


def test_space_left_empty_versus_filled_is_wrong(run):
    rec, _ = run(plan({"space": None, "time": None, "aspect": "排隊"}), plan(sq()))
    assert rec["fields"]["space"] == [0, 1]


def test_different_names_resolving_to_the_same_osm_object_count_as_correct(run):
    rec, _ = run(plan(sq(space(name="東京スカイツリー"))), plan(sq(space(name="晴空塔", city=""))))
    assert rec["fields"]["space"] == [1, 1]


def test_different_osm_objects_are_wrong(run):
    rec, _ = run(plan(sq(space(name="東京スカイツリー"))), plan(sq(space(name="晴空塔城"))))
    assert rec["fields"]["space"] == [0, 1]


def test_different_kind_is_wrong(run):
    rec, _ = run(plan(sq(space(name="押上", kind=AREA))), plan(sq(space(name="押上", kind=SPOT))))
    assert rec["fields"]["space"] == [0, 1]


def test_unresolvable_place_is_wrong(run):
    rec, _ = run(plan(sq(space(name="どこにもない"))), plan(sq(space(name="どこにもない"))))
    assert rec["fields"]["space"] == [0, 1]


def test_group_by_and_compose(run):
    rec, _ = run(plan(sq(), sq(), group_by=["day_type", "time_of_day"], compose="contrast"),
                 plan(sq(), sq(), group_by=["time_of_day", "day_type"], compose="merge"))
    assert rec["fields"]["group_by"] == [1, 1]
    assert rec["fields"]["compose"] == [0, 1]


def test_sub_queries_pair_regardless_of_order(run):
    morning, evening = sq(time={"time": ["早上"]}), sq(time={"time": ["晚上"]})
    rec, _ = run(plan(morning, evening, compose="contrast"), plan(evening, morning, compose="contrast"))
    assert rec["correct"] is True


def test_missing_sub_query_makes_its_fields_wrong(run):
    morning, evening = sq(time={"time": ["早上"]}), sq(time={"time": ["晚上"]})
    rec, _ = run(plan(morning, evening), plan(evening))
    assert rec["fields"]["sub_queries"] == [0, 1]
    assert rec["fields"]["time"] == [1, 2]
    assert rec["fields"]["space"] == [1, 2]


def test_splitting_one_scope_into_several_aspects_counts_as_one_sub_query(run):
    t = {"month": ["1"], "day_type": "平日", "time": ["早上"]}
    rec, _ = run(plan(sq(time=t, aspect="富士山與排隊")),
                 plan(sq(time=t, aspect="富士山"), sq(space(name="晴空塔", city=""), time=t, aspect="排隊")))
    assert rec["fields"]["sub_queries"] == [1, 1]
    assert rec["fields"]["space"] == [1, 1]
    assert rec["correct"] is True


def test_merged_aspect_is_filled_if_any_part_is_filled(run):
    rec, _ = run(plan(sq(aspect="排隊")), plan(sq(aspect=None), sq(aspect="排隊")))
    assert rec["correct"] is True


def test_sub_queries_with_different_time_are_not_merged(run):
    rec, _ = run(plan(sq(time={"time": ["早上"]})), plan(sq(time={"time": ["早上"]}), sq(time={"time": ["晚上"]})))
    assert rec["fields"]["sub_queries"] == [0, 1]
    assert rec["correct"] is False


def test_unreadable_plan_makes_every_field_wrong(run):
    rec, overall = run(plan(sq()), None)
    assert rec["correct"] is False
    assert all(ok == 0 for ok, _ in rec["fields"].values())
    assert overall["accuracy"] == 0


def test_question_without_gold_plan_is_skipped(run):
    rec, overall = run(None, plan(sq()))
    assert rec is None
    assert overall["n"] == 0 and overall["accuracy"] is None and overall["space"] is None


def test_overall_and_per_field_accuracy_grouped_by_type(tmp_path, places):
    right, wrong = plan(sq(time={"month": ["12"]})), plan(sq(time={"month": ["11"]}))
    path = tmp_path / "spot_questions.json"
    path.write_text(json.dumps({"questions": [
        {"id": "q1", "question": "a", "type": "停留", "gold_plan": right},
        {"id": "q2", "question": "b", "type": "停留", "gold_plan": right},
        {"id": "q3", "question": "c", "type": "比較", "gold_plan": right},
        {"id": "q4", "question": "d", "type": "比較"},
    ]}, ensure_ascii=False))
    plans = {"spot/q1": right, "spot/q2": wrong, "spot/q3": right, "spot/q4": right}
    summary = evaluate(load_questions(path), {k: Outcome(plan=Plan.from_dict(v)) for k, v in plans.items()},
                       places)["summary"]

    overall = summary["overall"]["planner"]
    assert (overall["n"], overall["accuracy"]) == (3, pytest.approx(2 / 3))
    assert overall["month"] == pytest.approx(2 / 3)
    assert overall["space"] == 1
    assert summary["by_type"]["停留"]["planner"]["accuracy"] == 0.5
    assert summary["by_type"]["比較"]["planner"]["n"] == 1
    assert summary["by_type"]["比較"]["planner"]["accuracy"] == 1


def test_unreadable_gold_plan_is_a_question_error(tmp_path):
    path = tmp_path / "spot_questions.json"
    path.write_text(json.dumps({"questions": [
        {"id": "q1", "question": "a", "gold_plan": {"sub_queries": []}}]}, ensure_ascii=False))
    with pytest.raises(QuestionError, match="spot/q1 的 gold_plan"):
        load_questions(path)
