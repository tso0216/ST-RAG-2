"""檢索指標：題目加上系統輸出 → 每題的指標，以及整體、依題型、依 dev／test 的彙總。

每題：
- 取回集合：各段證據的片段 id 合起來（同一個片段只算一次）。
- recall、precision、F1：取回集合對 `relevant_contents`。
  - 不計分的片段（題目檔 `excluded` 裡理由是「時間不明」的）先從取回集合拿掉：撈到不算誤撈；
    它們本來就不在 `relevant_contents` 裡，所以也不影響 recall。系統照設計會撈時間標成不明的片段，
    但標準答案不知道它是不是問的那個時間，算對算錯都不公平。
  - 取回（拿掉不計分的之後）是空的：recall、precision、F1 都是 0；但題目本來就沒有相關片段時，三個都是 1（正確地什麼都沒取）。
  - 題目沒有相關片段、卻取回了東西：precision、F1 是 0，recall 是 1（沒有東西可漏）。
  - 題目沒有 `relevant_contents`（還沒標註）：三個都不算。
- 時間違規：取回的片段時間跟題目的 `when` 不相符（照檢索的比對規則，`不明` 的維度算相符），
  又沒有標成時間退讓或空間退讓。同一個片段在不同段出現時，只要有一份沒標退讓就算違規。
- 有回答：取回集合不是空的（不計分的片段也算）。

彙總：
- recall、precision、F1 是各題的平均（macro），不含沒標註的題目。
- 時間違規率是所有題目的違規片段數除以取回片段數（pooled），沒有取回任何片段時不算。
- 有回答率是有回答的題數除以題數。
- 地點解析失敗是有任何子查詢地點解析不到的題數；每題的紀錄另外列出解析不到的地點。
- 答案指標（`answer`）：`expect` 覆蓋率和時間誤植率，由評審的判斷算出，規則見 `full/answer.py`。
  沒有傳 `judgements`（評審結果）時不算。
沒有 `type` 或 `split` 的題目，分組時歸在「未標」。
"""
from dataclasses import asdict, dataclass, field

from ..rag.evidence import Evidence, Section
from ..rag.plan import Plan
from .full.answer import Judgement, aggregate as aggregate_answers
from .questions import Question

UNTAGGED = "未標"


@dataclass(frozen=True)
class Outcome:
    """系統對一題的輸出：交給生成器的段、檢索計畫（dense 沒有）、答案（沒開生成時沒有）。"""
    sections: list[Section] = field(default_factory=list)
    plan: Plan | None = None
    answer: str | None = None
    # 這題跑不起來的原因（例如規劃器產生了看不懂的計畫）；有錯誤時當作什麼都沒取回
    error: str | None = None

    @property
    def evidence(self) -> list[Evidence]:
        return [e for s in self.sections for e in s.evidence]

    @property
    def unresolved_places(self) -> list[dict]:
        """地點解析不到的子查詢問的地點（同一個地點只列一次）。"""
        out: list[dict] = []
        for s in self.sections:
            for r in s.results:
                if r.place_unresolved and r.sub_query.space and (d := asdict(r.sub_query.space)) not in out:
                    out.append(d)
        return out


@dataclass(frozen=True)
class Score:
    retrieved: tuple[int, ...]
    hits: tuple[int, ...]
    recall: float | None
    precision: float | None
    f1: float | None
    violations: tuple[int, ...]
    answered: bool
    # 取回的片段裡不計分的
    unscored: tuple[int, ...] = ()


def score(q: Question, out: Outcome) -> Score:
    retrieved = sorted({e.content_id for e in out.evidence})
    scored = [c for c in retrieved if c not in q.unscored]
    violations = sorted({e.content_id for e in out.evidence
                         if q.when is not None and not q.when.matches(e.time)
                         and not (e.time_backoff or e.space_backoff)})
    hits: list[int] = []
    recall = precision = f1 = None
    if q.relevant is not None and not scored:
        recall = precision = f1 = 0.0 if q.relevant else 1.0
    elif q.relevant is not None:
        hits = sorted(q.relevant.intersection(scored))
        precision = len(hits) / len(scored)
        recall = len(hits) / len(q.relevant) if q.relevant else 1.0
        f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return Score(tuple(retrieved), tuple(hits), recall, precision, f1, tuple(violations), bool(retrieved),
                 tuple(c for c in retrieved if c in q.unscored))


def aggregate(scores: list[Score], errors: int = 0, unresolved: int = 0) -> dict:
    labelled = [s for s in scores if s.recall is not None]
    retrieved = sum(len(s.retrieved) for s in scores)
    violations = sum(len(s.violations) for s in scores)
    return {
        "n": len(scores),
        "recall": _mean([s.recall for s in labelled]),
        "precision": _mean([s.precision for s in labelled]),
        "f1": _mean([s.f1 for s in labelled]),
        "time_violation_rate": violations / retrieved if retrieved else None,
        "answered_rate": _mean([float(s.answered) for s in scores]),
        "retrieved": retrieved,
        "unscored": sum(len(s.unscored) for s in scores),
        "violations": violations,
        "labelled": len(labelled),
        "errors": errors,
        "unresolved": unresolved,
    }


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def evaluate(questions: list[Question], outcomes: dict[str, Outcome],
             judgements: dict[str, Judgement] | None = None) -> dict:
    """每題的紀錄（計畫、取回集合、證據、答案、指標）加上整體、依題型、依 split 的彙總。

    judgements：評審對各題答案的判斷（題目 key → 判斷），用來算答案指標；None 或缺題時那些題不算。"""
    judgements = judgements or {}
    rows = [(q, outcomes[q.key], score(q, outcomes[q.key])) for q in questions]

    def summary(subset) -> dict:
        return {**aggregate([s for _, _, s in subset], errors=sum(o.error is not None for _, o, _ in subset),
                            unresolved=sum(bool(o.unresolved_places) for _, o, _ in subset)),
                "answer": aggregate_answers([judgements[q.key] for q, _, _ in subset if q.key in judgements])}

    def by(attr: str) -> dict:
        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(getattr(row[0], attr) or UNTAGGED, []).append(row)
        return {k: summary(v) for k, v in sorted(groups.items(), key=lambda kv: (kv[0] == UNTAGGED, kv[0]))}

    return {
        "summary": {"overall": summary(rows), "by_split": by("split"), "by_type": by("type")},
        "questions": [_record(q, o, s, judgements.get(q.key)) for q, o, s in rows],
    }


def _record(q: Question, o: Outcome, s: Score, judgement: Judgement | None) -> dict:
    return {
        "key": q.key,
        "question": q.question,
        "type": q.type,
        "split": q.split,
        "when": q.when_raw,
        "relevant": None if q.relevant is None else sorted(q.relevant),
        "retrieved": list(s.retrieved),
        "hits": list(s.hits),
        "unscored": list(s.unscored),
        "recall": s.recall,
        "precision": s.precision,
        "f1": s.f1,
        "violations": list(s.violations),
        "answered": s.answered,
        "error": o.error,
        "unresolved_places": o.unresolved_places,
        "plan": o.plan.to_dict() if o.plan else None,
        "sections": [asdict(sec) for sec in o.sections],
        "answer": o.answer,
        "expect": list(q.expect),
        "judge": judgement.to_dict() if judgement else None,
    }
