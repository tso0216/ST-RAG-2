"""檢索 seam 測試共用的假 embedder 和 fixture：記憶體內 SQLite，不打外部 API。"""
import textwrap

import pytest

from strag_v3.rag.hierarchy import Hierarchy
from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan
from strag_v3.rag.retrieve import Retriever


class KeywordEmbedder:
    """假的 embedding：每個關鍵字一維，文字含該字就是 1；全部沒命中時給一個共同的底。"""

    model = "fake-keyword"

    def __init__(self, keywords=("富士山", "排隊", "夕陽", "拉麵")):
        self.keywords = keywords
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0 if k in t else 0.0 for k in self.keywords] + [0.1] for t in texts]


@pytest.fixture
def embedder():
    return KeywordEmbedder()


@pytest.fixture
def add(conn):
    """塞一個片段，回傳片段 id；景點不在 place 表時順便建。"""
    def add(place="晴空塔", day_type="平日", time="10", month="1", content="排隊狀況", article="a1") -> int:
        pid = conn.execute("SELECT id FROM place WHERE name = ?", (place,)).fetchone()
        pid = pid[0] if pid else conn.execute("INSERT INTO place (name) VALUES (?)", (place,)).lastrowid
        return conn.execute(
            "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", (article, pid, place, day_type, time, month, content)).lastrowid
    return add


@pytest.fixture
def hierarchy(tmp_path):
    """把 TOML 字串寫成階層檔再載入：測試用的小型階層。"""
    def hierarchy(toml: str) -> Hierarchy:
        path = tmp_path / "hierarchy.toml"
        path.write_text(textwrap.dedent(toml))
        return Hierarchy.load(path)
    return hierarchy


@pytest.fixture
def sub():
    """一個子查詢；時間的欄位（month、day_type、time）用關鍵字給，都沒給就不限時間。"""
    def sub(space="晴空塔", aspect="排隊", **time) -> dict:
        return {"space": space, "time": time or None, "aspect": aspect}
    return sub


@pytest.fixture
def retrieve(conn, embedder, sub):
    """檢索 seam：一份檢索計畫進，分好組的證據（段的列表）出。

    沒給子查詢時用 `sub()` 的預設值；沒給 embedder 時用 `embedder` fixture 的 KeywordEmbedder。
    """
    default_embedder = embedder

    def retrieve(*sub_queries, group_by=(), compose="merge", question="排隊要多久", params=Params(),
                 hierarchy=None, embedder=None):
        plan = Plan.from_dict({"sub_queries": list(sub_queries) or [sub()],
                               "group_by": list(group_by), "compose": compose})
        return Retriever(conn, embedder or default_embedder, params, hierarchy).retrieve(plan, question)
    return retrieve
