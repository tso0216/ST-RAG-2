"""檢索 seam：景點階層（別名、母子包含、退讓）。輸入檢索計畫，看取回哪些片段。不打外部 API。"""
import textwrap

import pytest

from strag_v3.rag.hierarchy import HIERARCHY_PATH, Hierarchy
from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan
from strag_v3.rag.retrieve import Retriever


class KeywordEmbedder:
    """假的 embedding：每個關鍵字一維，文字含該字就是 1；全部沒命中時給一個共同的底。"""

    model = "fake-keyword"

    def __init__(self, keywords=("富士山", "排隊", "夕陽", "拉麵")):
        self.keywords = keywords

    def embed(self, texts):
        return [[1.0 if k in t else 0.0 for k in self.keywords] + [0.1] for t in texts]


def add(conn, place, day_type="平日", time="10", month="1", content="排隊狀況", article="a1"):
    pid = conn.execute("SELECT id FROM place WHERE name = ?", (place,)).fetchone()
    pid = pid[0] if pid else conn.execute("INSERT INTO place (name) VALUES (?)", (place,)).lastrowid
    return conn.execute(
        "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)", (article, pid, place, day_type, time, month, content)).lastrowid


def plan(space, aspect="排隊", **time):
    return Plan.from_dict({"sub_queries": [{"space": space, "time": time or None, "aspect": aspect}]})


def hierarchy(tmp_path, toml: str) -> Hierarchy:
    path = tmp_path / "hierarchy.toml"
    path.write_text(textwrap.dedent(toml))
    return Hierarchy.load(path)


def retrieve(conn, p, h, embedder=None, params=Params()):
    [result] = Retriever(conn, embedder or KeywordEmbedder(), params, hierarchy=h).retrieve(p, "排隊要多久")
    return result


def ids(result):
    return [e.content_id for e in result.evidence]


SKYTREE = """
    [[node]]
    name = "押上"
    kind = "區域"

    [[node]]
    name = "東京晴空塔城"
    aliases = ["晴空塔城"]
    parent = "押上"

    [[node]]
    name = "東京晴空塔"
    aliases = ["晴空塔"]
    parent = "東京晴空塔城"

    [[node]]
    name = "東京晴空塔天望甲板"
    aliases = ["天望甲板"]
    parent = "東京晴空塔"

    [[node]]
    name = "北十間川"
    parent = "押上"
"""


def test_alias_retrieves_canonical_place(conn, tmp_path):
    tower = add(conn, "東京晴空塔")
    other = add(conn, "淺草寺")

    assert ids(retrieve(conn, plan("晴空塔"), hierarchy(tmp_path, SKYTREE))) == [tower]


def test_parent_place_includes_all_descendants(conn, tmp_path):
    tower = add(conn, "東京晴空塔")
    deck = add(conn, "天望甲板")  # 片段用別名
    town = add(conn, "晴空塔城")
    river = add(conn, "北十間川")
    h = hierarchy(tmp_path, SKYTREE)

    assert sorted(ids(retrieve(conn, plan("晴空塔"), h))) == [tower, deck]
    assert sorted(ids(retrieve(conn, plan("押上"), h))) == [tower, deck, town, river]


def test_backs_off_to_parent_when_nothing_passes_and_marks_backoff(conn, tmp_path):
    deck_may = add(conn, "天望甲板", month="5")
    tower_jan = add(conn, "東京晴空塔", month="1")
    town_jan = add(conn, "晴空塔城", month="1")
    h = hierarchy(tmp_path, SKYTREE)

    result = retrieve(conn, plan("天望甲板", month="1"), h)

    assert ids(result) == [tower_jan]  # 只退一層：到晴空塔，不到晴空塔城
    assert all(e.backoff for e in result.evidence)


def test_no_backoff_when_place_itself_has_evidence(conn, tmp_path):
    deck_jan = add(conn, "天望甲板", month="1")
    tower_jan = add(conn, "東京晴空塔", month="1")

    result = retrieve(conn, plan("天望甲板", month="1"), hierarchy(tmp_path, SKYTREE))

    assert ids(result) == [deck_jan]
    assert not any(e.backoff for e in result.evidence)


def test_empty_after_backoff_returns_no_evidence(conn, tmp_path):
    add(conn, "天望甲板", month="5")
    add(conn, "東京晴空塔", month="7")
    add(conn, "晴空塔城", month="1")  # 祖父節點，退讓只退一層，不會查到

    result = retrieve(conn, plan("天望甲板", month="1"), hierarchy(tmp_path, SKYTREE))

    assert result.evidence == []


def test_empty_result_lists_closest_times_first(conn, tmp_path):
    add(conn, "東京晴空塔", month="7")
    add(conn, "天望甲板", month="5")
    add(conn, "天望甲板", month="5", article="a2")
    add(conn, "晴空塔城", month="1")  # 不在查過的範圍內

    result = retrieve(conn, plan("天望甲板", month="1", day_type="平日"), hierarchy(tmp_path, SKYTREE))

    assert [(s.place, s.month, s.day_type, s.time, s.count) for s in result.nearest] == [
        ("天望甲板", "5", "平日", "10", 2),
        ("東京晴空塔", "7", "平日", "10", 1),
    ]


class CharEmbedder:
    """假的 embedding：每個字一維（字數），名稱共用的字越多越接近。"""

    model = "fake-char"

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 4096
            for ch in t:
                v[ord(ch) % 4096] += 1.0
            out.append(v)
        return out


def test_unmatched_name_resolves_to_nearest_node_by_embedding(conn, tmp_path):
    tower = add(conn, "東京晴空塔")
    deck = add(conn, "天望甲板")
    town = add(conn, "晴空塔城")
    h = hierarchy(tmp_path, SKYTREE)

    # 「晴空塔展望台」不是任何別名；字最像的名稱是「晴空塔」，對到東京晴空塔節點（含子節點天望甲板）
    result = retrieve(conn, plan("晴空塔展望台"), h, embedder=CharEmbedder())

    assert sorted(ids(result)) == [tower, deck]


def test_place_missing_from_hierarchy_still_matches_its_own_name(conn, tmp_path):
    tower = add(conn, "東京晴空塔")
    mall = add(conn, "晴空塔商場")  # 重新抽取後才出現、階層檔還沒收的景點

    result = retrieve(conn, plan("晴空塔商場"), hierarchy(tmp_path, SKYTREE), embedder=CharEmbedder())

    assert ids(result) == [mall]


def test_name_unlike_any_node_is_not_forced_onto_one(conn, tmp_path):
    add(conn, "晴空塔城")  # 跟「大阪城」只共用一個字

    result = retrieve(conn, plan("大阪城"), hierarchy(tmp_path, SKYTREE), embedder=CharEmbedder())

    assert result.evidence == []
    assert result.nearest == ()


@pytest.mark.parametrize("asked, stored", [
    ("晴空塔城", "東京晴空塔城"),
    ("東京晴空塔城", "晴空塔城"),
    ("雷門", "淺草寺雷門"),
    ("淺草寺雷門", "雷門"),
    ("嵐山竹林", "嵐山竹林小徑"),
    ("嵐山竹林小徑", "嵐山竹林"),
    ("晴空塔", "東京晴空塔天望甲板"),  # 天望甲板屬於晴空塔
    ("押上", "東京晴空塔"),
    ("淺草", "淺草寺"),
])
def test_shipped_hierarchy_merges_aliases_and_includes_children(conn, asked, stored):
    content = add(conn, stored)
    add(conn, "清水寺")

    assert ids(retrieve(conn, plan(asked), Hierarchy.load(HIERARCHY_PATH))) == [content]


def test_stored_place_spelled_with_extra_space_still_matches(conn, tmp_path):
    tower = add(conn, "東京 晴空塔")

    assert ids(retrieve(conn, plan("晴空塔"), hierarchy(tmp_path, SKYTREE))) == [tower]
