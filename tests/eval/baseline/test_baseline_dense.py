"""dense_frag 和 dense_filter 的檢索：片段和過濾條件進，取回的片段出。假 embedder，不打外部 API。"""
from strag_v3.eval.baseline.dense import Filter, dense_top_k, filter_top_k
from tests.eval.baseline.conftest import frag


def ids(scored):
    return [f.id for _, f in scored]


def test_dense_takes_top_k_by_semantic_score_ignoring_time_and_place(embedder):
    pool = [frag(1, text="甲板很冷"), frag(2, month="8", time="晚上", text="富士山很清楚"),
            frag(3, place="淺草寺", text="富士山跟排隊")]

    assert ids(dense_top_k(embedder, "看得到富士山嗎", pool, 2)) == [2, 3]


def f(names=(), **time) -> Filter:
    return Filter.from_dict({"place": {"name": names[0], "name_ja": names[-1]} if names else None,
                             "month": time.get("month"), "day_type": time.get("day_type"), "time": time.get("time")})


def test_place_is_matched_by_string_against_the_fragment_names_without_expanding_areas():
    sky = frag(1, place="東京晴空塔")
    bridge = frag(2, place="十間橋")
    tokyo = frag(3, place="東京")
    ja = frag(4, place="浅草寺")

    oshiage = f(("押上", "押上"))
    skytree = f(("晴空塔", "スカイツリー"))
    asakusa = f(("淺草寺", "浅草寺"))

    assert not oshiage.matches(bridge)          # 區域不展開到底下的景點
    assert skytree.matches(sky)                 # 名稱包含在片段的地點名稱裡
    assert not skytree.matches(tokyo)           # 片段名稱比較短不算
    assert asakusa.matches(ja)                  # 日文寫法也比對
    assert f().matches(bridge)                  # 沒有地點就不限


def test_time_uses_the_main_system_rules_with_unknown_matching():
    flt = f(month=["3"], time=["早上"])

    assert flt.matches(frag(1, month="3", time="早上"))
    assert flt.matches(frag(2, month="不明", time="早上"))
    assert flt.matches(frag(3, month="春", time="全天"))
    assert not flt.matches(frag(4, month="5", time="早上"))
    assert not flt.matches(frag(5, month="3", time="晚上"))


def test_several_filters_each_take_top_k_then_merge(embedder):
    pool = [frag(1, time="早上", text="富士山"), frag(2, time="早上", text="富士山排隊"), frag(3, time="早上", text="甲板"),
            frag(4, time="晚上", text="富士山夕陽"), frag(5, time="晚上", text="甲板")]

    got, unmatched = filter_top_k(embedder, "富士山", pool, [f(time=["早上"]), f(time=["晚上"])], 1)

    # 每組各取 1 筆：早上取 1 或 2（同分取 id 小的），晚上取 4
    assert sorted(ids(got)) == [1, 4]
    assert unmatched is False


def test_filter_whose_place_matches_no_fragment_is_reported(embedder):
    pool = [frag(1, place="淺草寺", text="富士山")]

    got, unmatched = filter_top_k(embedder, "富士山", pool, [f(("清水寺", "清水寺"))], 5)

    assert got == [] and unmatched is True
