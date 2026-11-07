"""檢索 seam：景點階層（別名、母子包含、退讓）。輸入檢索計畫，看取回哪些片段。不打外部 API。"""
import pytest

from strag_v3.rag.hierarchy import HIERARCHY_PATH, Hierarchy
from strag_v3.rag.timedist import TimeSpec


@pytest.fixture
def retrieve_at(retrieve, sub):
    """只有一個子查詢的計畫：回傳那個子查詢的結果，證據照分數排序。"""
    def retrieve_at(space, h, **time):
        [section] = retrieve(sub(space=space, **time), hierarchy=h)
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

    assert [(s.place, s.time, s.count) for s in result.nearest] == [
        ("天望甲板", TimeSpec("5", "平日", "10"), 2),
        ("東京晴空塔", TimeSpec("7", "平日", "10"), 1),
    ]


def test_name_matching_no_alias_retrieves_nothing(add, retrieve_at, hierarchy):
    add("東京晴空塔")
    add("天望甲板")
    add("晴空塔城")

    # 「晴空塔展望台」不是任何節點的名稱或別名：不猜最像的節點，當作階層裡沒有這個地點
    result = retrieve_at("晴空塔展望台", hierarchy(SKYTREE))

    assert result.evidence == []
    assert result.nearest == ()


def test_place_missing_from_hierarchy_still_matches_its_own_name(add, retrieve_at, hierarchy):
    add("東京晴空塔")
    mall = add("晴空塔商場")  # 重新抽取後才出現、階層檔還沒收的景點

    result = retrieve_at("晴空塔商場", hierarchy(SKYTREE))

    assert ids(result) == [mall]


def test_canonical_name_retrieves_content_stored_under_alias(add, retrieve_at, hierarchy):
    town = add("晴空塔城")
    tower = add("東京晴空塔")

    assert ids(retrieve_at("東京晴空塔城", hierarchy(SKYTREE))) == [town, tower]


def test_shipped_hierarchy_file_is_well_formed():
    """正式的階層檔只檢查結構：能載入、每個母節點都存在、沒有循環。內容由研究者審稿，不在這裡檢查。"""
    h = Hierarchy.load(HIERARCHY_PATH)

    assert h.nodes
    for node in h.nodes.values():
        seen = {node.name}
        parent = node.parent
        while parent:
            assert parent in h.nodes, f"{node.name} 的母節點「{parent}」不在階層檔裡"
            assert parent not in seen, f"{node.name} 的母子關係繞成循環"
            seen.add(parent)
            parent = h.nodes[parent].parent


def test_stored_place_spelled_with_extra_space_still_matches(add, retrieve_at, hierarchy):
    tower = add("東京 晴空塔")

    assert ids(retrieve_at("晴空塔", hierarchy(SKYTREE))) == [tower]
