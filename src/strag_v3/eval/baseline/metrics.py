"""指標：題目、系統輸出、評審判斷 → 每題分數 → 一個系統的彙總。

| 指標 | 算法 | 適用 |
|---|---|---|
| expect 覆蓋率 | 每題涵蓋條數 ÷ 總條數，取各題平均 | 全部 |
| 無支持答案比例 | 判「有」的題數 ÷ 題數 | 全部 |
| 文章級 recall | 取回的文章裡是標準文章的數量 ÷ 標準文章數，各題平均 | 有取回的（article、fragment） |
| 片段級 precision、recall、F1 | 取回的片段對標準片段，各題平均 | fragment |
| 時間違規率 | 違規片段數 ÷ 取回片段數，所有題合起來算 | fragment |
| 成本 | 每題平均的生成器輸入 token、LLM 呼叫數、JEV 呼叫數 | 全部 |

計分規則：
- 取回的片段先拿掉標註為「時間不明」的排除片段（不算命中也不算誤撈），重複的只算一次。
- 時間違規：片段的時間標籤跟題目的時間條件矛盾（`TimeQuery.matches` 不符）。標籤不明的維度不算矛盾；
  strag 標了退讓的片段不算；比較題只要符合任一選項的時間條件就不算。
- 出錯、地點解析不到、取回為空（三者不重複計）的題照樣算進分母：沒送評審的題覆蓋率 0、無支持「沒有」，檢索指標都是 0。
- 答案層兩項附 95% 信賴區間：逐題 bootstrap，亂數種子固定，所以每個系統重抽到的題目都一樣（配對）。
"""
import random
from dataclasses import dataclass

from .fragments import Fragment
from .judge import Verdict
from .questions import Question
from .results import Outcome

BOOTSTRAP = 10_000
SEED = 20261110


@dataclass(frozen=True)
class QuestionScore:
    id: str
    type: str
    coverage: float
    unsupported: bool
    # 不適用時是 None
    article_recall: float | None
    precision: float | None
    recall: float | None
    f1: float | None
    # 拿掉時間不明片段後的取回片段數、其中時間違規的片段數（fragment 系統才有）
    retrieved: int | None
    violations: int | None
    error: bool
    place_unresolved: bool
    empty: bool
    input_tokens: int
    llm_calls: int
    jev_calls: int


def score_question(q: Question, o: Outcome, v: Verdict, fragments: dict[int, Fragment], retrieval: str) -> QuestionScore:
    covered = v.covered
    coverage = sum(covered) / len(q.expect) if q.expect else 0.0
    article_recall = precision = recall = f1 = None
    retrieved = violations = None
    if retrieval in ("article", "fragment"):
        article_recall = len(set(o.articles) & set(q.articles)) / len(q.articles)
    if retrieval == "fragment":
        got = [c for c in dict.fromkeys(o.contents) if c not in q.time_unknown]
        hits = len(set(got) & set(q.relevant))
        precision = hits / len(got) if got else 0.0
        recall = hits / len(q.relevant)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        retrieved = len(got)
        violations = sum(_violates(q, fragments[c]) for c in got if c not in o.backoff)
    empty = (o.error is None and not o.place_unresolved and retrieval != "none"
             and not (o.contents if retrieval == "fragment" else o.articles))
    return QuestionScore(q.id, q.type, coverage, v.has_unsupported, article_recall, precision, recall, f1,
                         retrieved, violations, error=o.error is not None, place_unresolved=o.place_unresolved,
                         empty=empty, input_tokens=o.cost.input_tokens, llm_calls=o.cost.llm_calls,
                         jev_calls=o.cost.jev_calls)


def _violates(q: Question, f: Fragment) -> bool:
    return not any(t is None or t.matches(f.time) for t in q.time_conditions)


def score_run(questions: list[Question], outcomes: list[Outcome], verdicts: list[Verdict],
              fragments: dict[int, Fragment], retrieval: str) -> list[QuestionScore]:
    """依題目的順序；題目在結果檔裡缺了就當成出錯。"""
    outs = {o.id: o for o in outcomes}
    vs = {v.id: v for v in verdicts}
    return [score_question(q, outs.get(q.id, Outcome(q.id, error="結果檔裡沒有這題")),
                           vs.get(q.id, Verdict(q.id, skipped=True)), fragments, retrieval) for q in questions]


@dataclass(frozen=True)
class Summary:
    n: int
    coverage: float
    coverage_ci: tuple[float, float]
    unsupported: float
    unsupported_ci: tuple[float, float]
    article_recall: float | None
    precision: float | None
    recall: float | None
    f1: float | None
    violation_rate: float | None
    errors: int
    place_unresolved: int
    empty: int
    input_tokens: float
    llm_calls: float
    jev_calls: float


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _optional_mean(xs: list[float | None]) -> float | None:
    """不適用的指標每題都是 None。"""
    present = [x for x in xs if x is not None]
    return _mean(present) if present else None


def bootstrap_ci(xs: list[float], seed: int = SEED, rounds: int = BOOTSTRAP) -> tuple[float, float]:
    """逐題重抽的 95% 百分位區間。種子固定，同樣題數的系統重抽到同樣的題目（配對）。"""
    if not xs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(rounds))
    return (means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1])


def summarize(scores: list[QuestionScore], retrieval: str) -> Summary:
    cov = [s.coverage for s in scores]
    uns = [float(s.unsupported) for s in scores]
    retrieved = sum(s.retrieved or 0 for s in scores)
    violation_rate = None
    if retrieval == "fragment":
        violation_rate = sum(s.violations or 0 for s in scores) / retrieved if retrieved else 0.0
    return Summary(
        n=len(scores), coverage=_mean(cov), coverage_ci=bootstrap_ci(cov), unsupported=_mean(uns),
        unsupported_ci=bootstrap_ci(uns),
        article_recall=_optional_mean([s.article_recall for s in scores]),
        precision=_optional_mean([s.precision for s in scores]),
        recall=_optional_mean([s.recall for s in scores]),
        f1=_optional_mean([s.f1 for s in scores]),
        violation_rate=violation_rate,
        errors=sum(s.error for s in scores), place_unresolved=sum(s.place_unresolved for s in scores),
        empty=sum(s.empty for s in scores),
        input_tokens=_mean([s.input_tokens for s in scores]), llm_calls=_mean([s.llm_calls for s in scores]),
        jev_calls=_mean([s.jev_calls for s in scores]),
    )
