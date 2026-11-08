"""規劃器正確率：題目的 `gold_plan` 加上規劃器產生的計畫 → 每個欄位對不對，以及各欄位和整體的正確率。

欄位：
- 計畫層級：`sub_queries`（子查詢個數）、`group_by`（維度集合，不看順序）、`compose`。
- 子查詢層級：`space`、`month`、`day_type`、`time`、`aspect`。每一對子查詢各算一次。
  - 兩邊都留空算對，一邊留空一邊有填算錯。
  - `space`：兩邊都用地點解析模組解析，解析到同一個 OSM 物件、而且景點／區域的標記相同才算對；
    不比對名稱字串。任何一邊解析不到算錯。
  - `month`、`time`：比的是意思，不是寫法。月份換成月份集合（`12` 和 `12-12` 相同，`冬` 和 `12-2` 相同）；
    時段換成時段集合，含 `全天` 等於不限時段（跟留空相同），照檢索的比對規則。
  - `day_type`：字面相同。
  - `aspect`：自由文字，只看有沒有留空。
- 同一個地點、同一段時間、只有 aspect 不同的子查詢，比對前先併成一個（兩邊都併）：把一句話裡的
  幾個小問題拆成幾個子查詢，跟寫成一個子查詢算一樣。併起來的 aspect 只要有一個有填就算有填。
  「同一個地點」照 `space` 的規則（解析到同一個 OSM 物件）；「同一段時間」比的是月份、平假日、時段的意思。
- 子查詢的配對：兩邊的子查詢依「對的欄位最多」配成一對一（不看順序）；多出來的子查詢沒有對象，
  它的每個子查詢欄位都算錯。
- 規劃器產生不出看得懂的計畫時，每個欄位都算錯。

這題計畫正確：每個欄位都對。

彙總：
- 整體正確率：計畫正確的題數除以有 `gold_plan` 的題數。
- 各欄位正確率：對的次數除以比對次數（pooled）；子查詢欄位的比對次數是配對後的子查詢對數。
沒有 `gold_plan` 的題目不算這項指標。
"""
from dataclasses import dataclass, replace
from itertools import permutations

from ...place import Places
from ...rag.plan import Plan, Space, SubQuery
from ...rag.timematch import TimeQuery

PLAN_FIELDS = ("sub_queries", "group_by", "compose")
SUB_QUERY_FIELDS = ("space", "month", "day_type", "time", "aspect")
FIELDS = (*PLAN_FIELDS, *SUB_QUERY_FIELDS)


@dataclass(frozen=True)
class PlanScore:
    # 每個欄位：(對的次數, 比對次數)
    fields: dict[str, tuple[int, int]]

    @property
    def correct(self) -> bool:
        return all(ok == n for ok, n in self.fields.values())

    def to_dict(self) -> dict:
        return {"correct": self.correct, "fields": {k: list(v) for k, v in self.fields.items()}}


def score_plan(gold: Plan, pred: Plan | None, places: Places) -> PlanScore:
    """pred 是 None：規劃器產生不出看得懂的計畫，每個欄位都算錯。"""
    if pred is None:
        n = len(gold.sub_queries)
        return PlanScore({**{f: (0, 1) for f in PLAN_FIELDS}, **{f: (0, n) for f in SUB_QUERY_FIELDS}})
    resolve = _Resolver(places)
    gold_subs, pred_subs = _merge_same_scope(gold.sub_queries, resolve), _merge_same_scope(pred.sub_queries, resolve)
    plan_level = {
        "sub_queries": len(gold_subs) == len(pred_subs),
        "group_by": set(gold.group_by) == set(pred.group_by),
        "compose": gold.compose == pred.compose,
    }
    pairs = _pair(gold_subs, pred_subs, resolve)
    return PlanScore({
        **{f: (int(ok), 1) for f, ok in plan_level.items()},
        **{f: (sum(p[f] for p in pairs), len(pairs)) for f in SUB_QUERY_FIELDS},
    })


def aggregate(scores: list[PlanScore]) -> dict:
    totals = {f: [0, 0] for f in FIELDS}
    for s in scores:
        for f, (ok, n) in s.fields.items():
            totals[f][0] += ok
            totals[f][1] += n
    return {
        "n": len(scores),
        "accuracy": sum(s.correct for s in scores) / len(scores) if scores else None,
        **{f: ok / n if n else None for f, (ok, n) in totals.items()},
    }


class _Resolver:
    """space → 解析到的地點 id；同一個 space 只解析一次。"""

    def __init__(self, places: Places):
        self.places = places
        self.cache: dict[Space, int | None] = {}

    def __call__(self, s: Space) -> int | None:
        if s not in self.cache:
            p = self.places.resolve(s.name_ja, s.city, s.kind)
            self.cache[s] = p.id if p and p.kind == s.kind else None
        return self.cache[s]


def _merge_same_scope(subs: tuple[SubQuery, ...], resolve: _Resolver) -> tuple[SubQuery, ...]:
    """地點和時間的意思都相同的子查詢併成一個，保留第一個；aspect 取第一個有填的。"""
    merged: dict[tuple, SubQuery] = {}
    for sq in subs:
        t = sq.time or TimeQuery()
        place = None if sq.space is None else (sq.space.kind, resolve(sq.space) or sq.space)
        key = (place, t.months, t.day_type, t.slots)
        if key not in merged:
            merged[key] = sq
        elif merged[key].aspect is None and sq.aspect is not None:
            merged[key] = replace(merged[key], aspect=sq.aspect)
    return tuple(merged.values())


def _pair(gold: tuple[SubQuery, ...], pred: tuple[SubQuery, ...], resolve: _Resolver) -> list[dict[str, bool]]:
    """一對一配對，讓對的欄位總數最多；沒有對象的子查詢每個欄位都算錯。"""
    size = max(len(gold), len(pred))
    g = [*gold, *[None] * (size - len(gold))]
    p = [*pred, *[None] * (size - len(pred))]
    table = [[_compare(a, b, resolve) for b in p] for a in g]
    best = max(permutations(range(size)), key=lambda perm: sum(sum(table[i][j].values()) for i, j in enumerate(perm)))
    return [table[i][j] for i, j in enumerate(best)]


def _compare(gold: SubQuery | None, pred: SubQuery | None, resolve: _Resolver) -> dict[str, bool]:
    if gold is None or pred is None:
        return dict.fromkeys(SUB_QUERY_FIELDS, False)
    gt, pt = gold.time or TimeQuery(), pred.time or TimeQuery()
    return {
        "space": _same_space(gold.space, pred.space, resolve),
        "month": gt.months == pt.months,
        "day_type": gt.day_type == pt.day_type,
        "time": gt.slots == pt.slots,
        "aspect": (gold.aspect is None) == (pred.aspect is None),
    }


def _same_space(gold: Space | None, pred: Space | None, resolve: _Resolver) -> bool:
    if gold is None or pred is None:
        return gold is pred
    if gold.kind != pred.kind:
        return False
    g = resolve(gold)
    return g is not None and g == resolve(pred)
