"""檢索 seam：多子查詢、group_by 分組、compose 合併或對照。不打外部 API。"""
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


def add(conn, place, day_type, time, month, content="排隊狀況", article="a1"):
    pid = conn.execute("SELECT id FROM place WHERE name = ?", (place,)).fetchone()
    pid = pid[0] if pid else conn.execute("INSERT INTO place (name) VALUES (?)", (place,)).lastrowid
    return conn.execute(
        "INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month, content)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)", (article, pid, place, day_type, time, month, content)).lastrowid


def sub(space="晴空塔", aspect="排隊", **time):
    return {"space": space, "time": time or None, "aspect": aspect}


def grouped(conn, *subs, group_by=(), compose=None, params=Params(), question="排隊要多久"):
    d = {"sub_queries": list(subs) or [sub()], "group_by": list(group_by)}
    if compose:
        d["compose"] = compose
    return Retriever(conn, KeywordEmbedder(), params).retrieve_grouped(Plan.from_dict(d), question)


def layout(sections):
    """每段的分組鍵和分組內的片段 id。"""
    return [[(g.key, [e.content_id for e in g.evidence]) for g in s.groups] for s in sections]


def test_group_by_time_of_day(conn):
    morning = add(conn, "晴空塔", "平日", "8", "1")
    night = add(conn, "晴空塔", "平日", "20", "1")
    evening = add(conn, "晴空塔", "假日", "晚上", "3", article="a2")

    assert layout(grouped(conn, group_by=["time_of_day"])) == [[
        ({"time_of_day": "早上"}, [morning]),
        ({"time_of_day": "晚上"}, [night, evening]),
    ]]


def test_content_spanning_groups_goes_to_the_group_holding_most_of_its_time(conn):
    mostly_evening = add(conn, "晴空塔", "平日", "16-18", "1")    # 16 下午，17、18 晚上
    mostly_afternoon = add(conn, "晴空塔", "平日", "12-15", "1")  # 12 中午，13–15 下午

    assert layout(grouped(conn, group_by=["time_of_day"])) == [[
        ({"time_of_day": "下午"}, [mostly_afternoon]),
        ({"time_of_day": "晚上"}, [mostly_evening]),
    ]]


def test_unknown_time_gets_its_own_group_after_known_ones(conn):
    unknown = add(conn, "晴空塔", "平日", "不明", "1")
    late = add(conn, "晴空塔", "平日", "2", "1")

    assert layout(grouped(conn, group_by=["time_of_day"])) == [[
        ({"time_of_day": "深夜"}, [late]),
        ({"time_of_day": "不明"}, [unknown]),
    ]]


def test_group_by_month(conn):
    dec = add(conn, "晴空塔", "平日", "10", "12")
    jan = add(conn, "晴空塔", "假日", "18", "1")
    unknown = add(conn, "晴空塔", "平日", "10", "不明")

    assert layout(grouped(conn, group_by=["month"])) == [[
        ({"month": "1"}, [jan]),
        ({"month": "12"}, [dec]),
        ({"month": "不明"}, [unknown]),
    ]]


def test_group_by_place_puts_the_place_with_the_best_evidence_first(conn):
    tower = add(conn, "晴空塔", "假日", "17", "12", content="夕陽和排隊")
    temple = add(conn, "淺草寺", "假日", "17", "12", content="夕陽")
    tower_2 = add(conn, "晴空塔", "假日", "17", "12", content="夕陽和排隊", article="a2")

    sections = grouped(conn, sub(space=None, aspect="夕陽", time="16-18"), group_by=["place"])

    assert layout(sections) == [[
        ({"place": "淺草寺"}, [temple]),
        ({"place": "晴空塔"}, [tower, tower_2]),
    ]]


def test_group_by_several_dimensions_at_once(conn):
    weekend_night = add(conn, "晴空塔", "假日", "20", "12")
    weekday_morning = add(conn, "晴空塔", "平日", "9", "12")
    weekend_morning = add(conn, "晴空塔", "假日", "早上", "12")
    weekday_night = add(conn, "晴空塔", "平日", "晚上", "12")
    weekday_morning_2 = add(conn, "晴空塔", "平日", "8-10", "1", article="a2")

    assert layout(grouped(conn, group_by=["day_type", "time_of_day"])) == [[
        ({"day_type": "平日", "time_of_day": "早上"}, [weekday_morning, weekday_morning_2]),
        ({"day_type": "平日", "time_of_day": "晚上"}, [weekday_night]),
        ({"day_type": "假日", "time_of_day": "早上"}, [weekend_morning]),
        ({"day_type": "假日", "time_of_day": "晚上"}, [weekend_night]),
    ]]


def test_contrast_hands_each_sub_query_its_own_section(conn):
    dusk = add(conn, "澀谷 SKY", "假日", "16", "12")
    night = add(conn, "澀谷 SKY", "平日", "22", "12", article="a2")
    all_evening = add(conn, "澀谷 SKY", "假日", "16-22", "12", article="a3")  # 兩邊都沾得到
    morning = add(conn, "澀谷 SKY", "平日", "9", "12")

    dusk_q = sub(space="澀谷 SKY", month="12", time="15-17")
    night_q = sub(space="澀谷 SKY", month="12", time="21-23")
    sections = grouped(conn, dusk_q, night_q, compose="contrast")

    assert [[r.sub_query.time.time for r in s.results] for s in sections] == [["15-17"], ["21-23"]]
    assert layout(sections) == [
        [({}, [dusk, all_evening])],
        [({}, [night, all_evening])],
    ]


def test_merge_pools_sub_queries_into_one_section_without_duplicates(conn):
    dusk = add(conn, "澀谷 SKY", "假日", "16", "12")
    night = add(conn, "澀谷 SKY", "平日", "22", "12", article="a2")
    all_evening = add(conn, "澀谷 SKY", "假日", "16-22", "12", article="a3")

    dusk_q = sub(space="澀谷 SKY", month="12", time="15-17")
    night_q = sub(space="澀谷 SKY", month="12", time="21-23")
    [section] = grouped(conn, dusk_q, night_q, compose="merge")

    assert len(section.results) == 2
    assert layout([section]) == [[({}, [dusk, night, all_evening])]]


def test_contrast_groups_each_section_on_its_own(conn):
    weekday = add(conn, "晴空塔", "平日", "10", "12")
    weekend = add(conn, "晴空塔", "假日", "10", "12")
    weekend_june = add(conn, "晴空塔", "假日", "10", "6")

    sections = grouped(conn, sub(month="12"), sub(month="6"), group_by=["day_type"], compose="contrast")

    assert layout(sections) == [
        [({"day_type": "平日"}, [weekday]), ({"day_type": "假日"}, [weekend])],
        [({"day_type": "假日"}, [weekend_june])],
    ]
