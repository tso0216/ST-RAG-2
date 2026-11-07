"""生成器的輸入：檢索 seam 的輸出經 build_answer_prompt 整理後，生成器看到什麼。不打外部 API。"""
import json
import re

from strag_v3.rag.llm import build_answer_prompt


def evidence_in(prompt: str) -> dict[int, dict]:
    """prompt 裡所有 JSON 區塊中的證據，依片段 id 索引。"""
    out = {}
    stack = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", prompt, re.S)]
    while stack:
        x = stack.pop()
        if isinstance(x, dict) and "片段 id" in x:
            out[x["片段 id"]] = x
        elif isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return out


def conditions_in(prompt: str) -> list[list[dict]]:
    """每段的檢索條件。"""
    return [json.loads(c) for c in re.findall(r"^檢索條件：(.*)$", prompt, re.M)]


FLAGS = ("時間退讓", "空間退讓", "時間不明")


def flags(e: dict) -> tuple[str, ...]:
    return tuple(f for f in FLAGS if e[f])


def test_evidence_shows_its_own_time_labels_and_no_flags_when_it_matches(add, retrieve, sub):
    row = add("晴空塔", "平日", "晚上", "12")

    got = evidence_in(build_answer_prompt("十二月平日晚上排隊要多久",
                                          retrieve(sub(month="12", day_type="平日", time="晚上"))))

    assert (got[row]["月份"], got[row]["平日／假日"], got[row]["時段"]) == ("12", "平日", "晚上")
    assert flags(got[row]) == ()


def test_time_backoff_evidence_is_flagged(add, retrieve, sub):
    january = add("晴空塔", "平日", "早上", "1")

    got = evidence_in(build_answer_prompt("十二月早上排隊要多久", retrieve(sub(month="12", time="早上"))))

    assert flags(got[january]) == ("時間退讓",)


def test_space_backoff_evidence_names_the_admin_area_it_came_from(add, retrieve, sub):
    town = add("晴空塔城", "平日", "早上", "12")

    got = evidence_in(build_answer_prompt("十二月晴空塔排隊要多久", retrieve(sub(space="晴空塔", month="12"))))

    assert flags(got[town]) == ("空間退讓",)
    assert (got[town]["地點"], got[town]["空間退讓到"]) == ("晴空塔城", "押上一丁目")


def test_unknown_time_evidence_is_flagged(add, retrieve, sub):
    unknown = add("晴空塔", "平日", "不明", "12")

    got = evidence_in(build_answer_prompt("十二月早上排隊要多久", retrieve(sub(month="12", time="早上"))))

    assert flags(got[unknown]) == ("時間不明",)


def test_merged_evidence_matching_any_sub_query_directly_is_not_flagged(add, retrieve, sub):
    # 一月片段：十二月的子查詢靠時間退讓才取回；一月的子查詢直接取回
    january = add("晴空塔", "平日", "早上", "1")

    sections = retrieve(sub(month="12"), sub(month="1"), compose="merge")
    got = evidence_in(build_answer_prompt("十二月和一月排隊要多久", sections))

    assert flags(got[january]) == ()


def test_empty_sub_query_lists_slots_and_months_with_data(add, retrieve, sub):
    add("晴空塔", "平日", "早上", "5")
    add("晴空塔", "假日", "早上", "5", article="a2")
    add("晴空塔", "平日", "晚上", "夏", article="a3")

    prompt = build_answer_prompt("一月排隊要多久", retrieve(sub(month="1")))
    [empty] = json.loads(re.search(r"沒有證據的子查詢.*?```json\n(.*?)\n```", prompt, re.S)[1])

    assert empty["有資料的時段"] == {"早上": 2, "晚上": 1}
    assert empty["有資料的月份"] == {"5": 2, "夏": 1}


def test_each_section_states_its_sub_query_time(add, retrieve, sub):
    add("澀谷 SKY", "假日", "下午", "12")
    add("澀谷 SKY", "平日", "晚上", "12")

    sections = retrieve(sub(space="澀谷 SKY", month="12", time=["下午", "晚上"]),
                        sub(space="澀谷 SKY", month="12", time="晚上"), compose="contrast")
    conditions = conditions_in(build_answer_prompt("十二月傍晚跟晚上哪個比較不擠", sections))

    assert [[(c["月份"], c["時段"]) for c in section] for section in conditions] == [
        [("12", "下午、晚上")],
        [("12", "晚上")],
    ]
