"""檢索 seam：多子查詢、group_by 分組、compose 合併或對照。不打外部 API。"""
from strag_v3.place import AREA


def layout(sections):
    """每段的分組鍵和分組內的片段 id。"""
    return [[(g.key, [e.content_id for e in g.evidence]) for g in s.groups] for s in sections]


def test_group_by_time_of_day_follows_the_content_slot_with_all_day_and_unknown_last(add, retrieve):
    unknown = add(time="不明")
    all_day = add(time="全天")
    night = add(time="晚上")
    morning = add(time="早上")
    evening = add(time="晚上", month="3", article="a2")
    noon = add(time="中午")

    assert layout(retrieve(group_by=["time_of_day"])) == [[
        ({"time_of_day": "早上"}, [morning]),
        ({"time_of_day": "中午"}, [noon]),
        ({"time_of_day": "晚上"}, [night, evening]),
        ({"time_of_day": "全天"}, [all_day]),
        ({"time_of_day": "不明"}, [unknown]),
    ]]


def test_group_by_month_follows_the_content_label(add, retrieve):
    dec = add(month="12")
    unknown = add(month="不明")
    winter = add(month="冬")
    cross_year = add(month="12-2")
    jan = add(day_type="假日", time="晚上", month="1")

    assert layout(retrieve(group_by=["month"])) == [[
        ({"month": "1"}, [jan]),
        ({"month": "12"}, [dec]),
        ({"month": "12-2"}, [cross_year]),
        ({"month": "冬"}, [winter]),
        ({"month": "不明"}, [unknown]),
    ]]


def test_group_by_place_puts_the_place_with_the_best_evidence_first(add, retrieve, sub, typesafe):
    typesafe.nouls = {"夕陽": 0.9, "夕陽和排隊": 0.7}
    tower = add("晴空塔", "假日", "下午", "12", content="夕陽和排隊")
    temple = add("淺草寺", "假日", "下午", "12", content="夕陽")
    tower_2 = add("晴空塔", "假日", "下午", "12", content="夕陽和排隊", article="a2")

    sections = retrieve(sub(space=None, aspect="夕陽", time=["下午", "晚上"]), group_by=["place"])

    assert layout(sections) == [[
        ({"place": "淺草寺"}, [temple]),
        ({"place": "晴空塔"}, [tower, tower_2]),
    ]]


def test_group_by_place_groups_by_osm_object_and_keeps_area_content_on_its_own(add, retrieve, sub, typesafe):
    typesafe.nouls = {"夕陽": 0.9, "夕陽和排隊": 0.7}
    tower = add("晴空塔", content="夕陽和排隊")
    tower_ja = add("スカイツリー", content="夕陽和排隊", article="a2")  # 同一個 OSM 物件，組名用第一次抽到的繁中名稱
    area = add("押上", content="夕陽和排隊", kind=AREA)                  # 區域本身的片段，不拆到底下的景點
    river = add("北十間川", content="夕陽")

    sections = retrieve(sub(space="押上", kind=AREA, aspect="夕陽"), group_by=["place"])

    assert layout(sections) == [[
        ({"place": "北十間川"}, [river]),
        ({"place": "晴空塔"}, [tower, tower_ja]),
        ({"place": "押上"}, [area]),
    ]]


def test_group_by_several_dimensions_at_once(add, retrieve):
    weekend_night = add("晴空塔", "假日", "晚上", "12")
    weekday_morning = add("晴空塔", "平日", "早上", "12")
    weekend_morning = add("晴空塔", "假日", "早上", "12")
    weekday_night = add("晴空塔", "平日", "晚上", "12")
    weekday_morning_2 = add("晴空塔", "平日", "早上", "1", article="a2")

    assert layout(retrieve(group_by=["day_type", "time_of_day"])) == [[
        ({"day_type": "平日", "time_of_day": "早上"}, [weekday_morning, weekday_morning_2]),
        ({"day_type": "平日", "time_of_day": "晚上"}, [weekday_night]),
        ({"day_type": "假日", "time_of_day": "早上"}, [weekend_morning]),
        ({"day_type": "假日", "time_of_day": "晚上"}, [weekend_night]),
    ]]


def test_contrast_hands_each_sub_query_its_own_section(add, retrieve, sub):
    dusk = add("澀谷 SKY", "假日", "下午", "12")
    night = add("澀谷 SKY", "平日", "晚上", "12", article="a2")
    all_evening = add("澀谷 SKY", "假日", "全天", "12", article="a3")  # 兩邊都對得上
    morning = add("澀谷 SKY", "平日", "早上", "12")

    dusk_q = sub(space="澀谷 SKY", month="12", time="下午")
    night_q = sub(space="澀谷 SKY", month="12", time="晚上")
    sections = retrieve(dusk_q, night_q, compose="contrast")

    assert [[r.sub_query.time.time for r in s.results] for s in sections] == [[("下午",)], [("晚上",)]]
    assert layout(sections) == [
        [({}, [dusk, all_evening])],
        [({}, [night, all_evening])],
    ]


def test_merge_pools_sub_queries_into_one_section_without_duplicates(add, retrieve, sub):
    dusk = add("澀谷 SKY", "假日", "下午", "12")
    night = add("澀谷 SKY", "平日", "晚上", "12", article="a2")
    all_evening = add("澀谷 SKY", "假日", "全天", "12", article="a3")

    dusk_q = sub(space="澀谷 SKY", month="12", time="下午")
    night_q = sub(space="澀谷 SKY", month="12", time="晚上")
    [section] = retrieve(dusk_q, night_q, compose="merge")

    assert len(section.results) == 2
    assert layout([section]) == [[({}, [dusk, night, all_evening])]]


def test_contrast_groups_each_section_on_its_own(add, retrieve, sub):
    weekday = add("晴空塔", "平日", "早上", "12")
    weekend = add("晴空塔", "假日", "早上", "12")
    weekend_june = add("晴空塔", "假日", "早上", "6")

    sections = retrieve(sub(month="12"), sub(month="6"), group_by=["day_type"], compose="contrast")

    assert layout(sections) == [
        [({"day_type": "平日"}, [weekday]), ({"day_type": "假日"}, [weekend])],
        [({"day_type": "假日"}, [weekend_june])],
    ]
