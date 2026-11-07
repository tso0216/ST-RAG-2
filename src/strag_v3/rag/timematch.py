"""時間標籤比對：問題的時間條件跟片段的時間標籤相不相符，以及時間退讓時怎麼往外擴。

三個維度都是硬過濾，不做時間分布或平滑（見 `docs/adr/0001-hard-time-filter-with-backoff.md`）：
- 月份：問題的月份標籤和片段的月份標籤各自換成月份集合，有交集就相符。季節：春 3–5、夏 6–8、秋 9–11、冬 12–2。
- 時段：片段的時段在問題的時段裡就相符；片段是 `全天` 時，問任何時段都相符；問題含 `全天` 等於不限時段。
- 平日／假日：字面相符。
- 片段某個維度是 `不明` 時，該維度算相符，但片段標成時間不明。
- 時間退讓：時段和月份各往外擴一格，都是環狀的（早上↔中午↔下午↔晚上↔早上，十二月↔一月）；平日／假日不擴。
"""
import re
from dataclasses import dataclass

SLOTS = ("早上", "中午", "下午", "晚上")
ALL_DAY = "全天"
UNKNOWN = "不明"
CONTENT_SLOTS = (*SLOTS, ALL_DAY, UNKNOWN)
QUERY_SLOTS = (*SLOTS, ALL_DAY)
DAY_TYPES = ("平日", "假日")
SEASONS = {"春": (3, 4, 5), "夏": (6, 7, 8), "秋": (9, 10, 11), "冬": (12, 1, 2)}

_RANGE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_SINGLE = re.compile(r"^\d{1,2}$")


class LabelError(ValueError):
    """看不懂的時間標籤。"""


def months_of(label: str) -> tuple[int, ...]:
    """月份標籤 → 依序列出的月份（1–12）：單一月份、範圍（`12-2` 跨年）、季節。`不明` 不在這裡處理。"""
    s = label.strip()
    if s in SEASONS:
        return SEASONS[s]
    if _SINGLE.match(s):
        start = end = int(s)
    elif m := _RANGE.match(s):
        start, end = int(m[1]), int(m[2])
    else:
        raise LabelError(f"看不懂的月份標籤：{label}")
    if not (1 <= start <= 12 and 1 <= end <= 12):
        raise LabelError(f"月份超出 1–12：{label}")
    return tuple((start - 1 + i) % 12 + 1 for i in range((end - start) % 12 + 1))


def month_order(label: str) -> tuple:
    """月份標籤的排序鍵：依起始月份；起始月份相同時單一月份在前，再來範圍、季節；`不明` 排最後。"""
    if label == UNKNOWN:
        return (13,)
    kind = 2 if label in SEASONS else 1 if "-" in label else 0
    return (months_of(label)[0], kind, label)


@dataclass(frozen=True)
class TimeSpec:
    """片段的時間標籤：每個維度一個值，看不出來就是 `不明`。"""
    month: str = UNKNOWN
    day_type: str = UNKNOWN
    time: str = UNKNOWN

    def __post_init__(self):
        if self.month != UNKNOWN:
            months_of(self.month)
        if self.day_type not in (*DAY_TYPES, UNKNOWN):
            raise LabelError(f"看不懂的平日／假日標籤：{self.day_type}")
        if self.time not in CONTENT_SLOTS:
            raise LabelError(f"片段的時段只能是 {'、'.join(CONTENT_SLOTS)}，不是「{self.time}」（舊格式的 DB 要重新抽取）")

    @property
    def unknown(self) -> bool:
        """任何一個維度是 `不明`：檢索時算相符，但標成時間不明。"""
        return UNKNOWN in (self.month, self.day_type, self.time)


@dataclass(frozen=True)
class TimeQuery:
    """問題（子查詢）的時間條件。月份和時段可以是一組；空的或 None 代表該維度不限。"""
    month: tuple[str, ...] = ()
    day_type: str | None = None
    time: tuple[str, ...] = ()

    def __post_init__(self):
        for label in self.month:
            months_of(label)
        if self.day_type is not None and self.day_type not in DAY_TYPES:
            raise LabelError(f"看不懂的平日／假日條件：{self.day_type}")
        for label in self.time:
            if label not in QUERY_SLOTS:
                raise LabelError(f"問題的時段只能是 {'、'.join(QUERY_SLOTS)}，不是「{label}」")

    @property
    def months(self) -> frozenset[int] | None:
        return frozenset(m for label in self.month for m in months_of(label)) if self.month else None

    @property
    def slots(self) -> frozenset[str] | None:
        return None if not self.time or ALL_DAY in self.time else frozenset(self.time)

    def matches(self, c: TimeSpec) -> bool:
        months, slots = self.months, self.slots
        return ((months is None or c.month == UNKNOWN or not months.isdisjoint(months_of(c.month)))
                and (self.day_type is None or c.day_type in (self.day_type, UNKNOWN))
                and (slots is None or c.time in (ALL_DAY, UNKNOWN) or c.time in slots))

    def widened(self) -> "TimeQuery | None":
        """時間退讓的條件：時段和月份各往外擴一格；平日／假日不變。兩個都不限時沒得擴，回傳 None。"""
        months, slots = self.months, self.slots
        if months is None and slots is None:
            return None
        wide_month = self.month
        if months is not None:
            order = [m for label in self.month for m in months_of(label)]
            wide_month = tuple(dict.fromkeys(str((m - 1 + d) % 12 + 1) for m in order for d in (-1, 0, 1)))
        wide_time = self.time
        if slots is not None:
            near = {SLOTS[(SLOTS.index(s) + d) % len(SLOTS)] for s in slots for d in (-1, 0, 1)}
            wide_time = tuple(s for s in SLOTS if s in near)
        return TimeQuery(wide_month, self.day_type, wide_time)
