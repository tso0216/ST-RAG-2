"""比較表（markdown）：主表是系統 × 指標，第二張依題型分、只列平均。不適用的格子留空。"""
from dataclasses import dataclass

from .metrics import QuestionScore, Summary, summarize


@dataclass(frozen=True)
class Row:
    """一份評審檔：系統名稱（含 k）、取回的粒度、逐題分數。"""
    label: str
    retrieval: str
    scores: list[QuestionScore]


def label(config: dict) -> str:
    return f"{config['system']} (k={config['k']})" if config.get("k") is not None else config["system"]


def _num(x: float | None) -> str:
    return "" if x is None else f"{x:.3f}"


def _ci(x: float, ci: tuple[float, float]) -> str:
    return f"{x:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"


MAIN_HEAD = ("系統", "expect 覆蓋率 [95% CI]", "無支持比例 [95% CI]", "文章 recall", "片段 P", "片段 R", "片段 F1",
             "時間違規率", "出錯", "地點解析不到", "取回為空", "輸入 token／題", "LLM 呼叫／題", "JEV 呼叫／題")


def _table(head: tuple[str, ...], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])


def main_table(rows: list[Row]) -> str:
    out = []
    for r in rows:
        s: Summary = summarize(r.scores, r.retrieval)
        retrieves = r.retrieval != "none"
        out.append([r.label, _ci(s.coverage, s.coverage_ci), _ci(s.unsupported, s.unsupported_ci),
                    _num(s.article_recall), _num(s.precision), _num(s.recall), _num(s.f1), _num(s.violation_rate),
                    str(s.errors), str(s.place_unresolved) if retrieves else "", str(s.empty) if retrieves else "",
                    f"{s.input_tokens:.0f}", f"{s.llm_calls:.1f}", f"{s.jev_calls:.1f}"])
    return _table(MAIN_HEAD, out)


TYPE_HEAD = ("系統", "題型", "題數", "expect 覆蓋率", "無支持比例", "文章 recall", "片段 P", "片段 R", "片段 F1", "時間違規率")


def type_table(rows: list[Row]) -> str:
    out = []
    for r in rows:
        for t in dict.fromkeys(s.type for s in r.scores):
            s = summarize([x for x in r.scores if x.type == t], r.retrieval)
            out.append([r.label, t, str(s.n), _num(s.coverage), _num(s.unsupported), _num(s.article_recall),
                        _num(s.precision), _num(s.recall), _num(s.f1), _num(s.violation_rate)])
    return _table(TYPE_HEAD, out)


def report(rows: list[Row]) -> str:
    return ("## 主表\n\n" + main_table(rows) + "\n\n"
            "答案層兩項的 95% 信賴區間是逐題配對的 bootstrap。時間違規率是所有題合起來算；"
            "出錯、地點解析不到、取回為空的題都算進分母。\n\n"
            "## 依題型\n\n" + type_table(rows) + "\n")
