"""評審 seam：題目、片段和系統輸出進，每題的判斷出。假 TypeSafe client，不打外部 API。"""
import asyncio

from service.jev import JEVClient

from strag_v3.eval.baseline.judge import Judge, agreement, disagreements
from strag_v3.eval.baseline.results import Outcome
from tests.eval.baseline.conftest import frag, question
from tests.fake_typesafe import ScriptedTypeSafe


def judge(questions, fragments, outcomes, typesafe, n=1):
    return asyncio.run(Judge(JEVClient(typesafe), n=n).judge(questions, fragments, outcomes))


def test_asks_coverage_once_per_expect_and_unsupported_once_per_answer(fragments):
    fragments[3] = frag(3, time="不明", text="時間不明的片段")
    q = question(relevant=(1, 2), excluded={3: "時間不明", 4: "無關"}, expect=("重點一", "重點二"))
    ts = ScriptedTypeSafe()

    judge([q], fragments, [Outcome("q1", answer="答案")], ts)

    states = [c["state"] for c in ts.calls]
    coverage = [s for s in states if "point" in s]
    unsupported = [s for s in states if "point" not in s]
    assert sorted(s["point"] for s in coverage) == ["重點一", "重點二"]
    assert all(s["question"] == "問題 q1" and s["answer"] == "答案" for s in coverage)
    assert len(unsupported) == 1
    u = unsupported[0]
    assert u["answer"] == "答案"
    assert [f["id"] for f in u["reference_fragments"]] == [1, 2]
    assert u["reference_fragments"][0]["text"] == "片段 1 的內容"
    assert u["reference_fragments"][0]["time"] == "3 月 平日 早上"
    # 只有時間不明的排除片段放進去，無關的不放
    assert [f["id"] for f in u["time_unknown_fragments"]["fragments"]] == [3]
    assert {c["model"] for c in ts.calls} == {"jev-1.14.0"}


def test_n_repeats_every_judgement_and_scores_only_the_first(fragments):
    q = question(expect=("重點一", "重點二"))

    def respond(state, attempt):
        if state.get("point") == "重點一":
            return [0.9, 0.2, 0.8][attempt - 1]   # 第 1 次涵蓋，之後不一致
        if "point" in state:
            return 0.1                             # 三次都沒涵蓋
        return [0.3, 0.3, 0.7][attempt - 1]        # 無支持：第 1 次「沒有」
    ts = ScriptedTypeSafe(respond)

    [v] = judge([q], fragments, [Outcome("q1", answer="答案")], ts, n=3)

    assert len(ts.calls) == 9
    assert v.coverage == [[0.9, 0.2, 0.8], [0.1, 0.1, 0.1]]
    assert v.unsupported == [0.3, 0.3, 0.7]
    assert v.covered == [True, False]
    assert v.has_unsupported is False


def test_disagreements_list_each_inconsistent_judgement_and_agreement_is_split(fragments):
    q1, q2 = question("q1", expect=("甲", "乙")), question("q2", expect=("丙",))

    def respond(state, attempt):
        if state.get("point") == "甲":
            return [0.9, 0.1][attempt - 1]
        if "point" not in state and state["question"] == "問題 q2":
            return [0.2, 0.6][attempt - 1]
        return 0.9
    verdicts = judge([q1, q2], fragments, [Outcome("q1", answer="答"), Outcome("q2", answer="答")],
                     ScriptedTypeSafe(respond), n=2)

    assert disagreements("dense_frag", verdicts) == [
        {"system": "dense_frag", "id": "q1", "item": "expect 1", "nouls": [0.9, 0.1]},
        {"system": "dense_frag", "id": "q2", "item": "無支持", "nouls": [0.2, 0.6]},
    ]
    # 覆蓋 3 條裡 2 條一致；無支持 2 題裡 1 題一致
    assert agreement(verdicts) == {"coverage": 2 / 3, "unsupported": 1 / 2}


def test_question_without_an_answer_is_not_sent_but_a_no_match_answer_is(fragments):
    ts = ScriptedTypeSafe()
    failed, empty = question("q1"), question("q2")

    verdicts = judge([failed, empty], fragments,
                     [Outcome("q1", error="LLMError: 逾時"), Outcome("q2", answer="沒有符合的經驗。")], ts)

    assert {c["state"]["question"] for c in ts.calls} == {"問題 q2"}
    assert verdicts[0].skipped and verdicts[0].covered == [] and verdicts[0].has_unsupported is False
    assert not verdicts[1].skipped
