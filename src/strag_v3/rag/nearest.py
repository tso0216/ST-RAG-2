"""空結果時的「最接近的時段資訊」：查過的地點裡，有資料的時段依離問題時間多遠排序。

時間門檻不放寬，這裡只回報時段標籤和筆數，不回傳片段內容。

時間距離：片段的時間落在問題時間範圍外多遠，三個維度各自算再相加（0–3）：
- 月份：到問題範圍最近一個月份的週期距離 ÷ 6
- 小時：到問題範圍最近一個小時的週期距離 ÷ 12
- 平日／假日：不在問題範圍內就是 1
問題範圍取隸屬度不低於峰值一半的格子。片段標籤是範圍、季節或 `不明` 時，依它的邊際分布取期望值。
"""
from collections import Counter
from dataclasses import dataclass

from .params import DEFAULT, Params
from .store import Content
from .timedist import TimeSpec, day_marginal, hour_marginal, month_marginal

NEAREST_K = 3


@dataclass(frozen=True)
class NearestTime:
    """一個有資料的時段：景點和時間標籤相同的片段併成一筆。"""
    place: str
    time: TimeSpec
    count: int


def nearest_times(contents: list[Content], time: TimeSpec | None, params: Params = DEFAULT) -> tuple[NearestTime, ...]:
    """查過的片段裡，離 time 最近的 NEAREST_K 個時段（time 是 None 代表不限時間）。"""
    q = _marginals(time or TimeSpec(), params)

    def distance(t: TimeSpec) -> float:
        return sum(_distance(qm, cm) for qm, cm in zip(q, _marginals(t, params)))

    counts = Counter((c.place, c.time) for c in contents)
    ranked = sorted(counts.items(), key=lambda item: (distance(item[0][1]), item[0][0], *_labels(item[0][1])))
    return tuple(NearestTime(place, t, n) for (place, t), n in ranked[:NEAREST_K])


def _marginals(t: TimeSpec, params: Params) -> tuple[list[float], list[float], list[float]]:
    return month_marginal(t.month), day_marginal(t.day_type), hour_marginal(t.time, params)


def _labels(t: TimeSpec) -> tuple[str, str, str]:
    """距離並列時依標籤字串排，讓順序固定。"""
    return t.month or "", t.day_type or "", t.time or ""


def _distance(query: list[float], content: list[float]) -> float:
    """片段邊際分布到問題範圍的期望週期距離，除以最遠距離（格數的一半）正規化到 0–1。"""
    n = len(query)
    peak = max(query)
    core = [i for i, x in enumerate(query) if x >= peak / 2]

    def gap(j: int) -> int:
        return min(min(abs(i - j), n - abs(i - j)) for i in core)

    return sum(w * gap(j) for j, w in enumerate(content) if w) / (n // 2)
