"""Embedding：文字列表進、向量列表出。

所有呼叫都走 `Embedder` 介面，測試時換成假的實作。
`CachedEmbedder` 把結果存在 DB 的 `embedding` 表，以（模型, 文字）為鍵，同樣的組合不會再呼叫 API。
"""
import array
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Protocol

OPENAI_MODEL = "text-embedding-3-large"
OPENAI_URL = "https://api.openai.com/v1/embeddings"


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """OpenAI embeddings API；API key 從環境變數 `OPENAI_API_KEY` 讀取。"""

    def __init__(self, model: str = OPENAI_MODEL, batch_size: int = 128, retries: int = 5):
        self.model = model
        self.batch_size = batch_size
        self.retries = retries

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out += self._request(texts[i:i + self.batch_size])
        return out

    def _request(self, texts: list[str]) -> list[list[float]]:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EmbeddingError("沒有設定環境變數 OPENAI_API_KEY")
        body = json.dumps({"model": self.model, "input": texts}).encode()
        for attempt in range(1, self.retries + 1):
            req = urllib.request.Request(OPENAI_URL, data=body, headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.load(r)["data"]
                return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                if e.code != 429 and e.code < 500 or attempt == self.retries:
                    raise EmbeddingError(f"OpenAI HTTP {e.code}: {detail}") from None
            except urllib.error.URLError as e:
                if attempt == self.retries:
                    raise EmbeddingError(f"OpenAI 連線失敗：{e.reason}") from None
            time.sleep(2 ** attempt)
        raise EmbeddingError("OpenAI 重試失敗")


CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding (
    model  TEXT NOT NULL,
    text   TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (model, text)
)
"""


class CachedEmbedder:
    """包住另一個 Embedder，結果快取在 SQLite（float32）。"""

    def __init__(self, inner: Embedder, conn: sqlite3.Connection):
        self.inner = inner
        self.model = inner.model
        self.conn = conn
        conn.execute(CACHE_SCHEMA)

    def embed(self, texts: list[str]) -> list[list[float]]:
        found: dict[str, list[float]] = {}
        for t in set(texts):
            row = self.conn.execute(
                "SELECT vector FROM embedding WHERE model = ? AND text = ?", (self.model, t)).fetchone()
            if row:
                found[t] = array.array("f", row[0]).tolist()
        missing = sorted(set(texts) - found.keys())
        if missing:
            vectors = self.inner.embed(missing)
            with self.conn:
                for t, v in zip(missing, vectors):
                    packed = array.array("f", v)  # 第一次和之後讀快取都回傳同樣的 float32 值
                    self.conn.execute("INSERT OR REPLACE INTO embedding (model, text, vector) VALUES (?, ?, ?)",
                                      (self.model, t, packed.tobytes()))
                    found[t] = packed.tolist()
        return [found[t] for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
