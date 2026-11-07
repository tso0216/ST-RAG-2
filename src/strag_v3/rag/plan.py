"""檢索計畫：一到多個子查詢，每個子查詢有 space、time、aspect，留空代表不限制。

計畫另有 `group_by`（取回的證據依哪些維度分組）和 `compose`（多個子查詢的結果合併或分開對照）。"""
from dataclasses import asdict, dataclass
from enum import StrEnum

from .timedist import LabelError, TimeSpec, day_marginal, hour_marginal, month_marginal


class PlanError(ValueError):
    pass


class Dimension(StrEnum):
    """group_by 可用的分組維度。值是計畫裡的寫法，`label` 是給生成器看的名稱。"""
    MONTH = "month", "月份"
    DAY_TYPE = "day_type", "平日／假日"
    TIME_OF_DAY = "time_of_day", "時段"
    PLACE = "place", "地點"

    def __new__(cls, value: str, label: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member


class Compose(StrEnum):
    """多個子查詢的證據怎麼交給生成器：合成一段，或每個子查詢一段分開對照。"""
    MERGE = "merge"
    CONTRAST = "contrast"


@dataclass(frozen=True)
class SubQuery:
    space: str | None = None
    time: TimeSpec | None = None
    aspect: str | None = None


@dataclass(frozen=True)
class Plan:
    sub_queries: tuple[SubQuery, ...]
    group_by: tuple[Dimension, ...] = ()
    compose: Compose = Compose.MERGE

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        subs = []
        for s in d.get("sub_queries") or []:
            t = s.get("time") or {}
            spec = TimeSpec(_clean(t.get("month")), _clean(t.get("day_type")), _clean(t.get("time")))
            try:
                month_marginal(spec.month), day_marginal(spec.day_type), hour_marginal(spec.time)
            except LabelError as e:
                raise PlanError(str(e)) from None
            subs.append(SubQuery(
                space=_clean(s.get("space")),
                time=spec if spec != TimeSpec() else None,
                aspect=_clean(s.get("aspect")),
            ))
        if not subs:
            raise PlanError("計畫沒有任何子查詢")
        group_by = tuple(dict.fromkeys(_parse(Dimension, dim, "分組維度") for dim in d.get("group_by") or []))
        compose = _parse(Compose, d.get("compose") or Compose.MERGE, " compose")
        return cls(tuple(subs), group_by, compose)

    def to_dict(self) -> dict:
        return {"sub_queries": [asdict(s) for s in self.sub_queries],
                "group_by": list(self.group_by), "compose": self.compose}


def _parse[E: StrEnum](enum: type[E], value, what: str) -> E:
    try:
        return enum(value)
    except ValueError:
        raise PlanError(f"看不懂的{what}：{value}") from None


def _clean(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None
