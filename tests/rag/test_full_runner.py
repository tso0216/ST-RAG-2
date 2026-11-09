"""主系統評估的 Runner：規劃器換成固定的計畫，跑一題取回片段。不打外部 API。"""
import asyncio

from strag_v3.eval.full.runner import Config, Runner
from strag_v3.eval.questions import Question
from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan, PlanError


def question() -> Question:
    return Question(key="t/q1", question="排隊要多久", when=None, relevant=frozenset())


def run(conn, embedder, nominatim, planner, jev, config=Config(answer=False)):
    return asyncio.run(Runner(conn, embedder, config, nominatim, planner=planner, jev=jev).run(question()))


def test_runner_retrieves_with_time_backoff(conn, embedder, nominatim, jev, add, sub):
    nov = add(month="11")
    add(place="北十間川", month="12")

    async def planner(_):
        return Plan.from_dict({"sub_queries": [sub(month="12")], "group_by": [], "compose": "merge"})

    out = run(conn, embedder, nominatim, planner, jev)
    assert [e.content_id for e in out.evidence] == [nov]
    assert out.error is None and out.answer is None


def test_unreadable_plan_becomes_an_error_outcome(conn, embedder, nominatim, jev):
    async def planner(_):
        raise PlanError("壞掉")

    out = run(conn, embedder, nominatim, planner, jev)
    assert out.evidence == [] and "壞掉" in out.error


def test_jev_failure_after_sdk_retries_becomes_an_error_outcome(conn, embedder, nominatim, jev, typesafe, add, sub):
    add(month="12")
    typesafe.fail = True

    async def planner(_):
        return Plan.from_dict({"sub_queries": [sub(month="12")], "group_by": [], "compose": "merge"})

    out = run(conn, embedder, nominatim, planner, jev)
    assert out.evidence == [] and "JEV" in out.error and "假的連線失敗" in out.error


def test_config_records_the_gate_and_the_jev_model_only_for_jev():
    assert Config().to_dict()["gate"] == "jev" and Config().to_dict()["jev_model"] == "jev-1.14.0"
    semantic = Config(params=Params(gate="semantic")).to_dict()
    assert semantic["gate"] == "semantic" and "jev_model" not in semantic


def test_semantic_gate_runs_without_a_jev_client(conn, embedder, nominatim, add, sub):
    row = add(month="12")

    async def planner(_):
        return Plan.from_dict({"sub_queries": [sub(month="12")], "group_by": [], "compose": "merge"})

    out = run(conn, embedder, nominatim, planner, None, Config(answer=False, params=Params(gate="semantic")))
    assert [e.content_id for e in out.evidence] == [row]
