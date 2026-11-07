"""題目檔：`data/mock_article/eval/<地點>_questions.json`，格式見 `data/mock_article/README.md`。

`type`（停留、找時間、找地點、比較）和 `split`（dev、test）只用於分組，系統不讀；舊的題目檔沒有這兩個欄位也能跑。
沒有 `relevant_contents` 的題目（還沒標註）照跑，只是不算 recall、precision、F1。
"""
import json
from dataclasses import dataclass
from pathlib import Path

from ..rag.plan import parse_time
from ..rag.timematch import LabelError, TimeQuery

SPLITS = ("dev", "test")


class QuestionError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    # `<題目檔名去掉 _questions>/<題目 id>`，跨檔唯一
    key: str
    question: str
    # 題目限定的時間條件；沒有 `when` 或三個維度都沒填時是 None（不限時間）
    when: TimeQuery | None
    # 回答需要的片段 id；題目檔沒有這個欄位時是 None（還沒標註）
    relevant: frozenset[int] | None
    type: str | None = None
    split: str | None = None
    expect: tuple[str, ...] = ()
    # 題目檔裡的原始 `when`，存進結果檔方便對照
    when_raw: dict | None = None


def load_questions(path: Path) -> list[Question]:
    """題目檔，或資料夾裡所有的 `*.json`（依檔名排序）。"""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise QuestionError(f"{path} 裡沒有題目檔")
    out: list[Question] = []
    for f in files:
        out += _load_file(f)
    keys = [q.key for q in out]
    if dupes := sorted({k for k in keys if keys.count(k) > 1}):
        raise QuestionError(f"題目 id 重複：{'、'.join(dupes)}")
    return out


def _load_file(f: Path) -> list[Question]:
    prefix = f.stem.removesuffix("_questions")
    data = json.loads(f.read_text())
    out = []
    for d in data.get("questions") or []:
        key = f"{prefix}/{d['id']}"
        try:
            when = parse_time(d.get("when"))
        except LabelError as e:
            raise QuestionError(f"{key} 的 when：{e}") from None
        split = d.get("split")
        if split is not None and split not in SPLITS:
            raise QuestionError(f"{key} 的 split 只能是 {'、'.join(SPLITS)}，不是「{split}」")
        rel = d.get("relevant_contents")
        out.append(Question(
            key=key,
            question=d["question"],
            when=when,
            relevant=None if rel is None else frozenset(int(i) for i in rel),
            type=d.get("type"),
            split=split,
            expect=tuple(d.get("expect") or ()),
            when_raw=d.get("when"),
        ))
    return out
