"""題目檔：`data/questions/ptt/<題型>.json`，一個題型一個檔。

`type`（停留經驗、找時間、找地點、比較、移動經驗）和 `split`（dev、test）只用於分組，系統不讀；舊的題目檔沒有這兩個欄位也能跑。
沒有 `relevant_contents` 的題目（還沒標註）照跑，只是不算 recall、precision、F1。
`excluded` 裡理由是「時間不明」的片段（內容相關，但題目限定的時間說不準）不計分，見 `metrics.py`。
"""
import json
from dataclasses import dataclass
from pathlib import Path

from ..rag.plan import parse_time
from ..rag.timematch import LabelError, TimeQuery

SPLITS = ("dev", "test")
# 題目檔 `excluded` 裡，標成這個理由的片段不計分
UNSCORED_REASON = "時間不明"


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
    # 不計分的片段：撈到不算誤撈，沒撈到也不算漏撈（它們不在 relevant 裡）
    unscored: frozenset[int] = frozenset()


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
        unscored = frozenset(int(i) for i, why in (d.get("excluded") or {}).items() if why == UNSCORED_REASON)
        if rel is not None and (both := unscored.intersection(int(i) for i in rel)):
            raise QuestionError(f"{key} 的片段 {sorted(both)} 同時在 relevant_contents 和不計分（{UNSCORED_REASON}）裡")
        out.append(Question(
            key=key,
            question=d["question"],
            when=when,
            relevant=None if rel is None else frozenset(int(i) for i in rel),
            type=d.get("type"),
            split=split,
            expect=tuple(d.get("expect") or ()),
            when_raw=d.get("when"),
            unscored=unscored,
        ))
    return out
