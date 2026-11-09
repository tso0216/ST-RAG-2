"""檢索 seam 測試共用的假 embedder、假 Nominatim、假 JEV 和 fixture：記憶體內 SQLite，不打外部 API。"""
import asyncio

import pytest
from service.jev import JEVClient

from strag_v3.place import SPOT, Places
from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan
from strag_v3.rag.retrieve import Retriever
from tests.fake_nominatim import FakeNominatim
from tests.fake_typesafe import FakeTypeSafe


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
def nominatim():
    return FakeNominatim()


@pytest.fixture
def embedder():
    return KeywordEmbedder()


@pytest.fixture
def typesafe():
    """假的 TypeSafe client；測試可以改它的 `nouls`、`fail`，或看 `calls`。"""
    return FakeTypeSafe()


@pytest.fixture
def jev(typesafe):
    return JEVClient(typesafe)


@pytest.fixture
def add(conn, nominatim):
    """塞一個片段，回傳片段 id。地點用假 Nominatim 解析，name_zh 記成第一次給的寫法。"""
    places = Places(conn, nominatim)

    def add(place="晴空塔", day_type="平日", time="早上", month="1", content="排隊狀況", article="a1",
            kind=SPOT) -> int:
        p = places.resolve(place, "東京", kind, name_zh=place)
        assert p is not None, f"假世界裡沒有「{place}」"
        return conn.execute(
            "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", (article, p.id, place, day_type, time, month, content)).lastrowid
    return add


@pytest.fixture
def sub():
    """一個子查詢；時間的欄位（month、day_type、time）用關鍵字給，都沒給就不限時間。

    space 給地點的寫法（同時當繁中名稱和日文名稱），kind 給景點或區域；space=None 不限地點。
    month 和 time 可以給一個值或一組值的列表，跟規劃器的寫法相同。
    """
    def sub(space="晴空塔", aspect="排隊", kind=SPOT, **time) -> dict:
        s = None if space is None else {"name": space, "name_ja": space, "city": "東京", "kind": kind}
        return {"space": s, "time": time or None, "aspect": aspect}
    return sub


@pytest.fixture
def retrieve(conn, embedder, nominatim, jev, sub):
    """檢索 seam：一份檢索計畫進，分好組的證據（段的列表）出。

    沒給子查詢時用 `sub()` 的預設值；沒給 embedder 時用 `embedder` fixture 的 KeywordEmbedder；
    JEV 用 `typesafe` fixture 的假 client。
    """
    default_embedder = embedder

    def retrieve(*sub_queries, group_by=(), compose="merge", question="排隊要多久", params=Params(), embedder=None):
        plan = Plan.from_dict({"sub_queries": list(sub_queries) or [sub()],
                               "group_by": list(group_by), "compose": compose})
        retriever = Retriever(conn, embedder or default_embedder, params, nominatim, jev=jev)
        return asyncio.run(retriever.retrieve(plan, question))
    return retrieve

