"""片段的 dense 檢索：`dense_frag` 和 `dense_filter` 共用。

- `dense_top_k`：原問題跟片段內容的 embedding cosine，取 top-k，不看時間和地點（`dense_frag`）。
- `filter_top_k`（`dense_filter`）：LLM 從問題產生的一組或多組過濾條件，每組先過濾片段再取 cosine top-k，
  多組各取 top-k 後合併。
  - 地點：過濾條件的地點名稱（繁中、日文）包含在片段的任一個地點名稱裡就算符合。只做字串比對，
    不經 Nominatim、不展開區域（問押上不會取到十間橋）。
  - 時間：跟主系統相同的比對規則（`TimeQuery.matches`），片段標成不明的維度算符合。
  - 沒有相關判斷，沒有時間退讓和空間退讓。
"""
import unicodedata
from dataclasses import dataclass

from ...rag.embedding import Embedder, cosine
from ...rag.plan import parse_time
from ...rag.timematch import TimeQuery
from .fragments import Fragment

Scored = tuple[float, Fragment]


def dense_top_k(embedder: Embedder, question: str, pool: list[Fragment], k: int) -> list[Scored]:
    """依分數由高到低；同分時片段 id 小的在前。"""
    if not pool:
        return []
    qvec, *cvecs = embedder.embed([question] + [f.text for f in pool])
    scored = sorted(((cosine(qvec, v), f) for f, v in zip(pool, cvecs)), key=lambda x: (-x[0], x[1].id))
    return scored[:k]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace(" ", "").lower()


@dataclass(frozen=True)
class Filter:
    # 地點的寫法（繁中、日文）；空的代表不限地點
    names: tuple[str, ...]
    time: TimeQuery | None

    @classmethod
    def from_dict(cls, d: dict) -> "Filter":
        """LLM 輸出的一組條件：{place: {name, name_ja} | null, month, day_type, time}。看不懂的時間標籤丟 LabelError。"""
        place = d.get("place") or {}
        names = tuple(dict.fromkeys(n.strip() for n in (place.get("name"), place.get("name_ja")) if n and n.strip()))
        return cls(names, parse_time({k: d.get(k) for k in ("month", "day_type", "time")}))

    def place_matches(self, f: Fragment) -> bool:
        return not self.names or any(_norm(n) in _norm(m) for n in self.names for m in f.names)

    def matches(self, f: Fragment) -> bool:
        return self.place_matches(f) and (self.time is None or self.time.matches(f.time))


def filter_top_k(embedder: Embedder, question: str, pool: list[Fragment], filters: list[Filter],
                 k: int) -> tuple[list[Scored], bool]:
    """回傳合併後的片段（依分數排序，重複的只留一次），和有沒有哪組的地點對不到任何片段。"""
    merged: dict[int, Scored] = {}
    unmatched = False
    for flt in filters:
        if flt.names and not any(flt.place_matches(f) for f in pool):
            unmatched = True
        for score, f in dense_top_k(embedder, question, [f for f in pool if flt.matches(f)], k):
            merged.setdefault(f.id, (score, f))
    return sorted(merged.values(), key=lambda x: (-x[0], x[1].id)), unmatched
