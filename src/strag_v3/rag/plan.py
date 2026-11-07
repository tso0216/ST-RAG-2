"""檢索計畫：一到多個子查詢，每個子查詢有 space、time、aspect，留空代表不限制。

space 寫出繁中名稱、日文名稱、城市、景點或區域；檢索時用日文名稱、城市、種類解析成 OSM 物件（見 `place.py`）。
計畫另有 `group_by`（取回的證據依哪些維度分組）和 `compose`（多個子查詢的結果合併或分開對照）。"""
from dataclasses import asdict, dataclass
from enum import StrEnum

from ..place import KINDS
from .timematch import LabelError, TimeQuery


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
class Space:
    name: str      # 繁中名稱，顯示用
    name_ja: str   # 日文名稱，給 Nominatim 查詢
    city: str      # 城市（日文）
    kind: str      # 景點、區域

    @classmethod
    def from_dict(cls, d) -> "Space | None":
        if d is None:
            return None
        if not isinstance(d, dict):
            raise PlanError(f"space 要寫成 {{name, name_ja, city, kind}}，不是 {d!r}")
        name_ja, kind = _clean(d.get("name_ja")), _clean(d.get("kind"))
        if not name_ja:
            raise PlanError(f"space 沒有日文名稱：{d}")
        if kind not in KINDS:
            raise PlanError(f"space 的 kind 只能是 {'、'.join(KINDS)}，不是「{kind}」")
        return cls(name=_clean(d.get("name")) or name_ja, name_ja=name_ja, city=_clean(d.get("city")) or "", kind=kind)


@dataclass(frozen=True)
class SubQuery:
    space: Space | None = None
    time: TimeQuery | None = None
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
            try:
                spec = TimeQuery(_labels(t.get("month")), _clean(t.get("day_type")), _labels(t.get("time")))
            except LabelError as e:
                raise PlanError(str(e)) from None
            subs.append(SubQuery(
                space=Space.from_dict(s.get("space")),
                time=spec if spec != TimeQuery() else None,
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


def _labels(v) -> tuple[str, ...]:
    """月份或時段：一個值或一組值都可以；空的去掉，重複的只留一個。"""
    values = v if isinstance(v, (list, tuple)) else [v]
    return tuple(dict.fromkeys(x for x in map(_clean, values) if x))


def _clean(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None
