"""校準評審：用 ptt_v2 現有的正反向答案，確認兩種問法靠得住。

- 正向答案：照 `expect_sources` 只用標準片段的原句拼成（拼法同出題工具 `qgen.py answer`）。
  每條 expect 都要判涵蓋，無支持要判「沒有」。
- 反向答案：校準檔裡每題一個。每條 expect 都要判不涵蓋，無支持要判「有」。
分數只看第 1 次判斷；n > 1 時另外印出不一致的判斷。
"""
from dataclasses import dataclass, field

from .fragments import Fragment, when_text
from .judge import Judge, Verdict
from .questions import Question
from .results import Outcome


def positive_answer(q: Question, fragments: dict[int, Fragment]) -> str:
    """只用證據原句拼成的答案：揭露條照抄（去掉「說明」），其餘每個來源寫成「地點（時間標籤）：原句 [片段 id]」。"""
    lines = []
    for point, sources in zip(q.expect, q.expect_sources):
        if not sources:
            lines.append(point.removeprefix("說明") + "。")
        for cid, quote in sources.items():
            f = fragments[cid]
            lines.append(f"{f.place}（{when_text(f.time)}）：{quote} [{cid}]")
    return "\n".join(lines)


@dataclass
class Calibration:
    # 沒過的條目：（題目 id, 說明）
    coverage_failures: list[tuple[str, str]] = field(default_factory=list)
    unsupported_failures: list[tuple[str, str]] = field(default_factory=list)
    # 覆蓋、無支持各判了幾次（正向加反向）
    coverage_total: int = 0
    unsupported_total: int = 0
    positive: list[Verdict] = field(default_factory=list)
    negative: list[Verdict] = field(default_factory=list)


async def calibrate(judge: Judge, questions: list[Question], fragments: dict[int, Fragment],
                    negatives: dict[str, str]) -> Calibration:
    qs = [q for q in questions if q.id in negatives]
    pos = await judge.judge(qs, fragments, [Outcome(q.id, answer=positive_answer(q, fragments)) for q in qs])
    neg = await judge.judge(qs, fragments, [Outcome(q.id, answer=negatives[q.id]) for q in qs])
    out = Calibration(positive=pos, negative=neg)
    for q, p, n in zip(qs, pos, neg):
        for i, point in enumerate(q.expect):
            if not p.covered[i]:
                out.coverage_failures.append((q.id, f"[正向沒涵蓋] {q.id}｜expect {i + 1}｜{point}｜noul {p.coverage[i][0]:.2f}"))
            if n.covered[i]:
                out.coverage_failures.append((q.id, f"[反向沒擋住] {q.id}｜expect {i + 1}｜{point}｜noul {n.coverage[i][0]:.2f}"))
        if p.has_unsupported:
            out.unsupported_failures.append((q.id, f"[正向判有無支持] {q.id}｜noul {p.unsupported[0]:.2f}"))
        if not n.has_unsupported:
            out.unsupported_failures.append((q.id, f"[反向判沒有無支持] {q.id}｜noul {n.unsupported[0]:.2f}"))
        out.coverage_total += 2 * len(q.expect)
        out.unsupported_total += 2
    return out
