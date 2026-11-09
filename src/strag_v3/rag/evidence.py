"""檢索的輸出：每筆證據、每個子查詢的結果，以及交給生成器的段和分組。"""
from dataclasses import dataclass

from .plan import Dimension, SubQuery
from .timematch import TimeSpec


@dataclass(frozen=True)
class Evidence:
    content_id: int
    article_id: str
    place_id: int
    # 地點的顯示名稱（繁中）
    place: str
    time: TimeSpec
    content: str
    # 相關分數：gate=jev 時是 JEV 的 noul，gate=semantic 和 dense baseline 是 embedding cosine
    relevance: float
    # 排序用的分數：相關分數，時間不明時再乘上 unknown_discount
    score: float
    # 子查詢原本的時間條件沒有證據，時段和月份各往外擴一格才找到
    time_backoff: bool = False
    # 子查詢的地點沒有證據，退到外圍的行政區才找到
    space_backoff: bool = False
    # 空間退讓時，退到的外圍行政區的名稱
    backoff_area: str | None = None
    # 片段有任何一個時間維度是 `不明`
    time_unknown: bool = False


@dataclass(frozen=True)
class Available:
    """沒有證據時，問的地點有資料的時段和月份，各有幾筆（依片段的標籤計數）。"""
    time: tuple[tuple[str, int], ...] = ()
    month: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class SubQueryResult:
    sub_query: SubQuery
    evidence: list[Evidence]
    # 沒有證據時，問的地點有資料的時段和月份；有證據時為空
    available: Available = Available()
    # 子查詢的地點解析不到 OSM 物件，沒有檢索也沒有退讓；跟「地點解析得到但沒有資料」分開
    place_unresolved: bool = False


@dataclass(frozen=True)
class Group:
    """一組證據。`key` 依 group_by 的順序記錄每個維度的組名；沒有分組時是空的。"""
    key: dict[Dimension, str]
    evidence: list[Evidence]


@dataclass(frozen=True)
class Section:
    """交給生成器的一段證據：合併時全部子查詢共用一段，對照時每個子查詢一段。"""
    results: list[SubQueryResult]
    groups: list[Group]

    @property
    def evidence(self) -> list[Evidence]:
        """這段的所有證據，依分組的順序。"""
        return [e for g in self.groups for e in g.evidence]
