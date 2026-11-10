"""評審：JEV（`jev-1.14.0`）對每題的答案問兩種 Noul，noul ≥ 0.5 算「是」。

- 覆蓋：每條 `expect` 問一次「答案有沒有涵蓋這條重點」。`state` 是問題、該條重點、答案全文。
- 無支持：整份答案問一次「答案裡有沒有標準答案不支持的經驗說法」。`state` 是問題、問的時間、
  標準片段（全文和時間標籤）、標註為「時間不明」的排除片段（註明不計分）、答案。
  任何一條經驗說法對不上標準片段、也對不上時間不明片段，就是「有」。

每個判斷用同一個模型重問 n 次；分數只用第 1 次，第 2 次以後只用來看評審自己一不一致。
沒有答案的題（系統出錯）不送評審。評審不快取，每次都重新問。
"""
import asyncio
from dataclasses import dataclass, field

from service.jev import JEVClient

from ...rag.timematch import TimeQuery
from .fragments import Fragment, when_text
from .questions import Question
from .results import Outcome

MODEL = "jev-1.14.0"
PASS = 0.5

COVERAGE = {
    "name": "covers_point",
    "instructions": (
        "答案有沒有說出跟這條重點相同的事實？用字可以不同，但內容要一致："
        "講到同一件事卻結論相反、數字或時間不同、地點不同，都算沒涵蓋。"
        "重點開頭寫了時間或地點（例如「5 月下午：」「六義園：」）時，答案的時間或地點也要對得上。"
    ),
    "criteria": {"true": "答案裡有說法跟這條重點的事實一致，結論、數字、時間、地點都對得上。",
                 "false": "答案沒提到這件事，或提到了但結論相反、數字或時間不同、地點不同。"},
}
UNSUPPORTED = {
    "name": "unsupported_claim",
    "instructions": (
        "答案裡有沒有標準答案不支持的經驗說法？經驗說法是描述某個地點在某個時間實際是什麼狀況的說法"
        "（人潮、排隊、開放、景色、交通狀況等），不論是不是旅客親身經歷的口吻。"
        "每條經驗說法都要能在 reference_fragments 或 time_unknown_fragments 裡找到依據："
        "內容一致，地點和時間也要跟該片段對得上。時間看的是片段自己的時間標籤，不是問的時間："
        "答案明說這是另一個時間的經驗、而且跟片段的時間標籤一致，就算有依據。"
        "任何一條找不到依據，就是有。建議、一般介紹、說明沒有資料，不是經驗說法。"
    ),
    "criteria": {
        "true": "有：至少一條經驗說法在標準片段和時間不明片段裡都找不到依據，或地點、時間跟依據對不上。",
        "false": "沒有：每條經驗說法都找得到依據，或答案沒有任何經驗說法。",
    },
}
TIME_UNKNOWN_NOTE = "以下是時間標籤不明、沒列入標準答案的片段，不計分：答案的說法來自這些片段時，不算無支持。"


@dataclass
class Verdict:
    """一題的判斷。coverage 是每條 expect 的 n 次 noul，unsupported 是無支持的 n 次 noul。"""
    id: str
    skipped: bool = False
    coverage: list[list[float]] = field(default_factory=list)
    unsupported: list[float] = field(default_factory=list)

    @property
    def covered(self) -> list[bool]:
        """每條 expect 有沒有涵蓋（只看第 1 次）；沒送評審的題全部算沒涵蓋。"""
        return [ns[0] >= PASS for ns in self.coverage]

    @property
    def has_unsupported(self) -> bool:
        """有沒有無支持的說法（只看第 1 次）；沒送評審的題記「沒有」。"""
        return bool(self.unsupported) and self.unsupported[0] >= PASS


def time_text(t: TimeQuery | None) -> str:
    if t is None:
        return "不限"
    return "；".join((f"月份 {'、'.join(t.month) or '不限'}", f"平日／假日 {t.day_type or '不限'}",
                     f"時段 {'、'.join(t.time) or '不限'}"))


def asked_time(q: Question) -> str | dict:
    """問的時間：比較題是各選項的時間條件。"""
    if q.options:
        return {o.label: time_text(o.when) for o in q.options}
    return time_text(q.when)


def fragment_block(f: Fragment) -> dict:
    return {"id": f.id, "place": f.place, "time": when_text(f.time), "text": f.text}


def coverage_state(q: Question, point: str, answer: str) -> dict:
    return {"question": q.question, "point": point, "answer": answer}


def unsupported_state(q: Question, fragments: dict[int, Fragment], answer: str) -> dict:
    return {
        "question": q.question,
        "asked_time": asked_time(q),
        "reference_fragments": [fragment_block(fragments[i]) for i in q.relevant],
        "time_unknown_fragments": {"note": TIME_UNKNOWN_NOTE,
                                   "fragments": [fragment_block(fragments[i]) for i in sorted(q.time_unknown)]},
        "answer": answer,
    }


class Judge:
    def __init__(self, client: JEVClient, n: int = 1, model: str = MODEL, concurrency: int = 8):
        self.client = client
        self.n = n
        self.model = model
        self.sem = asyncio.Semaphore(concurrency)

    def config(self) -> dict:
        return {"model": self.model, "n": self.n, "pass": PASS, "coverage": COVERAGE, "unsupported": UNSUPPORTED}

    async def judge(self, questions: list[Question], fragments: dict[int, Fragment],
                    outcomes: list[Outcome]) -> list[Verdict]:
        """依 outcomes 的順序回傳每題的判斷。"""
        by_id = {q.id: q for q in questions}
        return list(await asyncio.gather(*(self._one(by_id[o.id], fragments, o) for o in outcomes)))

    async def _one(self, q: Question, fragments: dict[int, Fragment], o: Outcome) -> Verdict:
        if o.answer is None:
            return Verdict(q.id, skipped=True)
        coverage = [self._ask(coverage_state(q, p, o.answer), COVERAGE) for p in q.expect]
        unsupported = self._ask(unsupported_state(q, fragments, o.answer), UNSUPPORTED)
        *cov, uns = await asyncio.gather(*coverage, unsupported)
        return Verdict(q.id, coverage=list(cov), unsupported=uns)

    async def _ask(self, state: dict, question: dict) -> list[float]:
        """同一個判斷問 n 次，依序回傳 n 個 noul。"""
        async def once() -> float:
            async with self.sem:
                a = await self.client.noul(self.model, state, question["instructions"], question["criteria"],
                                           name=question["name"])
            return a.noul
        return list(await asyncio.gather(*(once() for _ in range(self.n))))


def _consistent(nouls: list[float]) -> bool:
    return len({n >= PASS for n in nouls}) <= 1


def disagreements(system: str, verdicts: list[Verdict]) -> list[dict]:
    """n 次的是／否不全相同的判斷，每筆一個 dict：系統、題目 id、第幾條 expect 或無支持、n 次的 noul。"""
    out = []
    for v in verdicts:
        out += [{"system": system, "id": v.id, "item": f"expect {i}", "nouls": ns}
                for i, ns in enumerate(v.coverage, 1) if not _consistent(ns)]
        if v.unsupported and not _consistent(v.unsupported):
            out.append({"system": system, "id": v.id, "item": "無支持", "nouls": v.unsupported})
    return out


def agreement(verdicts: list[Verdict]) -> dict[str, float | None]:
    """一致率：n 次判斷全部相同的比例，覆蓋（以 expect 條數計）和無支持（以題數計）分開算；沒送評審的題不算。"""
    cov = [_consistent(ns) for v in verdicts for ns in v.coverage]
    uns = [_consistent(v.unsupported) for v in verdicts if v.unsupported]
    return {"coverage": sum(cov) / len(cov) if cov else None, "unsupported": sum(uns) / len(uns) if uns else None}
