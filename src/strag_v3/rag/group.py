"""把各子查詢取回的證據整理成交給生成器的段和分組。

- `compose=merge`：所有子查詢的證據合成一段；同一個片段被多個子查詢取回時只留分數最高的那筆。
- `compose=contrast`：每個子查詢自成一段，讓生成器分開說明再對照。
- `group_by`：每段的證據再依指定的維度分組，可以多選。組內照分數排序。
  - 時間維度只看片段自己的時間標籤，用不平滑的邊際分布，所以分組不隨平滑頻寬改變。
    標籤是 `不明` 另成「不明」組；標籤本身就是組名時歸那組（例如「全天」）；
    其餘歸邊際分布質量最大的組，並列時歸順序在前的。
  - 地點依片段景點在階層裡的節點分組，同一節點的別名在同一組，組名用正式名稱。
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from .evidence import Evidence, Group, Section, SubQueryResult
from .hierarchy import Hierarchy
from .params import DEFAULT, Params
from .plan import Plan
from .timedist import (DAY_TYPES, N_MONTH, UNKNOWN, TimeSpec, day_marginal, hour_marginal, is_unknown,
                       month_marginal)

MONTH_GROUPS: dict[str, Sequence[int]] = {str(m + 1): (m,) for m in range(N_MONTH)}
DAY_TYPE_GROUPS: dict[str, Sequence[int]] = {d: (i,) for i, d in enumerate(DAY_TYPES)}

# group_by=time_of_day 的時段組，每個小時只屬於一組。
# 每個小時取 params.DEFAULT_PERIODS 梯形值最高的時段詞，交界（例如 11 點早上和中午都是 0.5）歸給後面的時段；
# 五個時段詞都不涵蓋的 0–4 點另成「深夜」。「全天」不佔任何鐘點，只收時間標籤就寫「全天」的片段。
TIME_OF_DAY_GROUPS: dict[str, Sequence[int]] = {
    "早上": range(5, 11),
    "中午": range(11, 13),
    "下午": range(13, 17),
    "晚上": range(17, 24),
    "深夜": range(0, 5),
    "全天": (),
}


@dataclass(frozen=True)
class _TimeAxis:
    """一個時間維度怎麼分組。"""
    label: Callable[[TimeSpec], str | None]                # 片段在這個維度的時間標籤
    marginal: Callable[[str | None, Params], list[float]]  # 標籤 → 不平滑的邊際分布
    groups: dict[str, Sequence[int]]                       # 組名 → 邊際分布的索引；順序就是輸出的順序，最後接「不明」


_TIME_AXES: dict[str, _TimeAxis] = {
    "month": _TimeAxis(lambda t: t.month, lambda label, _: month_marginal(label), MONTH_GROUPS),
    "day_type": _TimeAxis(lambda t: t.day_type, lambda label, _: day_marginal(label), DAY_TYPE_GROUPS),
    "time_of_day": _TimeAxis(lambda t: t.time, hour_marginal, TIME_OF_DAY_GROUPS),
}


def build_sections(plan: Plan, results: list[SubQueryResult], places: Hierarchy,
                   params: Params = DEFAULT) -> list[Section]:
    """places 是已對應 DB 景點名稱的階層，`group_by=place` 依片段景點所屬的節點分組，組名用正式名稱。"""
    if plan.compose == "contrast":
        return [Section([r], _group(r.evidence, plan.group_by, places, params)) for r in results]
    return [Section(results, _group(_merged(results), plan.group_by, places, params))]


def _merged(results: list[SubQueryResult]) -> list[Evidence]:
    """各子查詢的證據合在一起，再照分數排序。

    同一個片段被多個子查詢取回時只留分數最高的那筆；時間相符程度取各筆裡最高的，
    因為合併後生成器看到的是所有子查詢的條件，片段只要落在其中一個的時間內就算相符。
    """
    copies: dict[int, list[Evidence]] = {}
    for e in (e for r in results for e in r.evidence):
        copies.setdefault(e.content_id, []).append(e)
    merged = [replace(max(es, key=lambda e: e.score), time_match=max(e.time_match for e in es))
              for es in copies.values()]
    return sorted(merged, key=lambda e: (-e.score, e.content_id))


def _group(evidence: list[Evidence], dims: tuple[str, ...], places: Hierarchy, params: Params) -> list[Group]:
    buckets: dict[tuple[str, ...], list[Evidence]] = {}
    for e in evidence:
        buckets.setdefault(tuple(_label(e, d, places, params) for d in dims), []).append(e)
    # 時間維度照固定順序；地點照該地點最高分的證據排（證據已依分數排好，先出現的就是分數高的）
    order = {d: [*_TIME_AXES[d].groups, UNKNOWN] if d in _TIME_AXES
             else list(dict.fromkeys(places.canonical(e.place) for e in evidence)) for d in dims}
    keys = sorted(buckets, key=lambda k: [order[d].index(v) for d, v in zip(dims, k)])
    return [Group(dict(zip(dims, k)), buckets[k]) for k in keys]


def _label(e: Evidence, dim: str, places: Hierarchy, params: Params) -> str:
    """片段在該維度上分到哪一組。"""
    if dim in _TIME_AXES:
        return _time_group(e.time, _TIME_AXES[dim], params)
    return places.canonical(e.place)


def _time_group(t: TimeSpec, axis: _TimeAxis, params: Params) -> str:
    label = axis.label(t)
    if is_unknown(label):
        return UNKNOWN
    if label.strip() in axis.groups:
        return label.strip()
    w = axis.marginal(label, params)
    mass = {name: sum(w[i] for i in idx) for name, idx in axis.groups.items()}
    best = max(mass.values())
    return next(name for name, m in mass.items() if m >= best - 1e-9)
