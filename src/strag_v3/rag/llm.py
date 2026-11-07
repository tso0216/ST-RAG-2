"""規劃器和生成器：呼叫 Opus，以 structured output 取回結果。

實際的 LLM 呼叫在 `service/llm.py`（專案根目錄）。
"""
import json
from pathlib import Path

from service.llm import LLMError, call
from ..extract.paths import TIME_SLOTS_MARK, TIME_SLOTS_PATH
from .evidence import Evidence, Section, SubQueryResult
from .plan import Compose, Dimension, Plan, SubQuery
from ..place import KINDS
from .timematch import DAY_TYPES, QUERY_SLOTS, TimeQuery, TimeSpec

__all__ = ["LLMError", "plan", "answer"]

MODEL = "claude-opus-5-5"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}

_SPACE = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "name_ja": {"type": "string"},
        "city": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
    },
    "required": ["name", "name_ja", "city", "kind"],
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_queries": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "space": {"anyOf": [_SPACE, {"type": "null"}]},
                    "time": {
                        "type": "object",
                        "properties": {
                            "month": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
                            "day_type": {"anyOf": [{"type": "string", "enum": list(DAY_TYPES)}, {"type": "null"}]},
                            "time": {"anyOf": [{"type": "array", "items": {"type": "string", "enum": list(QUERY_SLOTS)}},
                                               {"type": "null"}]},
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
        "group_by": {"type": "array", "items": {"type": "string", "enum": [d.value for d in Dimension]}},
        "compose": {"type": "string", "enum": [c.value for c in Compose]},
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
    system = (PROMPT_DIR / "planner.md").read_text().replace(TIME_SLOTS_MARK, TIME_SLOTS_PATH.read_text().strip())
    out = await call(system, question, PLAN_SCHEMA, MODEL)
    return Plan.from_dict(out)


def _query_time_block(t: TimeQuery | None) -> dict:
    """子查詢的時間條件；沒限制的維度寫「不限」。"""
    t = t or TimeQuery()
    return {"月份": "、".join(t.month) or "不限", "平日／假日": t.day_type or "不限", "時段": "、".join(t.time) or "不限"}


def _content_time_block(t: TimeSpec) -> dict:
    return {"月份": t.month, "平日／假日": t.day_type, "時段": t.time}


def _evidence_block(e: Evidence) -> dict:
    return {
        "片段 id": e.content_id,
        "文章": e.article_id,
        "地點": e.place,
        **_content_time_block(e.time),
        "內容": e.content,
        "時間退讓": e.time_backoff,
        "空間退讓": e.space_backoff,
        **({"空間退讓到": e.backoff_area} if e.space_backoff else {}),
        "時間不明": e.time_unknown,
    }


def _sub_query_block(sq: SubQuery) -> dict:
    place = f"{sq.space.name}（{sq.space.kind}）" if sq.space else "不限"
    return {"地點": place, **_query_time_block(sq.time), "面向": sq.aspect or "（同問題）"}


def _empty_block(results: list[SubQueryResult]) -> str:
    """沒有證據的子查詢：列出它的檢索條件，和問的地點有資料的時段、月份（只有標籤和筆數）。"""
    empty = [{
        "檢索條件": _sub_query_block(r.sub_query),
        "有資料的時段": dict(r.available.time),
        "有資料的月份": dict(r.available.month),
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
        body = [{"分組": {d.label: v for d, v in g.key.items()},
                 "證據": [_evidence_block(e) for e in g.evidence]} for g in section.groups]
        dims = "、".join(d.label for d in section.groups[0].key)
        head = f"證據（{n} 筆，依{dims}分組）："
    else:
        body = [_evidence_block(e) for e in section.evidence]
        head = f"證據（{n} 筆）："
    return (f"檢索條件：{json.dumps(conditions, ensure_ascii=False)}\n"
            f"{head}\n```json\n{json.dumps(body, ensure_ascii=False, indent=2)}\n```") + _empty_block(section.results)


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
