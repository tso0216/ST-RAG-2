"""空結果時的「最接近的時段資訊」：查過的地點裡，有資料的時段依離問題時間多遠排序。

時間門檻不放寬，這裡只回報時段標籤和筆數，不回傳片段內容。

時間距離：片段的時間落在問題時間範圍外多遠，三個維度各自算再相加（0–3）：
- 月份：到問題範圍最近一個月份的週期距離 ÷ 6
- 小時：到問題範圍最近一個小時的週期距離 ÷ 12
- 平日／假日：不在問題範圍內就是 1
問題範圍取隸屬度不低於峰值一半的格子。片段標籤是範圍、季節或 `不明` 時，依它的邊際分布取期望值。
"""
import sqlite3
from dataclasses import dataclass

from .params import DEFAULT, Params
from .plan import TimeSpec
from .timedist import day_marginal, hour_marginal, month_marginal

NEAREST_K = 3


@dataclass(frozen=True)
class NearestTime:
    """一個有資料的時段：景點和時間標籤相同的片段併成一筆。"""
    place: str
    month: str
    day_type: str
    time: str
    count: int


def nearest_times(conn: sqlite3.Connection, places: frozenset[str] | None, time: TimeSpec | None,
                  params: Params = DEFAULT, k: int = NEAREST_K) -> tuple[NearestTime, ...]:
    """places 是要找的片段景點名稱（None 代表不限地點）；回傳離 time 最近的 k 個時段。"""
    t = time or TimeSpec()
    q = (month_marginal(t.month), day_marginal(t.day_type), hour_marginal(t.time, params))

    sql = "SELECT poi_name, month, day_type, time, COUNT(*) FROM content"
    args: tuple = ()
    if places is not None:
        sql += f" WHERE poi_name IN ({', '.join('?' * len(places))})"
        args = tuple(sorted(places))
    sql += " GROUP BY poi_name, month, day_type, time"

    ranked = []
    for place, month, day_type, hour, count in conn.execute(sql, args):
        c = (month_marginal(month), day_marginal(day_type), hour_marginal(hour, params))
        dist = sum(_distance(qm, cm) for qm, cm in zip(q, c))
        ranked.append((dist, place, month, day_type, hour, count))
    ranked.sort()
    return tuple(NearestTime(*row[1:]) for row in ranked[:k])


def _distance(query: list[float], content: list[float]) -> float:
    """片段邊際分布到問題範圍的期望週期距離，除以最遠距離（格數的一半）正規化到 0–1。"""
    n = len(query)
    peak = max(query)
    core = [i for i, x in enumerate(query) if x >= peak / 2]

    def gap(j: int) -> int:
        return min(min(abs(i - j), n - abs(i - j)) for i in core)

    return sum(w * gap(j) for j, w in enumerate(content) if w) / (n // 2)
