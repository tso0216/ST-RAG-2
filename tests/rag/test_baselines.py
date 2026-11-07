"""兩個 baseline 和 oracle 模式：透過評估的 Runner 切換設定，規劃器換成固定的計畫。不打外部 API。"""
import asyncio

import pytest

from strag_v3.eval.questions import Question
from strag_v3.eval.runner import Config, Runner
from strag_v3.rag.plan import Plan, parse_time


def question(when=None, text="排隊要多久") -> Question:
    return Question(key="t/q1", question=text, when=parse_time(when), relevant=frozenset())


@pytest.fixture
def run(conn, embedder, nominatim, sub):
    """用一個設定跑一題，回傳取回的片段 id（依證據的順序）。規劃器固定回傳 sub_queries 組成的計畫。"""
    def run(config: Config, q: Question, *sub_queries) -> list[int]:
        async def planner(_):
            return Plan.from_dict({"sub_queries": list(sub_queries) or [sub()], "group_by": [], "compose": "merge"})

        runner = Runner(conn, embedder, config, nominatim, planner=planner)
        out = asyncio.run(runner.run(q))
        return [e.content_id for e in out.evidence]
    return run


def test_dense_takes_top_k_by_semantic_score_ignoring_time_and_place(add, run):
    plain = add(content="甲板很冷")
    fuji = add(month="8", time="晚上", content="富士山很清楚")
    elsewhere = add(place="淺草寺", content="富士山跟排隊")

    assert run(Config(system="dense", k=2, answer=False), question(text="看得到富士山嗎")) == [fuji, elsewhere]


def test_hard_filter_turns_both_backoffs_off(add, run, sub):
    nov = add(month="11")
    oshiage = add(place="北十間川", month="12")
    plan = sub(month="12")

    assert run(Config(answer=False), question(), plan) == [nov]
    assert run(Config(system="hard", answer=False), question(), plan) == []


def test_oracle_replaces_planned_time_with_the_question_when(add, run, sub):
    dec = add(month="12")
    aug = add(month="8")
    wrong = sub(month="8")
    when = {"month": ["12"]}

    assert run(Config(answer=False), question(when), wrong) == [aug]
    assert run(Config(oracle=True, answer=False), question(when), wrong) == [dec]
    assert run(Config(system="hard", oracle=True, answer=False), question(when), wrong) == [dec]


def test_oracle_without_when_leaves_time_unlimited(add, run, sub):
    rows = [add(month="12"), add(month="8")]

    assert sorted(run(Config(oracle=True, answer=False), question(), sub(month="8"))) == rows


def test_dense_cannot_be_combined_with_oracle():
    with pytest.raises(ValueError):
        Config(system="dense", oracle=True)
