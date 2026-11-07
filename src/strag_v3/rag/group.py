"""把各子查詢取回的證據整理成交給生成器的段和分組。

- `compose=merge`：所有子查詢的證據合成一段；同一個片段被多個子查詢取回時只留分數最高的那筆。
- `compose=contrast`：每個子查詢自成一段，讓生成器分開說明再對照。
- `group_by`：每段的證據再依指定的維度分組，可以多選。組內照分數排序。
  - 時間維度直接照片段自己的標籤分組：時段是早上、中午、下午、晚上、全天、不明各一組；
    月份照片段的月份標籤（`12`、`12-2`、`冬` 各成一組），依起始月份排，`不明` 排最後；平日／假日照字面。
  - 地點依片段所屬的地點（OSM 物件）分組，組名用地點的繁中名稱；掛在區域本身的片段自成一組，不拆到底下的景點。
"""
from dataclasses import replace

from .evidence import Evidence, Group, Section, SubQueryResult
from .plan import Compose, Dimension, Plan
from .timematch import CONTENT_SLOTS, DAY_TYPES, UNKNOWN, month_order


def build_sections(plan: Plan, results: list[SubQueryResult]) -> list[Section]:
    if plan.compose is Compose.CONTRAST:
        return [Section([r], _group(r.evidence, plan.group_by)) for r in results]
    return [Section(results, _group(_merged(results), plan.group_by))]


def _merged(results: list[SubQueryResult]) -> list[Evidence]:
    """各子查詢的證據合在一起，再照分數排序。

    同一個片段被多個子查詢取回時只留分數最高的那筆；退讓標記只在每一份都是退讓時才留，
    因為合併後生成器看到的是所有子查詢的條件，片段只要直接符合其中一個就不算退讓。
    """
    copies: dict[int, list[Evidence]] = {}
    for e in (e for r in results for e in r.evidence):
        copies.setdefault(e.content_id, []).append(e)
    merged = []
    for es in copies.values():
        best = max(es, key=lambda e: e.score)
        space_backoff = all(e.space_backoff for e in es)
        merged.append(replace(best, time_backoff=all(e.time_backoff for e in es), space_backoff=space_backoff,
                              backoff_area=best.backoff_area if space_backoff else None))
    return sorted(merged, key=lambda e: (-e.score, e.content_id))


def _group(evidence: list[Evidence], dims: tuple[Dimension, ...]) -> list[Group]:
    buckets: dict[tuple, list[Evidence]] = {}
    for e in evidence:
        buckets.setdefault(tuple(_key(e, d) for d in dims), []).append(e)
    # 地點照該地點最高分的證據排（證據已依分數排好，先出現的就是分數高的）
    place_order = list(dict.fromkeys(e.place_id for e in evidence))
    order = {
        Dimension.TIME_OF_DAY: CONTENT_SLOTS.index,
        Dimension.DAY_TYPE: (*DAY_TYPES, UNKNOWN).index,
        Dimension.MONTH: month_order,
        Dimension.PLACE: place_order.index,
    }
    keys = sorted(buckets, key=lambda k: [order[d](v) for d, v in zip(dims, k)])
    return [Group({d: _name(buckets[k][0], d) for d in dims}, buckets[k]) for k in keys]


def _key(e: Evidence, dim: Dimension):
    """片段在該維度上分到哪一組：時間維度是標籤本身，地點是 place id。"""
    match dim:
        case Dimension.TIME_OF_DAY:
            return e.time.time
        case Dimension.DAY_TYPE:
            return e.time.day_type
        case Dimension.MONTH:
            return e.time.month
        case Dimension.PLACE:
            return e.place_id


def _name(e: Evidence, dim: Dimension) -> str:
    """組名：時間維度是標籤本身，地點是地點的繁中名稱。"""
    return e.place if dim is Dimension.PLACE else _key(e, dim)
