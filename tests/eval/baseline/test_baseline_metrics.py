"""指標 seam：題目、系統輸出、評審判斷進，每題分數和彙總出。手寫的資料，不讀 DB、不打外部 API。"""
import pytest

from strag_v3.eval.baseline.judge import Verdict
from strag_v3.eval.baseline.metrics import score_run, summarize
from strag_v3.eval.baseline.results import Cost, Outcome
from tests.eval.baseline.conftest import frag, question


def verdict(id, covered=(), unsupported=False) -> Verdict:
    return Verdict(id, coverage=[[0.9 if c else 0.1] for c in covered], unsupported=[0.9 if unsupported else 0.1])


def test_answer_metrics_average_per_question_coverage_and_count_unsupported_questions(fragments):
    qs = [question("q1", expect=("甲", "乙")), question("q2", expect=("丙", "丁", "戊", "己"))]
    outcomes = [Outcome("q1", answer="答"), Outcome("q2", answer="答")]
    verdicts = [verdict("q1", (True, False)), verdict("q2", (True, True, True, False), unsupported=True)]

    s = summarize(score_run(qs, outcomes, verdicts, fragments, "none"), "none")

    assert s.coverage == pytest.approx((0.5 + 0.75) / 2)
    assert s.unsupported == pytest.approx(0.5)
    # 沒有取回的系統，檢索指標留空
    assert s.article_recall is None and s.precision is None and s.violation_rate is None


def test_time_unknown_fragments_are_neither_hits_nor_misses(fragments):
    q = question("q1", relevant=(1, 2), excluded={3: "時間不明", 4: "無關"})
    # 取回 1（命中）、3（時間不明，拿掉）、4（誤撈）
    out = Outcome("q1", answer="答", contents=[1, 3, 4], articles=["a1", "a3", "a4"])

    [s] = score_run([q], [out], [verdict("q1", (True, True))], fragments, "fragment")

    assert s.retrieved == 2
    assert s.precision == pytest.approx(1 / 2)
    assert s.recall == pytest.approx(1 / 2)
    assert s.f1 == pytest.approx(1 / 2)
    assert s.article_recall == pytest.approx(1 / 2)


def test_time_violation_skips_unknown_labels_and_backoff_fragments():
    fragments = {1: frag(1, month="3"), 2: frag(2, month="5"), 3: frag(3, month="不明"), 4: frag(4, month="5")}
    q = question("q1", when={"month": ["3"]}, relevant=(1,))
    # 2 是五月，矛盾；3 月份不明，不算；4 是五月但 strag 標了退讓，不算
    out = Outcome("q1", answer="答", contents=[1, 2, 3, 4], backoff=[4])

    s = summarize(score_run([q], [out], [verdict("q1", (True, True))], fragments, "fragment"), "fragment")

    assert s.violation_rate == pytest.approx(1 / 4)


def test_compare_fragment_only_needs_to_match_one_option():
    fragments = {1: frag(1, time="早上"), 2: frag(2, time="下午"), 3: frag(3, time="晚上")}
    q = question("q1", type="比較", when={"month": ["3"]}, relevant=(1, 2), options=[
        {"label": "早上", "when": {"month": ["3"], "time": ["早上"]}, "relevant_contents": [1]},
        {"label": "下午", "when": {"month": ["3"], "time": ["下午"]}, "relevant_contents": [2]},
    ])
    out = Outcome("q1", answer="答", contents=[1, 2, 3])

    [s] = score_run([q], [out], [verdict("q1", (True, True))], fragments, "fragment")

    assert s.violations == 1


def test_violation_rate_pools_fragments_over_all_questions():
    fragments = {1: frag(1, month="3"), 2: frag(2, month="5"), 3: frag(3, month="3")}
    q1, q2 = question("q1", when={"month": ["3"]}), question("q2", when={"month": ["3"]})
    outs = [Outcome("q1", answer="答", contents=[2]), Outcome("q2", answer="答", contents=[1, 3, 1])]

    s = summarize(score_run([q1, q2], outs, [verdict("q1"), verdict("q2")], fragments, "fragment"), "fragment")

    # 每題平均是 (1 + 0) / 2；合起來算是 1 / 3（同一題重複的片段只算一次）
    assert s.violation_rate == pytest.approx(1 / 3)


def test_failed_place_unresolved_and_empty_questions_stay_in_the_denominator(fragments):
    qs = [question(f"q{i}", relevant=(1,), expect=("甲",)) for i in range(1, 5)]
    outs = [
        Outcome("q1", answer="答", contents=[1], articles=["a1"]),
        Outcome("q2", error="LLMError: 逾時"),
        Outcome("q3", answer="地點找不到", place_unresolved=True),
        Outcome("q4", answer="沒有符合的經驗"),
    ]
    verdicts = [verdict("q1", (True,)), Verdict("q2", skipped=True), verdict("q3", (False,)), verdict("q4", (False,))]

    s = summarize(score_run(qs, outs, verdicts, fragments, "fragment"), "fragment")

    assert s.n == 4
    assert s.coverage == pytest.approx(1 / 4)
    assert s.unsupported == 0
    assert s.recall == pytest.approx(1 / 4) and s.precision == pytest.approx(1 / 4)
    assert s.article_recall == pytest.approx(1 / 4)
    assert (s.errors, s.place_unresolved, s.empty) == (1, 1, 1)


def test_article_systems_get_article_recall_but_no_fragment_metrics(fragments):
    q = question("q1", relevant=(1, 2), articles=["a1", "a2"])
    out = Outcome("q1", answer="答", articles=["a2", "a9"])

    s = summarize(score_run([q], [out], [verdict("q1", (True, True))], fragments, "article"), "article")

    assert s.article_recall == pytest.approx(1 / 2)
    assert s.precision is None and s.recall is None and s.f1 is None and s.violation_rate is None


def test_confidence_interval_brackets_the_mean_and_is_reproducible(fragments):
    qs = [question(f"q{i}", expect=("甲",)) for i in range(20)]
    outs = [Outcome(q.id, answer="答") for q in qs]
    verdicts = [verdict(q.id, (i % 3 == 0,), unsupported=i % 4 == 0) for i, q in enumerate(qs)]

    a = summarize(score_run(qs, outs, verdicts, fragments, "none"), "none")
    b = summarize(score_run(qs, outs, verdicts, fragments, "none"), "none")

    lo, hi = a.coverage_ci
    assert lo < a.coverage < hi
    assert 0 <= lo and hi <= 1
    assert a.coverage_ci == b.coverage_ci and a.unsupported_ci == b.unsupported_ci


def test_cost_is_averaged_per_question(fragments):
    qs = [question("q1"), question("q2")]
    outs = [Outcome("q1", answer="答", cost=Cost(1000, 2, 30)), Outcome("q2", answer="答", cost=Cost(3000, 2, 10))]

    s = summarize(score_run(qs, outs, [verdict("q1"), verdict("q2")], fragments, "fragment"), "fragment")

    assert (s.input_tokens, s.llm_calls, s.jev_calls) == (2000, 2, 20)
