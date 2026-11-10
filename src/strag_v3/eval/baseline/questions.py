"""讀 ptt_v2 題目和校準用的反向答案。

一題的標註（規則見 `.scratch/ptt-v2-questions/generate.md`）：問題、時間條件 `when`、地點 `space`、
標準片段 `relevant_contents`、標準文章 `relevant_articles`、排除片段與理由 `excluded`、
重點 `expect` 和每條重點的出處 `expect_sources`；找時間題另有 `asks`，比較題另有 `options`（每個選項的地點和時間條件）。
"""
import json
from dataclasses import dataclass
from pathlib import Path

from ...rag.plan import parse_time
from ...rag.timematch import TimeQuery

PTT_V2 = Path(__file__).resolve().parents[1] / "questions" / "ptt_v2"
# 題目檔的順序，也是報表裡題型的順序
FILES = ("stay", "move", "find_place", "find_time", "compare")
TIME_UNKNOWN = "時間不明"


@dataclass(frozen=True)
class Option:
    """比較題的一個選項。"""
    label: str
    when: TimeQuery | None
    relevant: tuple[int, ...]


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    question: str
    # 題目的時間條件；None 是不限時間
    when: TimeQuery | None
    relevant: tuple[int, ...]
    articles: tuple[str, ...]
    # 排除的片段 id → 理由碼（無關、別處、時間矛盾、時間不明）
    excluded: dict[int, str]
    expect: tuple[str, ...]
    # 每條重點的出處：片段 id → 原句；揭露條是空的
    expect_sources: tuple[dict[int, str], ...] = ()
    options: tuple[Option, ...] = ()
    asks: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(
            id=d["id"], type=d["type"], question=d["question"], when=parse_time(d.get("when")),
            relevant=tuple(d["relevant_contents"]), articles=tuple(d["relevant_articles"]),
            excluded={int(k): v for k, v in d.get("excluded", {}).items()},
            expect=tuple(d["expect"]),
            expect_sources=tuple({int(k): v for k, v in s.items()} for s in d.get("expect_sources", [])),
            options=tuple(Option(o["label"], parse_time(o.get("when")), tuple(o["relevant_contents"]))
                          for o in d.get("options", [])),
            asks=d.get("asks"),
        )

    @property
    def time_unknown(self) -> frozenset[int]:
        """標註為「時間不明」的排除片段：不計分，答案引用它也不算無支持。"""
        return frozenset(i for i, why in self.excluded.items() if why == TIME_UNKNOWN)

    @property
    def time_conditions(self) -> tuple[TimeQuery | None, ...]:
        """片段要符合其中一個才不算時間違規：比較題是各選項的時間條件，其他題是 `when`。"""
        return tuple(o.when for o in self.options) if self.options else (self.when,)


def load_questions(folder: Path = PTT_V2) -> list[Question]:
    return [Question.from_dict(q) for name in FILES for q in json.loads((folder / f"{name}.json").read_text())["questions"]]


def load_negatives(folder: Path = PTT_V2) -> dict[str, str]:
    """校準檔：題目 id → 反向答案（每題一個）。"""
    out: dict[str, str] = {}
    for name in FILES:
        out |= json.loads((folder / "calibration" / f"{name}.json").read_text())
    return out
