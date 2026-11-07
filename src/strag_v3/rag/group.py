"""把各子查詢取回的證據整理成交給生成器的段落和分組。

- `compose=merge`：所有子查詢的證據合成一段；同一個片段被多個子查詢取回時只留分數最高的那筆。
- `compose=contrast`：每個子查詢自成一段，讓生成器分開說明再對照。
- `group_by`：每段的證據再依指定的維度分組，可以多選；每個片段分到它時間分布質量最大的那一組。
  組內照分數排序。
"""
from .evidence import Evidence, Group, Section, SubQueryResult
from .hierarchy import Hierarchy
from .params import DEFAULT, Params
from .plan import Plan
from .timedist import DAY_TYPES, N_DAY, N_HOUR, N_MONTH, TimeDist, to_dist

UNKNOWN = "不明"

MONTH_GROUPS: dict[str, range] = {str(m + 1): range(m, m + 1) for m in range(N_MONTH)}
DAY_TYPE_GROUPS: dict[str, range] = {d: range(i, i + 1) for i, d in enumerate(DAY_TYPES)}

# group_by=time_of_day 的時段組，每個小時只屬於一組。
# 每個小時取 params.DEFAULT_PERIODS 梯形值最高的時段詞，交界（例如 11 點早上和中午都是 0.5）歸給後面的時段；
# 五個時段詞都不涵蓋的 0–4 點另成「深夜」。
TIME_OF_DAY_GROUPS: dict[str, range] = {
    "早上": range(5, 11),
    "中午": range(11, 13),
    "下午": range(13, 17),
    "晚上": range(17, 24),
    "深夜": range(0, 5),
}

# 時間維度 → (在 576 格上的軸, 組名 → 該軸的索引)；組的順序就是輸出的順序，最後接「不明」。
_TIME_AXES: dict[str, tuple[int, dict[str, range]]] = {
    "month": (0, MONTH_GROUPS),
    "day_type": (1, DAY_TYPE_GROUPS),
    "time_of_day": (2, TIME_OF_DAY_GROUPS),
}


def build_sections(plan: Plan, results: list[SubQueryResult], places: Hierarchy,
                   params: Params = DEFAULT) -> list[Section]:
    """places 是已對應 DB 景點名稱的階層，`group_by=place` 依片段景點所屬的節點分組，組名用正式名稱。"""
    if plan.compose == "contrast":
        return [Section([r], _group(r.evidence, plan.group_by, places, params)) for r in results]
    return [Section(results, _group(_merged(results), plan.group_by, places, params))]


def _merged(results: list[SubQueryResult]) -> list[Evidence]:
    """各子查詢的證據合在一起；同一個片段只留分數最高的那筆，再照分數排序。"""
    best: dict[int, Evidence] = {}
    for e in (e for r in results for e in r.evidence):
        if e.content_id not in best or e.score > best[e.content_id].score:
            best[e.content_id] = e
    return sorted(best.values(), key=lambda e: (-e.score, e.content_id))


def _group(evidence: list[Evidence], dims: tuple[str, ...], places: Hierarchy, params: Params) -> list[Group]:
    buckets: dict[tuple[str, ...], list[Evidence]] = {}
    for e in evidence:
        buckets.setdefault(tuple(_label(e, d, places, params) for d in dims), []).append(e)
    # 時間維度照固定順序；地點照該地點最高分的證據排（證據已依分數排好，先出現的就是分數高的）
    order = {d: list(_TIME_AXES[d][1]) + [UNKNOWN] if d in _TIME_AXES
             else list(dict.fromkeys(places.canonical(e.place) for e in evidence)) for d in dims}
    keys = sorted(buckets, key=lambda k: [order[d].index(v) for d, v in zip(dims, k)])
    return [Group(dict(zip(dims, k)), buckets[k]) for k in keys]


def _label(e: Evidence, dim: str, places: Hierarchy, params: Params) -> str:
    """片段在該維度上分到哪一組：邊際分布質量最大的組，並列時取順序在前的；均勻分布（不明）另成一組。"""
    if dim == "place":
        return places.canonical(e.place)
    axis, groups = _TIME_AXES[dim]
    marginal = _marginal(to_dist(e.time, params), axis)
    if max(marginal) - min(marginal) < 1e-9:
        return UNKNOWN
    mass = {name: sum(marginal[i] for i in idx) for name, idx in groups.items()}
    best = max(mass.values())
    return next(name for name, m in mass.items() if m >= best - 1e-9)


def _marginal(dist: TimeDist, axis: int) -> list[float]:
    out = [0.0] * (N_MONTH, N_DAY, N_HOUR)[axis]
    for m in range(N_MONTH):
        for d in range(N_DAY):
            for h in range(N_HOUR):
                out[(m, d, h)[axis]] += dist.cells[TimeDist.index(m, d, h)]
    return out
