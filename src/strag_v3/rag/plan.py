"""檢索計畫：一到多個子查詢，每個子查詢有 space、time、aspect，留空代表不限制。"""
from dataclasses import asdict, dataclass

from .timedist import LabelError, day_marginal, hour_marginal, month_marginal


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class TimeSpec:
    """格式跟 eval 的 `when` 相同；None 代表該維度不限。"""
    month: str | None = None
    day_type: str | None = None
    time: str | None = None


@dataclass(frozen=True)
class SubQuery:
    space: str | None = None
    time: TimeSpec | None = None
    aspect: str | None = None


@dataclass(frozen=True)
class Plan:
    sub_queries: tuple[SubQuery, ...]

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
        return cls(tuple(subs))

    def to_dict(self) -> dict:
        return {"sub_queries": [asdict(s) for s in self.sub_queries]}


def _clean(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None
