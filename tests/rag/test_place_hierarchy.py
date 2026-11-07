"""檢索 seam：景點階層（別名、母子包含、退讓）。輸入檢索計畫，看取回哪些片段。不打外部 API。"""
import textwrap

import pytest

from strag_v3.rag.hierarchy import HIERARCHY_PATH, Hierarchy


@pytest.fixture
def hierarchy(tmp_path):
    """把 TOML 字串寫成階層檔再載入：測試用的小型階層。"""
    def hierarchy(toml: str) -> Hierarchy:
        path = tmp_path / "hierarchy.toml"
        path.write_text(textwrap.dedent(toml))
        return Hierarchy.load(path)
    return hierarchy


@pytest.fixture
def retrieve_at(retrieve, sub):
    """只有一個子查詢的計畫：回傳那個子查詢的結果，證據照分數排序。"""
    def retrieve_at(space, h, embedder=None, **time):
        [section] = retrieve(sub(space=space, **time), hierarchy=h, embedder=embedder)
        [r] = section.results
        return r
    return retrieve_at


def ids(r):
    return [e.content_id for e in r.evidence]


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


def test_alias_retrieves_canonical_place(add, retrieve_at, hierarchy):
    tower = add("東京晴空塔")
    other = add("淺草寺")

    assert ids(retrieve_at("晴空塔", hierarchy(SKYTREE))) == [tower]


def test_parent_place_includes_all_descendants(add, retrieve_at, hierarchy):
    tower = add("東京晴空塔")
    deck = add("天望甲板")  # 片段用別名
    town = add("晴空塔城")
    river = add("北十間川")
    h = hierarchy(SKYTREE)

    assert sorted(ids(retrieve_at("晴空塔", h))) == [tower, deck]
    assert sorted(ids(retrieve_at("押上", h))) == [tower, deck, town, river]


def test_backs_off_to_parent_when_nothing_passes_and_marks_backoff(add, retrieve_at, hierarchy):
    deck_may = add("天望甲板", month="5")
    tower_jan = add("東京晴空塔", month="1")
    town_jan = add("晴空塔城", month="1")
    h = hierarchy(SKYTREE)

    result = retrieve_at("天望甲板", h, month="1")

    assert ids(result) == [tower_jan]  # 只退一層：到晴空塔，不到晴空塔城
    assert all(e.backoff for e in result.evidence)


def test_no_backoff_when_place_itself_has_evidence(add, retrieve_at, hierarchy):
    deck_jan = add("天望甲板", month="1")
    tower_jan = add("東京晴空塔", month="1")

    result = retrieve_at("天望甲板", hierarchy(SKYTREE), month="1")

    assert ids(result) == [deck_jan]
    assert not any(e.backoff for e in result.evidence)


def test_empty_after_backoff_returns_no_evidence(add, retrieve_at, hierarchy):
    add("天望甲板", month="5")
    add("東京晴空塔", month="7")
    add("晴空塔城", month="1")  # 祖父節點，退讓只退一層，不會查到

    result = retrieve_at("天望甲板", hierarchy(SKYTREE), month="1")

    assert result.evidence == []


def test_empty_result_lists_closest_times_first(add, retrieve_at, hierarchy):
    add("東京晴空塔", month="7")
    add("天望甲板", month="5")
    add("天望甲板", month="5", article="a2")
    add("晴空塔城", month="1")  # 不在查過的範圍內

    result = retrieve_at("天望甲板", hierarchy(SKYTREE), month="1", day_type="平日")

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


def test_unmatched_name_resolves_to_nearest_node_by_embedding(add, retrieve_at, hierarchy):
    tower = add("東京晴空塔")
    deck = add("天望甲板")
    town = add("晴空塔城")
    h = hierarchy(SKYTREE)

    # 「晴空塔展望台」不是任何別名；字最像的名稱是「晴空塔」，對到東京晴空塔節點（含子節點天望甲板）
    result = retrieve_at("晴空塔展望台", h, embedder=CharEmbedder())

    assert sorted(ids(result)) == [tower, deck]


def test_place_missing_from_hierarchy_still_matches_its_own_name(add, retrieve_at, hierarchy):
    tower = add("東京晴空塔")
    mall = add("晴空塔商場")  # 重新抽取後才出現、階層檔還沒收的景點

    result = retrieve_at("晴空塔商場", hierarchy(SKYTREE), embedder=CharEmbedder())

    assert ids(result) == [mall]


def test_name_unlike_any_node_is_not_forced_onto_one(add, retrieve_at, hierarchy):
    add("晴空塔城")  # 跟「大阪城」只共用一個字

    result = retrieve_at("大阪城", hierarchy(SKYTREE), embedder=CharEmbedder())

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
def test_shipped_hierarchy_merges_aliases_and_includes_children(add, retrieve_at, asked, stored):
    content = add(stored)
    add("清水寺")

    assert ids(retrieve_at(asked, Hierarchy.load(HIERARCHY_PATH))) == [content]


def test_stored_place_spelled_with_extra_space_still_matches(add, retrieve_at, hierarchy):
    tower = add("東京 晴空塔")

    assert ids(retrieve_at("晴空塔", hierarchy(SKYTREE))) == [tower]
