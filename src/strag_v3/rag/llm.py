"""規劃器和生成器：呼叫 Opus，以 structured output 取回結果。

實際的 LLM 呼叫在 `service/llm.py`（專案根目錄）。
"""
import json
from dataclasses import asdict
from pathlib import Path

from service.llm import LLMError, call
from .plan import Plan
from .retrieve import Evidence, SubQueryResult

__all__ = ["LLMError", "plan", "answer"]

MODEL = "claude-opus-5-5"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_queries": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "space": _NULLABLE_STR,
                    "time": {
                        "type": "object",
                        "properties": {
                            "month": _NULLABLE_STR,
                            "day_type": {"anyOf": [{"type": "string", "enum": ["平日", "假日"]}, {"type": "null"}]},
                            "time": _NULLABLE_STR,
                        },
                        "required": ["month", "day_type", "time"],
                        "additionalProperties": False,
                    },
                    "aspect": _NULLABLE_STR,
                },
                "required": ["space", "time", "aspect"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sub_queries"],
    "additionalProperties": False,
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


async def plan(question: str) -> Plan:
    """zero-shot：prompt 只說明計畫格式。"""
    system = (PROMPT_DIR / "planner.md").read_text()
    out = await call(system, question, PLAN_SCHEMA, MODEL)
    return Plan.from_dict(out)


def _evidence_block(e: Evidence) -> dict:
    return {
        "片段 id": e.content_id,
        "文章": e.article_id,
        "地點": e.place,
        "月份": e.month,
        "平日／假日": e.day_type,
        "時段": e.time,
        "時空重疊度": round(e.overlap, 2),
        "內容": e.content,
        "來自退讓": e.backoff,
    }


def _nearest_block(results: list[SubQueryResult]) -> str:
    """沒有證據的子查詢：列出問的條件，和查過的範圍裡最接近的時段（只有標籤和筆數）。"""
    empty = [{
        "問的地點": r.sub_query.space or "不限",
        "問的時間": {k: v for k, v in asdict(r.sub_query.time).items() if v} if r.sub_query.time else "不限",
        "最接近的時段": [{"地點": n.place, "月份": n.month, "平日／假日": n.day_type, "時段": n.time,
                     "片段數": n.count} for n in r.nearest],
    } for r in results if not r.evidence]
    if not empty:
        return ""
    return (
        f"\n\n沒有證據的子查詢（{len(empty)} 個）：\n"
        f"```json\n{json.dumps(empty, ensure_ascii=False, indent=2)}\n```"
    )


def build_answer_prompt(question: str, results: list[SubQueryResult]) -> str:
    evidence = [_evidence_block(e) for r in results for e in r.evidence]
    return (
        f"旅客的問題：{question}\n\n"
        f"證據（{len(evidence)} 筆）：\n"
        f"```json\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n```"
    ) + _nearest_block(results)


async def answer(question: str, results: list[SubQueryResult]) -> str:
    system = (PROMPT_DIR / "generator.md").read_text()
    out = await call(system, build_answer_prompt(question, results), ANSWER_SCHEMA, MODEL)
    return out["answer"]
