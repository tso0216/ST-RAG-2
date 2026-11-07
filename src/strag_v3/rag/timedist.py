"""時間標籤 → 時間分布，以及兩個分布的時空重疊度。

時間分布定義在「月（12）× 平日／假日（2）× 小時（24）」共 576 格的週期格網上。
三個維度的標籤各自轉成邊際分布，再取外積。標籤留空或 `不明` 都給均勻分布。
"""
import re
from dataclasses import dataclass

from .params import DEFAULT, Params

N_MONTH, N_DAY, N_HOUR = 12, 2, 24
N_CELLS = N_MONTH * N_DAY * N_HOUR

DAY_TYPES = ("平日", "假日")
SEASONS = {"春": (3, 4, 5), "夏": (6, 7, 8), "秋": (9, 10, 11), "冬": (12, 1, 2)}
UNKNOWN = "不明"

_RANGE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_SINGLE = re.compile(r"^\d{1,2}$")


class LabelError(ValueError):
    """看不懂的時間標籤。"""


def _blank(label: str | None) -> bool:
    return label is None or not label.strip() or label.strip() == UNKNOWN


def _uniform(n: int) -> list[float]:
    return [1.0 / n] * n


def _normalize(w: list[float], label: str) -> list[float]:
    s = sum(w)
    if s <= 0:
        raise LabelError(f"標籤沒有任何質量：{label}")
    return [x / s for x in w]


def _cyclic_range(start: int, end: int, n: int) -> list[int]:
    """閉區間 start..end（0 起算），start > end 時跨過頭尾，例如 12-2 月、22-1 點。"""
    out, i = [start], start
    while i != end:
        i = (i + 1) % n
        out.append(i)
    return out


def month_marginal(label: str | None) -> list[float]:
    if _blank(label):
        return _uniform(N_MONTH)
    s = label.strip()
    if s in SEASONS:
        months = [m - 1 for m in SEASONS[s]]
    elif _SINGLE.match(s):
        months = [int(s) - 1]
    elif m := _RANGE.match(s):
        months = _cyclic_range(int(m[1]) - 1, int(m[2]) - 1, N_MONTH)
    else:
        raise LabelError(f"看不懂的月份標籤：{label}")
    if not all(0 <= m < N_MONTH for m in months):
        raise LabelError(f"月份超出 1–12：{label}")
    w = [0.0] * N_MONTH
    for m in months:
        w[m] = 1.0
    return _normalize(w, label)


def day_marginal(label: str | None) -> list[float]:
    if _blank(label):
        return _uniform(N_DAY)
    s = label.strip()
    if s not in DAY_TYPES:
        raise LabelError(f"看不懂的平日／假日標籤：{label}")
    return [1.0 if d == s else 0.0 for d in DAY_TYPES]


def _trapezoid(x: float, a: float, b: float, c: float, d: float) -> float:
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    if x <= c:
        return 1.0
    return (d - x) / (d - c)


def hour_marginal(label: str | None, params: Params = DEFAULT) -> list[float]:
    if _blank(label):
        return _uniform(N_HOUR)
    s = label.strip()
    if s in params.periods:
        a, b, c, d = params.periods[s]
        # 取格子中點；超過 24 或小於 0 的部分繞回
        w = [max(_trapezoid(h + 0.5 + k, a, b, c, d) for k in (-N_HOUR, 0, N_HOUR)) for h in range(N_HOUR)]
        return _normalize(w, label)
    if _SINGLE.match(s):
        hours = [int(s)]
    elif m := _RANGE.match(s):
        hours = _cyclic_range(int(m[1]), int(m[2]), N_HOUR)
    else:
        raise LabelError(f"看不懂的時間標籤：{label}")
    if not all(0 <= h < N_HOUR for h in hours):
        raise LabelError(f"小時超出 0–23：{label}")
    w = [0.0] * N_HOUR
    for h in hours:
        w[h] = 1.0
    return _normalize(w, label)


@dataclass(frozen=True)
class TimeDist:
    """576 格的時間分布，索引為 (月, 平日／假日, 小時)，總和為 1。"""
    cells: tuple[float, ...]

    @staticmethod
    def index(month: int, day: int, hour: int) -> int:
        return (month * N_DAY + day) * N_HOUR + hour


def to_dist(month: str | None = None, day_type: str | None = None, time: str | None = None,
            params: Params = DEFAULT) -> TimeDist:
    pm = month_marginal(month)
    pd = day_marginal(day_type)
    ph = hour_marginal(time, params)
    return TimeDist(tuple(m * d * h for m in pm for d in pd for h in ph))


def overlap(query: TimeDist, content: TimeDist) -> float:
    """時空重疊度：片段的時間落在問題時間範圍內的程度，0–1。

    問題分布除以自己的峰值當成隸屬度（範圍內為 1），再對片段分布取期望值。
    問題完全不限時間時，任何片段都是 1；片段整段落在問題範圍內時也是 1。
    """
    peak = max(query.cells)
    return sum(c * q for c, q in zip(content.cells, query.cells)) / peak
