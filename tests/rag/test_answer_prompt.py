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


def test_evidence_matching_the_asked_time_is_marked_fully_matching(add, retrieve, sub):
    exact = add("晴空塔", "平日", "晚上", "12")
    inside = add("晴空塔", "平日", "20", "12")
    january = add("晴空塔", "平日", "晚上", "1")

    prompt = build_answer_prompt("十二月平日晚上排隊要多久", retrieve(sub(month="12", day_type="平日", time="晚上")))
    got = evidence_in(prompt)

    assert got[exact]["時間相符程度"] == 1
    assert got[inside]["時間相符程度"] == 1
    assert got[january]["時間相符程度"] == 0


def test_neighbouring_hour_is_marked_outside_the_asked_time(add, retrieve, sub):
    at23 = add("晴空塔", "假日", "23", "8")
    midnight = add("晴空塔", "假日", "0", "8")

    got = evidence_in(build_answer_prompt("23 點排隊要多久", retrieve(sub(time="23"))))

    assert got[at23]["時間相符程度"] == 1
    assert got[midnight]["時間相符程度"] == 0


def test_vague_content_is_marked_partly_matching(add, retrieve, sub):
    winter = add("晴空塔", "平日", "10", "冬")  # 十二月、一月、二月各三分之一

    got = evidence_in(build_answer_prompt("十二月排隊要多久", retrieve(sub(month="12"))))

    assert 0 < got[winter]["時間相符程度"] < 1


def test_merged_evidence_matching_any_sub_query_time_is_fully_matching(add, retrieve, sub):
    # 一月片段：對十二月的子查詢語意分數高、時間不符；對一月的子查詢時間相符、語意分數低
    january = add("晴空塔", "平日", "10", "1", content="排隊")

    sections = retrieve(sub(month="12", aspect="排隊"), sub(month="1", aspect="富士山"), compose="merge")
    got = evidence_in(build_answer_prompt("十二月和一月排隊要多久", sections))

    assert got[january]["時間相符程度"] == 1


def test_each_section_states_its_sub_query_time(add, retrieve, sub):
    add("澀谷 SKY", "假日", "17", "12")
    add("澀谷 SKY", "平日", "21", "12")

    sections = retrieve(sub(space="澀谷 SKY", month="12", time="16-18"),
                        sub(space="澀谷 SKY", month="12", time="晚上"), compose="contrast")
    conditions = conditions_in(build_answer_prompt("十二月傍晚跟晚上哪個比較不擠", sections))

    assert [[(c["月份"], c["時段"]) for c in section] for section in conditions] == [
        [("12", "16-18")],
        [("12", "晚上")],
    ]
