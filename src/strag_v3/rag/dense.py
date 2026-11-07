"""Dense retrieval baseline：不看計畫、時間和地點，只用原問題跟片段內容的語意分數取 top-k。

輸出跟檢索模組同一個形狀（一段、不分組），生成器和評估可以直接沿用。
baseline 不知道時間條件，所以證據不會有退讓標記；時間不明照片段的標籤標記。
"""
import sqlite3

from .embedding import Embedder, cosine
from .evidence import Evidence, Group, Section, SubQueryResult
from .plan import SubQuery
from .store import contents


def dense_retrieve(conn: sqlite3.Connection, embedder: Embedder, question: str, k: int) -> list[Section]:
    pool = contents(conn, None)
    if not pool:
        return [Section([SubQueryResult(SubQuery(), [])], [])]
    qvec, *cvecs = embedder.embed([question] + [c.text for c in pool])
    scored = sorted(((cosine(qvec, v), c) for c, v in zip(pool, cvecs)), key=lambda x: (-x[0], x[1].id))
    evidence = [Evidence(c.id, c.article_id, c.place_id, c.place, c.time, c.text, semantic=sem, score=sem,
                         time_unknown=c.time.unknown)
                for sem, c in scored[:k]]
    return [Section([SubQueryResult(SubQuery(), evidence)], [Group({}, evidence)] if evidence else [])]
