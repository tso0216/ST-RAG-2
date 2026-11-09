"""`scripts/eval/qgen.py` 給協調者用的指令：layers、frag、usage、merge、blind-input、blind-diff。

用真的 `data/ptt.db`（唯讀）和 generate.md〈範例〉裡完整的 stay-01。
"""
import importlib.util
import json
import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("qgen", ROOT / "scripts" / "eval" / "qgen.py")
qgen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qgen)

WHEN = '{"month": ["3"], "time": ["晚上"]}'


def stay_01() -> dict:
    """generate.md〈範例〉的停留經驗 exact 那一題。"""
    md = (ROOT / "src" / "strag_v3" / "eval" / "questions" / "generate.md").read_text()
    block = re.search(r"\*\*停留經驗、`exact`（完整的一題）\*\*：\n\n```json\n(.*?)\n```", md, re.S).group(1)
    return json.loads(block)


def run(capsys, *args) -> tuple[int, str]:
    code = qgen.main([str(a) for a in args])
    return code, capsys.readouterr().out


def test_layers_prints_each_retrieval_layer_with_as_many_candidates_as_pool_prints(capsys):
    _, out = run(capsys, "layers", 50, "--when", WHEN)
    lines = out.splitlines()

    assert [line.split(" | ")[0] for line in lines] == ["exact", "time_backoff", "space_backoff"]
    pools = [("pool", 50, "--when", WHEN), ("pool", 50, "--when", WHEN, "--widen"), ("pool", 51, "--when", WHEN)]
    for line, args in zip(lines, pools):
        pool = run(capsys, *args)[1].splitlines()
        assert f"候選 {len(pool)}" in line, line
        assert f"限定維度不明 {sum('限定維度不明' in p for p in pool)}" in line, line
    assert "50 淺草寺" in lines[0] and "51 浅草二丁目" in lines[2]
    assert '"month": ["2", "3", "4"]' in lines[1], "時間退讓層印擴大後的條件"


def test_frag_prints_the_given_fragments_in_pool_format(capsys):
    _, pool = run(capsys, "pool", 50, "--when", WHEN)
    by_id = {line.split(" | ")[0]: line for line in pool.splitlines()}

    code, out = run(capsys, "frag", 6, 611)

    assert code == 0
    assert out.splitlines() == [by_id["6"], by_id["611"]]
    assert out.startswith("6 | 淺草寺 | 3/平日/晚上 | ") and "仲見世通り空蕩蕩" in out


def test_frag_reports_a_missing_fragment(capsys):
    code, out = run(capsys, "frag", 6, 999999)

    assert code == 1
    assert "沒有片段 999999" in out


def write_draft(path: Path, *questions: dict) -> Path:
    path.write_text(json.dumps({"annotation_note": "草稿", "questions": list(questions)}, ensure_ascii=False))
    return path


def test_merge_combines_drafts_sorted_by_id(tmp_path, capsys):
    q1 = stay_01()
    q2 = {**stay_01(), "id": "stay-02"}
    second = write_draft(tmp_path / "stay-2.json", q2)
    first = write_draft(tmp_path / "stay-1.json", q1)
    out = tmp_path / "ptt_v2" / "stay.json"

    code, _ = run(capsys, "merge", out, second, first)

    assert code == 0
    merged = json.loads(out.read_text())
    assert merged == {"annotation_note": "依 src/strag_v3/eval/questions/generate.md 出題與標註",
                      "questions": [q1, q2]}


def test_merge_refuses_duplicate_ids_and_writes_nothing(tmp_path, capsys):
    a = write_draft(tmp_path / "stay-1.json", stay_01())
    b = write_draft(tmp_path / "stay-2.json", stay_01())
    out = tmp_path / "stay.json"

    code, printed = run(capsys, "merge", out, a, b)

    assert code == 1
    assert "stay-01" in printed
    assert not out.exists()


def test_usage_without_question_files_says_so(tmp_path, capsys):
    (tmp_path / "stay-blind-1.json").write_text('{"stay-01": {"relevant": {}, "excluded": {}}}')

    assert run(capsys, "usage", tmp_path)[1].strip() == "還沒有題目"
    assert run(capsys, "usage", tmp_path / "ptt_v2")[1].strip() == "還沒有題目"


def test_usage_counts_places_per_type_marks_limits_and_lists_used_combinations(tmp_path, capsys):
    asakusa = {"place_id": 50, "name": "淺草寺", "kind": "景點"}
    park = {"place_id": 60, "name": "隅田公園", "kind": "景點"}

    def q(qid, type_, when, space=asakusa):
        return {"id": qid, "type": type_, "space": space, "aspect": "人潮多寡", "when": when}

    write_draft(tmp_path / "stay.json", stay_01(), q("stay-02", "停留經驗", {"month": ["4"]}),
                q("stay-03", "停留經驗", {"month": ["4"]}, park))
    write_draft(tmp_path / "move.json", q("move-01", "移動經驗", {"time": ["早上"]}),
                q("move-02", "移動經驗", {"time": ["晚上"]}))
    write_draft(tmp_path / "find_place.json", q("place-01", "找地點", {"time": ["早上"]}))
    write_draft(tmp_path / "compare.json", {
        "id": "cmp-01", "type": "比較", "aspect": "人潮多寡", "when": {"time": ["早上"]},
        "options": [{"label": "淺草寺", "space": asakusa, "when": {"time": ["早上"]}},
                    {"label": "隅田公園", "space": park, "when": {"time": ["早上"]}}]})

    code, out = run(capsys, "usage", tmp_path)

    assert code == 0
    lines = out.splitlines()
    asakusa_line = next(line for line in lines if line.startswith("50 淺草寺"))
    for part in ("停留經驗 2（到上限）", "移動經驗 2（到上限）", "找地點 1", "比較 1", "合計 6（到上限）"):
        assert part in asakusa_line, asakusa_line
    park_line = next(line for line in lines if line.startswith("60 隅田公園"))
    assert "停留經驗 1" in park_line and "合計 2" in park_line and "到上限" not in park_line
    combos = [line for line in lines if "｜人潮多寡｜" in line]
    assert '50 淺草寺（景點）｜人潮多寡｜{"month": ["3"], "time": ["晚上"]}｜stay-01' in combos
    assert '50 淺草寺（景點）｜人潮多寡｜{"time": ["早上"]}｜cmp-01、move-01、place-01' in combos
    assert '60 隅田公園（景點）｜人潮多寡｜{"time": ["早上"]}｜cmp-01' in combos


FORBIDDEN = {"coverage", "relevant_contents", "relevant_articles", "excluded", "expect", "expect_sources",
             "label_issues", "options"}


def keys_in(x) -> set[str]:
    if isinstance(x, dict):
        return set(x) | set().union(*(keys_in(v) for v in x.values()))
    if isinstance(x, list):
        return set().union(*(keys_in(v) for v in x))
    return set()


def blind_input(capsys, tmp_path, *questions, ids=()) -> dict:
    path = write_draft(tmp_path / "q.json", *questions)
    code, out = run(capsys, "blind-input", path, *ids)
    assert code == 0, out
    return json.loads(out)


def judged(question: dict) -> list[int]:
    return [int(i) for layer in question["layers"] for i in layer["judge"]]


def test_blind_input_hides_the_annotation_and_lists_exactly_the_candidates_to_judge(tmp_path, capsys):
    q = stay_01()
    data = blind_input(capsys, tmp_path, q)

    assert data["說明"]
    [item] = data["題目"]
    assert not keys_in(data) & FORBIDDEN
    assert {k: item[k] for k in ("id", "type", "question", "when", "aspect", "aspect_rule")} == \
        {k: q[k] for k in ("id", "type", "question", "when", "aspect", "aspect_rule")}
    [layer] = item["layers"]
    assert layer["layer"] == "exact" and layer["when"] == q["when"] and "50 淺草寺" in layer["space"]
    assert sorted(judged(item)) == sorted(q["relevant_contents"] + [int(i) for i in q["excluded"]])
    assert layer["pool"] == f".venv/bin/python scripts/eval/qgen.py pool 50 --when '{WHEN}'"


@pytest.mark.parametrize("coverage, layers", [("time_backoff", ["exact", "time_backoff"]),
                                              ("none", ["exact", "time_backoff", "space_backoff"])])
def test_blind_input_gives_every_layer_up_to_coverage_with_each_fragment_once(tmp_path, capsys, coverage, layers):
    q = {**stay_01(), "coverage": coverage}
    db = qgen.DB(ROOT / "data" / "ptt.db")

    [item] = blind_input(capsys, tmp_path, q)["題目"]

    assert [layer["layer"] for layer in item["layers"]] == layers
    assert sorted(judged(item)) == sorted(db.must_judge(q["space"], q["when"], coverage))
    widened = item["layers"][1]
    assert widened["pool"].endswith(" --widen") and widened["when"]["month"] == ["2", "3", "4"]
    if coverage == "none":
        assert item["layers"][2]["pool"] == f".venv/bin/python scripts/eval/qgen.py pool 51 --when '{WHEN}'"
    for layer in item["layers"]:
        pool = run(capsys, *shlex.split(layer["pool"])[2:])[1]
        assert set(layer["judge"]) <= {int(line.split(" | ")[0]) for line in pool.splitlines()}


def test_blind_input_for_comparison_judges_each_option_and_marks_shared_fragments(tmp_path, capsys):
    asakusa = {"place_id": 50, "name": "淺草寺", "kind": "景點"}
    q = {"id": "cmp-01", "type": "比較", "question": "淺草寺平日早上跟假日早上，人潮差在哪？",
         "when": {"time": ["早上"]}, "aspect": "人潮多寡", "aspect_rule": "算：人多人少；不算：氣氛",
         "coverage": "exact", "relevant_contents": [67, 124, 62, 135],
         "options": [{"label": "平日早上", "space": asakusa, "when": {"day_type": "平日", "time": ["早上"]},
                      "relevant_contents": [67, 124]},
                     {"label": "假日早上", "space": asakusa, "when": {"day_type": "假日", "time": ["早上"]},
                      "relevant_contents": [62, 135]}]}
    db = qgen.DB(ROOT / "data" / "ptt.db")
    weekday = {f["id"] for f in db.pool(50, q["options"][0]["when"])}
    holiday = {f["id"] for f in db.pool(50, q["options"][1]["when"])}

    [item] = blind_input(capsys, tmp_path, q)["題目"]

    assert not keys_in(item) & FORBIDDEN
    assert [(layer["option"], layer["layer"]) for layer in item["layers"]] == [("平日早上", "exact"), ("假日早上", "exact")]
    first, second = item["layers"]
    assert set(first["judge"]) == weekday and set(second["judge"]) == holiday - weekday
    assert sorted(judged(item)) == sorted(weekday | holiday)
    shared = weekday & holiday
    assert shared
    assert {int(i): labels for i, labels in first["in_options"].items()} == {i: ["平日早上", "假日早上"] for i in shared}
    assert not second.get("in_options")


def test_blind_input_can_pick_questions(tmp_path, capsys):
    data = blind_input(capsys, tmp_path, stay_01(), {**stay_01(), "id": "stay-02"}, ids=["stay-02"])

    assert [item["id"] for item in data["題目"]] == ["stay-02"]


def blind_from_annotation(q: dict) -> dict:
    """跟標註完全一樣的盲審判斷：收的附 expect_sources 裡的引文。"""
    quotes = {int(c): t for src in q["expect_sources"] for c, t in src.items()}
    return {"relevant": {str(c): quotes[c] for c in q["relevant_contents"]}, "excluded": dict(q["excluded"])}


def blind_diff(capsys, tmp_path, *blinds: dict) -> tuple[int, list[str]]:
    questions = write_draft(tmp_path / "stay.json", stay_01())
    paths = []
    for n, b in enumerate(blinds, 1):
        paths.append(tmp_path / f"stay-blind-{n}.json")
        paths[-1].write_text(json.dumps(b, ensure_ascii=False))
    code, out = run(capsys, "blind-diff", questions, *paths)
    return code, out.splitlines()


def row(lines: list[str], label: str) -> list[int]:
    return [int(x) for x in next(line for line in lines if line.startswith(f"{label} | ")).split(" | ")[1:]]


def test_blind_diff_agrees_fully_when_the_blind_review_matches_the_annotation(tmp_path, capsys):
    code, lines = blind_diff(capsys, tmp_path, {"stay-01": blind_from_annotation(stay_01())})

    assert code == 0, "\n".join(lines)
    assert "標註＼盲審 | 收 | 不計分 | 其他不收" in lines
    assert row(lines, "收") == [2, 0, 0]
    assert row(lines, "不計分") == [0, 12, 0]
    assert row(lines, "其他不收") == [0, 0, 6]
    assert "一致率：20/20（100.0%）" in lines


def test_blind_diff_puts_a_changed_judgement_in_the_right_cell_and_lists_it(tmp_path, capsys):
    blind = blind_from_annotation(stay_01())
    del blind["excluded"]["73"]
    blind["relevant"]["73"] = "感覺很靜謐"
    # 拆成兩個檔：合併後才是完整的判斷
    first = {"stay-01": {"relevant": blind["relevant"], "excluded": {}}}
    second = {"stay-01": {"relevant": {}, "excluded": blind["excluded"]}}

    code, lines = blind_diff(capsys, tmp_path, first, second)

    assert code == 1
    assert row(lines, "收") == [2, 0, 0]
    assert row(lines, "不計分") == [0, 12, 0]
    assert row(lines, "其他不收") == [1, 0, 5]
    assert "一致率：19/20（95.0%）" in lines
    [diff] = [line for line in lines if line.startswith("stay-01 | 73 | ")]
    assert diff == "stay-01 | 73 | 標註：不收（無關） | 盲審：收 | 盲審引文：感覺很靜謐"


def test_blind_diff_lists_missed_candidates_fragments_outside_the_candidates_and_quotes_not_in_the_fragment(
        tmp_path, capsys):
    blind = blind_from_annotation(stay_01())
    del blind["excluded"]["151"]
    blind["excluded"]["87"] = "無關"
    blind["relevant"]["6"] = "晚上淺草寺人很少"

    code, lines = blind_diff(capsys, tmp_path, {"stay-01": blind})

    assert code == 1
    assert "一致率：19/19（100.0%）" in lines
    text = "\n".join(lines)
    assert "盲審漏判的候選：\nstay-01：151" in text
    assert "判了候選以外的片段：\nstay-01：87" in text
    assert "盲審引文不是片段原文的：\nstay-01 | 6 | 晚上淺草寺人很少" in text


def test_blind_diff_merges_reviews_of_several_questions(tmp_path, capsys):
    q1, q2 = stay_01(), {**stay_01(), "id": "stay-02"}
    questions = write_draft(tmp_path / "stay.json", q1, q2)
    reviews = []
    for n, q in enumerate((q1, q2), 1):
        blind = blind_from_annotation(q)
        del blind["excluded"]["151"]
        reviews.append(tmp_path / f"stay-blind-{n}.json")
        reviews[-1].write_text(json.dumps({q["id"]: blind}, ensure_ascii=False))

    code, out = run(capsys, "blind-diff", questions, *reviews)

    assert code == 1
    assert "一致率：38/38（100.0%）" in out
    assert "盲審漏判的候選：\nstay-01：151\nstay-02：151\n" in out
