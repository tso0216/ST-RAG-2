"""檢索 seam：地點解析（OSM 物件、區域範圍、快取）。輸入檢索計畫，看取回哪些片段。不打外部 API。退讓見 test_backoff.py。"""
import pytest

from strag_v3.place import AREA, SPOT, PlaceError, Places
from strag_v3.rag.params import Params
from strag_v3.rag.plan import Plan, PlanError
from strag_v3.rag.retrieve import Retriever

NO_BACKOFF = Params(time_backoff=False, space_backoff=False)


@pytest.fixture
def ids_at(retrieve, sub):
    """只有一個子查詢、不退讓的計畫：回傳取回的片段 id。"""
    def ids_at(space, kind=SPOT, **time):
        [section] = retrieve(sub(space=space, kind=kind, **time), params=NO_BACKOFF)
        return sorted(e.content_id for e in section.evidence)
    return ids_at


def test_spellings_resolving_to_one_osm_object_retrieve_the_same_content(add, ids_at):
    tower = add("東京晴空塔")
    tower_ja = add("東京スカイツリー", article="a2")
    town = add("晴空塔城")

    assert ids_at("晴空塔") == ids_at("スカイツリー") == ids_at("東京スカイツリー") == [tower, tower_ja]


def test_place_that_does_not_resolve_retrieves_nothing(add, ids_at):
    add("晴空塔")

    assert ids_at("晴空塔展望台") == []


def test_area_query_does_not_resolve_to_a_spot(add, ids_at):
    add("晴空塔")

    assert ids_at("晴空塔", kind=AREA) == []


def test_area_takes_its_own_content_and_every_place_inside(add, ids_at):
    own = add("押上", kind=AREA)
    block = add("押上一丁目", kind=AREA)   # 範圍裡的小區域
    tower = add("晴空塔")
    river = add("北十間川")
    city = add("墨田区", kind=AREA)        # 外面那層區域本身
    flower = add("向島百花園")             # 同一個區、押上外
    temple = add("淺草寺")

    assert ids_at("押上", kind=AREA) == [own, block, tower, river]


def test_area_crowded_out_by_roads_is_found_by_a_settlement_only_retry(add, ids_at):
    ward = add("東山区", kind=AREA)

    assert ids_at("東山区", kind=AREA) == [ward]


def test_spot_query_leaves_out_the_content_of_the_area_it_sits_in(add, ids_at):
    block = add("押上一丁目", kind=AREA)
    area = add("押上", kind=AREA)
    tower = add("晴空塔")

    assert ids_at("晴空塔") == [tower]


def test_rerun_reads_resolution_from_the_cache_without_calling_nominatim(conn, add, sub, nominatim, embedder):
    tower = add("晴空塔")
    area = add("押上", kind=AREA)
    plan = Plan.from_dict({"sub_queries": [sub(space="晴空塔"), sub(space="押上", kind=AREA)]})
    first = Retriever(conn, embedder, NO_BACKOFF, nominatim).retrieve(plan, "排隊")
    calls = len(nominatim.calls)

    again = Retriever(conn, embedder, NO_BACKOFF, nominatim=None).retrieve(plan, "排隊")

    assert len(nominatim.calls) == calls
    assert [e.content_id for e in again[0].evidence] == [e.content_id for e in first[0].evidence] == [tower, area]


def test_new_place_without_nominatim_is_an_error_not_an_empty_result(conn, sub, embedder):
    plan = Plan.from_dict({"sub_queries": [sub(space="晴空塔")]})

    with pytest.raises(PlaceError):
        Retriever(conn, embedder, NO_BACKOFF, nominatim=None).retrieve(plan, "排隊")


def test_failed_resolution_is_cached_too(add, ids_at, nominatim):
    add("晴空塔")
    ids_at("晴空塔展望台")
    calls = len(nominatim.calls)

    assert ids_at("晴空塔展望台") == []
    assert len(nominatim.calls) == calls


@pytest.mark.parametrize("space", ["晴空塔", {"name": "晴空塔", "city": "東京", "kind": "景點"},
                                   {"name_ja": "スカイツリー", "city": "東京", "kind": "附近"}])
def test_plan_rejects_space_outside_the_format(space):
    with pytest.raises(PlanError):
        Plan.from_dict({"sub_queries": [{"space": space, "time": None, "aspect": None}]})


def test_question_written_as_an_alias_retrieves_the_target(conn, add, ids_at, nominatim):
    park = add("上野恩賜公園")
    Places(conn, nominatim).add_alias("上野公園", "上野恩賜公園", "東京", SPOT)

    assert ids_at("上野公園") == [park]


def test_alias_to_a_place_that_does_not_resolve_is_an_error(conn, nominatim):
    with pytest.raises(PlaceError):
        Places(conn, nominatim).add_alias("晴空塔展望台", "スカイツリー展望台", "東京", SPOT)
