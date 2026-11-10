"""原文段：`dense_raw` 用的語料。遊記原文切出來的一段文字，跟片段（抽取出來、帶地點和時間標籤的經驗）是兩回事。

- 語料：DB 裡有片段的遊記（目前 248 篇），原文在 `.archive/ptt_article/ptt_<文章 id>.json`。
- 切法（`split_article`）：內文以空行分段，推文一則一行，接在內文後面。依序把段落塞進原文段，
  超過約 500 字就換下一段；下一段開頭重複上一段最後 100 字。單一段落超過 500 字時先切成 500 字一塊。
- 存放：baseline 自己的 `chunks.db`（可重建的衍生資料，不進版控），`chunk` 表放原文段，
  `embedding` 表放 baseline 用到的所有 embedding（原文段、片段、問題），以（模型, 文字）為鍵，算過就不重算。
"""
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ...rag.embedding import Embedder, cosine

CHUNKS_DB = Path(__file__).resolve().parent / "chunks.db"
ARTICLES = Path(__file__).resolve().parents[4] / ".archive" / "ptt_article"
SIZE = 500
OVERLAP = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk (
    id         INTEGER PRIMARY KEY,
    article_id TEXT    NOT NULL,
    seq        INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    UNIQUE (article_id, seq)
)
"""


def _units(article: dict, size: int) -> list[str]:
    """內文的段落和每則推文；超過 size 的段落切成 size 一塊。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", article.get("text") or "") if p.strip()]
    paras += [f"{c.get('tag', '')} {c.get('user', '')}：{c.get('content', '')}".strip()
              for c in article.get("comments") or [] if (c.get("content") or "").strip()]
    return [p[i:i + size] for p in paras for i in range(0, len(p), size)]


def split_article(article: dict, size: int = SIZE, overlap: int = OVERLAP) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for u in _units(article, size):
        if cur and len(cur) + 1 + len(u) > size:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n" + u
        else:
            cur = f"{cur}\n{u}" if cur else u
    if cur:
        chunks.append(cur)
    return chunks


@dataclass(frozen=True)
class Chunk:
    id: int
    article_id: str
    text: str


def connect(path: Path = CHUNKS_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def build(conn: sqlite3.Connection, embedder: Embedder, article_ids: list[str], folder: Path = ARTICLES) -> int:
    """重建 chunk 表並算好每個原文段的 embedding；回傳原文段數。缺原文時丟 FileNotFoundError，不寫任何東西。"""
    missing = [a for a in article_ids if not (folder / f"{a}.json").is_file()]
    if missing:
        raise FileNotFoundError(f"缺 {len(missing)} 篇原文：{'、'.join(missing)}")
    rows = [(a, i, text) for a in sorted(article_ids)
            for i, text in enumerate(split_article(json.loads((folder / f"{a}.json").read_text())))]
    embedder.embed([t for *_, t in rows])
    with conn:
        conn.execute("DELETE FROM chunk")
        conn.executemany("INSERT INTO chunk (article_id, seq, text) VALUES (?, ?, ?)", rows)
    return len(rows)


def load_chunks(conn: sqlite3.Connection) -> list[Chunk]:
    return [Chunk(*r) for r in conn.execute("SELECT id, article_id, text FROM chunk ORDER BY id")]


def chunk_top_k(embedder: Embedder, question: str, chunks: list[Chunk], k: int) -> list[tuple[float, Chunk]]:
    """原問題跟所有原文段的 cosine，取 top-k；同分時 id 小的在前。"""
    if not chunks:
        return []
    qvec, *cvecs = embedder.embed([question] + [c.text for c in chunks])
    return sorted(((cosine(qvec, v), c) for c, v in zip(chunks, cvecs)), key=lambda x: (-x[0], x[1].id))[:k]
