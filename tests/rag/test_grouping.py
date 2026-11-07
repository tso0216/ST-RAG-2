"""檢索 seam：多子查詢、group_by 分組、compose 合併或對照。不打外部 API。"""
import pytest

from strag_v3.rag.params import Params


def layout(sections):
    """每段的分組鍵和分組內的片段 id。"""
    return [[(g.key, [e.content_id for e in g.evidence]) for g in s.groups] for s in sections]


def test_group_by_time_of_day(add, retrieve):
    morning = add("晴空塔", "平日", "8", "1")
    night = add("晴空塔", "平日", "20", "1")
    evening = add("晴空塔", "假日", "晚上", "3", article="a2")

    assert layout(retrieve(group_by=["time_of_day"])) == [[
        ({"time_of_day": "早上"}, [morning]),
        ({"time_of_day": "晚上"}, [night, evening]),
    ]]


def test_content_spanning_groups_goes_to_the_group_holding_most_of_its_time(add, retrieve):
    mostly_evening = add("晴空塔", "平日", "16-18", "1")    # 16 下午，17、18 晚上
    mostly_afternoon = add("晴空塔", "平日", "12-15", "1")  # 12 中午，13–15 下午

    assert layout(retrieve(group_by=["time_of_day"])) == [[
        ({"time_of_day": "下午"}, [mostly_afternoon]),
        ({"time_of_day": "晚上"}, [mostly_evening]),
    ]]


@pytest.mark.parametrize("bandwidths", [
    {"hour_bandwidth": 0, "month_bandwidth": 0},
    {},  # 預設頻寬
    {"hour_bandwidth": 3, "month_bandwidth": 2},
])
def test_groups_follow_the_content_labels_whatever_the_smoothing_bandwidth(add, retrieve, bandwidths):
    dusk = add("晴空塔", "平日", "16-17", "11-12")  # 16 下午、17 晚上各半；11、12 月各半：並列時歸前面的組
    night = add("晴空塔", "平日", "20", "12")

    assert layout(retrieve(group_by=["time_of_day", "month"], params=Params(**bandwidths))) == [[
        ({"time_of_day": "下午", "month": "11"}, [dusk]),
        ({"time_of_day": "晚上", "month": "12"}, [night]),
    ]]


def test_all_day_content_gets_its_own_group(add, retrieve):
    all_day = add("晴空塔", "平日", "全天", "1")
    morning = add("晴空塔", "平日", "8", "1")
    night = add("晴空塔", "平日", "晚上", "1")
    unknown = add("晴空塔", "平日", "不明", "1")

    assert layout(retrieve(group_by=["time_of_day"])) == [[
        ({"time_of_day": "早上"}, [morning]),
        ({"time_of_day": "晚上"}, [night]),
        ({"time_of_day": "全天"}, [all_day]),
        ({"time_of_day": "不明"}, [unknown]),
    ]]


def test_unknown_time_gets_its_own_group_after_known_ones(add, retrieve):
    unknown = add("晴空塔", "平日", "不明", "1")
    late = add("晴空塔", "平日", "2", "1")

    assert layout(retrieve(group_by=["time_of_day"])) == [[
        ({"time_of_day": "深夜"}, [late]),
        ({"time_of_day": "不明"}, [unknown]),
    ]]


def test_group_by_month(add, retrieve):
    dec = add("晴空塔", "平日", "10", "12")
    jan = add("晴空塔", "假日", "18", "1")
    unknown = add("晴空塔", "平日", "10", "不明")

    assert layout(retrieve(group_by=["month"])) == [[
        ({"month": "1"}, [jan]),
        ({"month": "12"}, [dec]),
        ({"month": "不明"}, [unknown]),
    ]]


def test_group_by_place_puts_the_place_with_the_best_evidence_first(add, retrieve, sub):
    tower = add("晴空塔", "假日", "17", "12", content="夕陽和排隊")
    temple = add("淺草寺", "假日", "17", "12", content="夕陽")
    tower_2 = add("晴空塔", "假日", "17", "12", content="夕陽和排隊", article="a2")

    sections = retrieve(sub(space=None, aspect="夕陽", time="16-18"), group_by=["place"])

    assert layout(sections) == [[
        ({"place": "淺草寺"}, [temple]),
        ({"place": "晴空塔"}, [tower, tower_2]),
    ]]


FUSHIMI = """
    [[node]]
    name = "伏見稻荷大社"

    [[node]]
    name = "伏見稻荷大社表參道"
    parent = "伏見稻荷大社"
    aliases = ["伏見稻荷表參道"]

    [[node]]
    name = "千本鳥居"
    parent = "伏見稻荷大社"
    aliases = ["伏見稻荷大社 千本鳥居"]
"""


def test_group_by_place_puts_aliases_of_one_place_together_under_its_canonical_name(add, retrieve, sub, hierarchy):
    gate = add("千本鳥居")
    gate_alias = add("伏見稻荷大社 千本鳥居")
    approach_alias = add("伏見稻荷表參道")
    approach_spaced = add("伏見稻荷大社 表參道")  # 只差空白

    sections = retrieve(sub(space="伏見稻荷大社"), group_by=["place"], hierarchy=hierarchy(FUSHIMI))

    assert layout(sections) == [[
        ({"place": "千本鳥居"}, [gate, gate_alias]),
        ({"place": "伏見稻荷大社表參道"}, [approach_alias, approach_spaced]),
    ]]


def test_group_by_several_dimensions_at_once(add, retrieve):
    weekend_night = add("晴空塔", "假日", "20", "12")
    weekday_morning = add("晴空塔", "平日", "9", "12")
    weekend_morning = add("晴空塔", "假日", "早上", "12")
    weekday_night = add("晴空塔", "平日", "晚上", "12")
    weekday_morning_2 = add("晴空塔", "平日", "8-10", "1", article="a2")

    assert layout(retrieve(group_by=["day_type", "time_of_day"])) == [[
        ({"day_type": "平日", "time_of_day": "早上"}, [weekday_morning, weekday_morning_2]),
        ({"day_type": "平日", "time_of_day": "晚上"}, [weekday_night]),
        ({"day_type": "假日", "time_of_day": "早上"}, [weekend_morning]),
        ({"day_type": "假日", "time_of_day": "晚上"}, [weekend_night]),
    ]]


def test_contrast_hands_each_sub_query_its_own_section(add, retrieve, sub):
    dusk = add("澀谷 SKY", "假日", "16", "12")
    night = add("澀谷 SKY", "平日", "22", "12", article="a2")
    all_evening = add("澀谷 SKY", "假日", "16-22", "12", article="a3")  # 兩邊都沾得到
    morning = add("澀谷 SKY", "平日", "9", "12")

    dusk_q = sub(space="澀谷 SKY", month="12", time="15-17")
    night_q = sub(space="澀谷 SKY", month="12", time="21-23")
    sections = retrieve(dusk_q, night_q, compose="contrast")

    assert [[r.sub_query.time.time for r in s.results] for s in sections] == [["15-17"], ["21-23"]]
    assert layout(sections) == [
        [({}, [dusk, all_evening])],
        [({}, [night, all_evening])],
    ]


def test_merge_pools_sub_queries_into_one_section_without_duplicates(add, retrieve, sub):
    dusk = add("澀谷 SKY", "假日", "16", "12")
    night = add("澀谷 SKY", "平日", "22", "12", article="a2")
    all_evening = add("澀谷 SKY", "假日", "16-22", "12", article="a3")

    dusk_q = sub(space="澀谷 SKY", month="12", time="15-17")
    night_q = sub(space="澀谷 SKY", month="12", time="21-23")
    [section] = retrieve(dusk_q, night_q, compose="merge")

    assert len(section.results) == 2
    assert layout([section]) == [[({}, [dusk, night, all_evening])]]


def test_contrast_groups_each_section_on_its_own(add, retrieve, sub):
    weekday = add("晴空塔", "平日", "10", "12")
    weekend = add("晴空塔", "假日", "10", "12")
    weekend_june = add("晴空塔", "假日", "10", "6")

    sections = retrieve(sub(month="12"), sub(month="6"), group_by=["day_type"], compose="contrast")

    assert layout(sections) == [
        [({"day_type": "平日"}, [weekday]), ({"day_type": "假日"}, [weekend])],
        [({"day_type": "假日"}, [weekend_june])],
    ]
