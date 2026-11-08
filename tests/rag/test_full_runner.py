"""主系統評估的 Runner：規劃器換成固定的計畫，跑一題取回片段。不打外部 API。"""
import asyncio

from strag_v3.eval.full.runner import Config, Runner
from strag_v3.eval.questions import Question
from strag_v3.rag.plan import Plan, PlanError


def question() -> Question:
    return Question(key="t/q1", question="排隊要多久", when=None, relevant=frozenset())


def run(conn, embedder, nominatim, planner):
    return asyncio.run(Runner(conn, embedder, Config(answer=False), nominatim, planner=planner).run(question()))


def test_runner_retrieves_with_time_backoff(conn, embedder, nominatim, add, sub):
    nov = add(month="11")
    add(place="北十間川", month="12")

    async def planner(_):
        return Plan.from_dict({"sub_queries": [sub(month="12")], "group_by": [], "compose": "merge"})

    out = run(conn, embedder, nominatim, planner)
    assert [e.content_id for e in out.evidence] == [nov]
    assert out.error is None and out.answer is None


def test_unreadable_plan_becomes_an_error_outcome(conn, embedder, nominatim):
    async def planner(_):
        raise PlanError("壞掉")

    out = run(conn, embedder, nominatim, planner)
    assert out.evidence == [] and "壞掉" in out.error
