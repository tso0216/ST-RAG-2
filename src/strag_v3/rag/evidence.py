"""檢索的輸出：每筆證據、每個子查詢的結果，以及交給生成器的段和分組。"""
from dataclasses import dataclass

from .nearest import NearestTime
from .plan import Dimension, SubQuery
from .timedist import TimeSpec


@dataclass(frozen=True)
class Evidence:
    content_id: int
    article_id: str
    place: str
    time: TimeSpec
    content: str
    overlap: float
    semantic: float
    score: float
    # 時間相符程度（見 timedist.time_match）：1 是完全落在子查詢的時間範圍內，0 是完全在範圍外
    time_match: float
    backoff: bool = False


@dataclass(frozen=True)
class SubQueryResult:
    sub_query: SubQuery
    evidence: list[Evidence]
    # 沒有證據時，查過的範圍裡最接近問題時間的時段；有證據時為空
    nearest: tuple[NearestTime, ...] = ()


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
