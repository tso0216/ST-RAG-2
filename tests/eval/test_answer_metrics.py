"""評估 seam：題目檔加上手寫的評審結果，看 `expect` 覆蓋率和時間誤植率的每題紀錄和彙總。不呼叫評審。"""
import json

import pytest

from strag_v3.eval.full.answer import Claim, ExpectCheck, Judgement
from strag_v3.eval.metrics import Outcome, evaluate
from strag_v3.eval.questions import load_questions

WHEN = {"month": ["12"]}


@pytest.fixture
def questions(tmp_path):
    def questions(*qs):
        path = tmp_path / "spot_questions.json"
        path.write_text(json.dumps({"questions": list(qs)}, ensure_ascii=False))
        return load_questions(path)
    return questions


def q(id, expect=("重點",), when=WHEN, **extra) -> dict:
    d = {"id": id, "question": f"問題 {id}", "expect": list(expect), **extra}
    if when is not None:
        d["when"] = when
    return d


def checks(*covered) -> tuple[ExpectCheck, ...]:
    return tuple(ExpectCheck(f"重點 {i}", c, f"理由 {i}") for i, c in enumerate(covered))


def claims(*misattributed) -> tuple[Claim, ...]:
    return tuple(Claim(f"說法 {i}", (i,), m, f"理由 {i}") for i, m in enumerate(misattributed))


def answered(*keys) -> dict[str, Outcome]:
    return {k: Outcome(answer="答案") for k in keys}


@pytest.fixture
def two(questions):
    qs = questions(q("q1", ["a", "b", "c", "d"], type="停留", split="dev"),
                   q("q2", ["a", "b"], type="找時間", split="test"))
    judgements = {
        "spot/q1": Judgement(checks(True, True, False, True), claims(False, True, False)),
        "spot/q2": Judgement(checks(False, True), claims(False)),
    }
    return evaluate(qs, answered("spot/q1", "spot/q2"), judgements=judgements)


def test_expect_coverage_per_question_and_macro_average(two):
    per = {r["key"]: r["judge"] for r in two["questions"]}

    assert per["spot/q1"]["expect_coverage"] == pytest.approx(3 / 4)
    assert per["spot/q2"]["expect_coverage"] == pytest.approx(1 / 2)
    assert two["summary"]["overall"]["answer"]["expect_coverage"] == pytest.approx((3 / 4 + 1 / 2) / 2)


def test_misattribution_rate_is_pooled_over_time_claims(two):
    per = {r["key"]: r["judge"] for r in two["questions"]}

    assert per["spot/q1"]["misattributed"] == 1 and per["spot/q1"]["claims_n"] == 3
    # 所有題目的誤植說法數 ÷ 講到時間的說法數
    assert two["summary"]["overall"]["answer"]["misattribution_rate"] == pytest.approx(1 / 4)


def test_answer_metrics_are_grouped_by_type_and_split(two):
    s = two["summary"]

    assert s["by_type"]["停留"]["answer"]["expect_coverage"] == pytest.approx(3 / 4)
    assert s["by_split"]["test"]["answer"]["misattribution_rate"] == 0
    assert s["by_split"]["test"]["answer"]["n"] == 1


def test_judge_reasons_are_kept_per_item(two):
    rec = two["questions"][0]["judge"]

    assert rec["expect"][2] == {"point": "重點 2", "covered": False, "reason": "理由 2"}
    assert rec["claims"][1] == {"claim": "說法 1", "content_ids": [1], "misattributed": True, "reason": "理由 1"}


def test_question_without_when_is_left_out_of_misattribution(questions):
    qs = questions(q("q1", when=None), q("q2"))
    out = evaluate(qs, answered("spot/q1", "spot/q2"), judgements={
        "spot/q1": Judgement(checks(True), None),
        "spot/q2": Judgement(checks(False), claims(True, False)),
    })
    overall = out["summary"]["overall"]["answer"]

    assert out["questions"][0]["judge"]["misattributed"] is None
    assert overall["misattribution_rate"] == pytest.approx(1 / 2)
    assert overall["expect_coverage"] == pytest.approx(1 / 2)


def test_answer_without_time_claims_has_no_rate(questions):
    out = evaluate(questions(q("q1")), answered("spot/q1"),
                   judgements={"spot/q1": Judgement(checks(True), ())})

    assert out["summary"]["overall"]["answer"]["misattribution_rate"] is None


def test_question_without_expect_is_left_out_of_coverage(questions):
    qs = questions(q("q1", expect=()), q("q2", ["a"]))
    out = evaluate(qs, answered("spot/q1", "spot/q2"), judgements={
        "spot/q1": Judgement((), ()),
        "spot/q2": Judgement(checks(True), ()),
    })

    assert out["questions"][0]["judge"]["expect_coverage"] is None
    assert out["summary"]["overall"]["answer"]["expect_coverage"] == 1


def test_without_judgements_answer_metrics_are_empty(questions):
    out = evaluate(questions(q("q1")), answered("spot/q1"))

    assert out["questions"][0]["judge"] is None
    assert out["summary"]["overall"]["answer"] == {"n": 0, "expect_coverage": None, "misattribution_rate": None,
                                                   "claims_n": 0, "misattributed": 0}
