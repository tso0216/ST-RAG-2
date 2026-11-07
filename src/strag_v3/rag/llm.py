"""規劃器和生成器：呼叫 Opus，以 structured output 取回結果。

實際的 LLM 呼叫在 `service/llm.py`（專案根目錄）。
"""
import json
from pathlib import Path

from service.llm import LLMError, call
from .evidence import Evidence, Section, SubQueryResult
from .plan import COMPOSE_MODES, GROUP_DIMENSIONS, Plan, SubQuery
from .timedist import TimeSpec

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
        },
        "group_by": {"type": "array", "items": {"type": "string", "enum": list(GROUP_DIMENSIONS)}},
        "compose": {"type": "string", "enum": list(COMPOSE_MODES)},
    },
    "required": ["sub_queries", "group_by", "compose"],
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


def _time_block(t: TimeSpec | None) -> dict:
    """時間標籤的三個維度；子查詢沒限制的維度寫「不限」。"""
    t = t or TimeSpec()
    return {"月份": t.month or "不限", "平日／假日": t.day_type or "不限", "時段": t.time or "不限"}


def _evidence_block(e: Evidence) -> dict:
    return {
        "片段 id": e.content_id,
        "文章": e.article_id,
        "地點": e.place,
        **_time_block(e.time),
        "時間相符程度": round(e.time_match, 2),
        "內容": e.content,
        "來自退讓": e.backoff,
    }


_DIMENSION_NAMES = {"month": "月份", "day_type": "平日／假日", "time_of_day": "時段", "place": "地點"}


def _sub_query_block(sq: SubQuery) -> dict:
    return {"地點": sq.space or "不限", **_time_block(sq.time), "面向": sq.aspect or "（同問題）"}


def _nearest_block(results: list[SubQueryResult]) -> str:
    """沒有證據的子查詢：列出它的檢索條件，和查過的範圍裡最接近的時段（只有標籤和筆數）。"""
    empty = [{
        "檢索條件": _sub_query_block(r.sub_query),
        "最接近的時段": [{"地點": n.place, **_time_block(n.time), "片段數": n.count} for n in r.nearest],
    } for r in results if not r.evidence]
    if not empty:
        return ""
    return (f"\n沒有證據的子查詢（{len(empty)} 個）：\n"
            f"```json\n{json.dumps(empty, ensure_ascii=False, indent=2)}\n```")


def _section_text(section: Section) -> str:
    """一段證據：先列這段的檢索條件，再列證據；有分組時依組列出。"""
    n = len(section.evidence)
    conditions = [_sub_query_block(r.sub_query) for r in section.results]
    if any(g.key for g in section.groups):
        body = [{"分組": {_DIMENSION_NAMES[d]: v for d, v in g.key.items()},
                 "證據": [_evidence_block(e) for e in g.evidence]} for g in section.groups]
        dims = "、".join(_DIMENSION_NAMES[d] for d in section.groups[0].key)
        head = f"證據（{n} 筆，依{dims}分組）："
    else:
        body = [_evidence_block(e) for e in section.evidence]
        head = f"證據（{n} 筆）："
    return (f"檢索條件：{json.dumps(conditions, ensure_ascii=False)}\n"
            f"{head}\n```json\n{json.dumps(body, ensure_ascii=False, indent=2)}\n```") + _nearest_block(section.results)


def build_answer_prompt(question: str, sections: list[Section]) -> str:
    """一段時直接列證據；多段（compose=contrast）時逐段列出，讓生成器分段說明再對照。"""
    parts = [f"旅客的問題：{question}"]
    if len(sections) == 1:
        parts.append(_section_text(sections[0]))
    else:
        parts.append(f"證據分成 {len(sections)} 段，每段是一個子查詢各自找到的證據，要分段說明再互相對照。")
        parts += [f"## 第 {i} 段\n{_section_text(s)}" for i, s in enumerate(sections, 1)]
    return "\n\n".join(parts)


async def answer(question: str, sections: list[Section]) -> str:
    system = (PROMPT_DIR / "generator.md").read_text()
    out = await call(system, build_answer_prompt(question, sections), ANSWER_SCHEMA, MODEL)
    return out["answer"]
