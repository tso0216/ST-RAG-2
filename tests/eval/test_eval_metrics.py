"""評估 seam：題目檔加上手寫的系統輸出（固定的取回集合），看指標和分組彙總算得對不對。不跑系統、不打外部 API。"""
import json

import pytest

from strag_v3.eval.metrics import UNTAGGED, Outcome, evaluate
from strag_v3.eval.questions import QuestionError, load_questions
from strag_v3.place import AREA, SPOT
from strag_v3.rag.evidence import Evidence, Group, Section, SubQueryResult
from strag_v3.rag.plan import Space, SubQuery
from strag_v3.rag.timematch import TimeSpec


def ev(cid, month="12", day_type="平日", time="早上", **flags) -> Evidence:
    t = TimeSpec(month, day_type, time)
    return Evidence(cid, "a1", 1, "晴空塔", t, "內容", relevance=0.5, score=0.5, time_unknown=t.unknown, **flags)


def section(*evidence) -> Section:
    return Section([], [Group({}, list(evidence))] if evidence else [])


def outcome(*evidence) -> Outcome:
    return Outcome([section(*evidence)])


@pytest.fixture
def write(tmp_path):
    """寫一個題目檔，回傳路徑。"""
    def write(questions, name="spot_questions.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"place_name": "x", "questions": questions}, ensure_ascii=False))
        return path
    return write


def q(id, when=None, relevant=(), **extra) -> dict:
    d = {"id": id, "question": f"問題 {id}", "relevant_contents": list(relevant), **extra}
    if when is not None:
        d["when"] = when
    return d


DEC_WEEKDAY_MORNING = {"month": ["12"], "day_type": "平日", "time": ["早上"]}


@pytest.fixture
def three(write):
    """三題、兩種題型、兩個 split，和各自固定的取回集合。"""
    questions = load_questions(write([
        q("q1", DEC_WEEKDAY_MORNING, [1, 2, 3, 4], type="停留", split="dev"),
        q("q2", {"month": ["冬"]}, [5, 6], type="找時間", split="test"),
        q("q3", {"time": ["晚上"]}, [7], type="停留", split="test"),
    ]))
    outcomes = {
        "spot/q1": outcome(ev(1), ev(2),
                           ev(9, month="8"),                              # 時間不符、沒標退讓：違規
                           ev(10, month="11", time="中午", time_backoff=True),  # 時間退讓：不算違規
                           ev(11, month="不明")),                          # 月份不明：算相符
        "spot/q2": outcome(),
        "spot/q3": outcome(ev(7, time="晚上"), ev(8, time="早上")),          # 8 違規
    }
    return evaluate(questions, outcomes)


def test_set_recall_precision_and_f1_per_question(three):
    per = {r["key"]: r for r in three["questions"]}

    assert per["spot/q1"]["retrieved"] == [1, 2, 9, 10, 11]
    assert per["spot/q1"]["hits"] == [1, 2]
    assert per["spot/q1"]["recall"] == pytest.approx(2 / 4)
    assert per["spot/q1"]["precision"] == pytest.approx(2 / 5)
    assert per["spot/q1"]["f1"] == pytest.approx(2 * 0.5 * 0.4 / 0.9)
    assert (per["spot/q2"]["recall"], per["spot/q2"]["precision"], per["spot/q2"]["f1"]) == (0, 0, 0)
    assert (per["spot/q3"]["recall"], per["spot/q3"]["precision"]) == (1, 0.5)
    assert per["spot/q3"]["f1"] == pytest.approx(2 / 3)


def test_overall_set_metrics_are_macro_averages(three):
    overall = three["summary"]["overall"]

    assert overall["n"] == 3
    assert overall["recall"] == pytest.approx((0.5 + 0 + 1) / 3)
    assert overall["precision"] == pytest.approx((0.4 + 0 + 0.5) / 3)
    assert overall["f1"] == pytest.approx((0.8 / 1.8 + 0 + 2 / 3) / 3)


def test_time_violation_counts_mismatches_not_marked_as_backoff(three):
    per = {r["key"]: r for r in three["questions"]}

    assert per["spot/q1"]["violations"] == [9]
    assert per["spot/q2"]["violations"] == []
    assert per["spot/q3"]["violations"] == [8]
    # 違規片段數 ÷ 取回片段數，所有題目合起來算
    assert three["summary"]["overall"]["time_violation_rate"] == pytest.approx(2 / 7)


def test_space_backoff_is_not_a_violation_and_unknown_dimension_counts_as_matching(write):
    questions = load_questions(write([q("q1", DEC_WEEKDAY_MORNING, [1])]))
    out = evaluate(questions, {"spot/q1": outcome(
        ev(1, month="1", space_backoff=True, backoff_area="押上"),
        ev(2, day_type="不明", time="不明"),
        ev(3, day_type="假日", month="不明"),   # 月份不明，但平日／假日明確不符：違規
    )})

    assert out["questions"][0]["violations"] == [3]


def test_question_without_when_has_no_violations(write):
    questions = load_questions(write([q("q1", None, [1])]))
    out = evaluate(questions, {"spot/q1": outcome(ev(1, month="8", time="晚上"))})

    assert out["questions"][0]["violations"] == []
    assert out["summary"]["overall"]["time_violation_rate"] == 0


def test_answered_rate_is_the_share_of_questions_with_any_evidence(three):
    assert three["summary"]["overall"]["answered_rate"] == pytest.approx(2 / 3)
    assert [r["answered"] for r in three["questions"]] == [True, False, True]


def test_summary_is_grouped_by_split_and_type(three):
    by_split, by_type = three["summary"]["by_split"], three["summary"]["by_type"]

    assert list(by_split) == ["dev", "test"]
    assert by_split["dev"]["n"] == 1
    assert by_split["dev"]["recall"] == pytest.approx(0.5)
    assert by_split["dev"]["time_violation_rate"] == pytest.approx(1 / 5)
    assert by_split["test"]["n"] == 2
    assert by_split["test"]["recall"] == pytest.approx(0.5)
    assert by_split["test"]["precision"] == pytest.approx(0.25)
    assert by_split["test"]["f1"] == pytest.approx(1 / 3)
    assert by_split["test"]["time_violation_rate"] == pytest.approx(1 / 2)
    assert by_split["test"]["answered_rate"] == pytest.approx(0.5)

    assert set(by_type) == {"停留", "找時間"}
    assert by_type["停留"]["n"] == 2
    assert by_type["停留"]["recall"] == pytest.approx(0.75)
    assert by_type["停留"]["precision"] == pytest.approx(0.45)
    assert by_type["停留"]["time_violation_rate"] == pytest.approx(2 / 7)
    assert by_type["停留"]["answered_rate"] == 1
    assert by_type["找時間"]["f1"] == 0
    assert by_type["找時間"]["time_violation_rate"] is None   # 一筆都沒取回，不算
    assert by_type["找時間"]["answered_rate"] == 0


def test_old_question_file_without_type_and_split_is_grouped_as_untagged(write):
    questions = load_questions(write([q("q1", DEC_WEEKDAY_MORNING, [1]), q("q2", DEC_WEEKDAY_MORNING, [2])]))
    out = evaluate(questions, {"spot/q1": outcome(ev(1)), "spot/q2": outcome(ev(3))})

    assert list(out["summary"]["by_split"]) == [UNTAGGED]
    assert list(out["summary"]["by_type"]) == [UNTAGGED]
    assert out["summary"]["by_split"][UNTAGGED]["recall"] == pytest.approx(0.5)


def test_same_content_in_two_sections_counts_once_and_violates_if_any_copy_is_unmarked(write):
    questions = load_questions(write([q("q1", DEC_WEEKDAY_MORNING, [1])]))
    contrast = Outcome([section(ev(1), ev(5, month="11", time_backoff=True)),
                        section(ev(5, month="11"))])

    [rec] = evaluate(questions, {"spot/q1": contrast})["questions"]

    assert rec["retrieved"] == [1, 5]
    assert rec["precision"] == pytest.approx(0.5)
    assert rec["violations"] == [5]


def test_question_without_relevant_contents_is_left_out_of_set_metrics(write):
    unlabelled = q("q2", DEC_WEEKDAY_MORNING)
    del unlabelled["relevant_contents"]
    questions = load_questions(write([q("q1", DEC_WEEKDAY_MORNING, [1]), unlabelled]))

    out = evaluate(questions, {"spot/q1": outcome(ev(1)), "spot/q2": outcome(ev(2, month="8"))})

    assert out["questions"][1]["recall"] is None
    overall = out["summary"]["overall"]
    assert (overall["n"], overall["labelled"]) == (2, 1)
    assert overall["recall"] == 1
    assert overall["time_violation_rate"] == pytest.approx(1 / 2)


def test_empty_retrieval_is_perfect_when_nothing_is_relevant(write):
    questions = load_questions(write([q("q1", DEC_WEEKDAY_MORNING, []), q("q2", DEC_WEEKDAY_MORNING, [])]))
    out = evaluate(questions, {"spot/q1": outcome(), "spot/q2": outcome(ev(1))})

    first, second = out["questions"]
    assert (first["recall"], first["precision"], first["f1"]) == (1, 1, 1)
    assert (second["recall"], second["precision"], second["f1"]) == (1, 0, 0)


def test_error_counts_as_nothing_retrieved(write):
    questions = load_questions(write([q("q1", DEC_WEEKDAY_MORNING, [1])]))
    out = evaluate(questions, {"spot/q1": Outcome(error="計畫看不懂")})

    assert out["questions"][0]["error"] == "計畫看不懂"
    assert out["summary"]["overall"]["errors"] == 1
    assert out["summary"]["overall"]["answered_rate"] == 0


def test_unresolved_places_are_listed_per_question_and_counted_in_the_summary(write):
    questions = load_questions(write([q("q1", None, [1]), q("q2", None, [1])]))
    ok = SubQuery(space=Space("晴空塔", "東京スカイツリー", "東京", SPOT))
    bad = SubQuery(space=Space("東山區", "東山区", "京都", AREA))
    out = evaluate(questions, {
        "spot/q1": Outcome([Section([SubQueryResult(ok, [ev(1)]), SubQueryResult(bad, [], place_unresolved=True)],
                                    [Group({}, [ev(1)])])]),
        "spot/q2": outcome(ev(1)),
    })

    first, second = out["questions"]
    assert first["unresolved_places"] == [{"name": "東山區", "name_ja": "東山区", "city": "京都", "kind": AREA}]
    assert second["unresolved_places"] == []
    assert out["summary"]["overall"]["unresolved"] == 1


def test_folder_loads_every_question_file_with_keys_unique_across_files(write, tmp_path):
    write([q("q1", None, [1])], "a_questions.json")
    write([q("q1", None, [2])], "b_questions.json")

    assert [x.key for x in load_questions(tmp_path)] == ["a/q1", "b/q1"]


@pytest.mark.parametrize("bad", [{"split": "train"}, {"when": {"time": ["傍晚"]}}])
def test_bad_question_file_is_rejected(write, bad):
    with pytest.raises(QuestionError):
        load_questions(write([q("q1", None, [1]) | bad]))
