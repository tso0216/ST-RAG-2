"""mock 題目集本身的檢查：欄位齊全、gold_plan 看得懂、dev／test 的切法、遊記的引用和作者（規則見 `data/mock_article/README.md`）。

不碰 `main.db`：負例有沒有避開題目的 `when`，要等抽取完才看得出來，在 09 標註時檢查。
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from strag_v3.eval.questions import load_questions
from strag_v3.rag.plan import Plan

MOCK = Path(__file__).resolve().parents[2] / "data" / "mock_article"
EVAL = MOCK / "eval"
TYPES = {"停留", "找時間", "找地點", "比較"}


def question_files():
    return {f.stem: json.loads(f.read_text()) for f in sorted(EVAL.glob("*.json"))}


def raw_questions():
    return [(name, q) for name, data in question_files().items() for q in data["questions"]]


def test_every_question_has_the_drafted_fields():
    for name, q in raw_questions():
        missing = [k for k in ("when", "expect", "type", "split", "gold_plan") if not q.get(k)]
        assert not missing, f"{name}/{q['id']} 缺 {missing}"
        assert q["type"] in TYPES, f"{name}/{q['id']} 的題型「{q['type']}」"


@pytest.mark.parametrize("name,q", raw_questions(), ids=lambda v: v if isinstance(v, str) else v["id"])
def test_gold_plan_parses(name, q):
    Plan.from_dict(q["gold_plan"])


def test_dev_and_test_split_cover_every_type():
    questions = load_questions(EVAL)
    assert Counter(q.split for q in questions) == {"dev": 10, "test": 20}
    for split in ("dev", "test"):
        assert {q.type for q in questions if q.split == split} == TYPES, split


def test_articles_exist_and_each_belongs_to_one_place():
    on_disk = {p.stem for p in MOCK.glob("mock_*.json")}
    listed = [a for data in question_files().values() for a in data["articles"] + data["negative_articles"]]
    assert set(listed) <= on_disk
    assert [a for a, n in Counter(listed).items() if n > 1] == []
    assert on_disk - set(listed) == set(), "沒寫進任何題目檔的遊記"


def test_every_article_has_its_own_author():
    authors = Counter(json.loads(p.read_text())["author"] for p in MOCK.glob("mock_*.json"))
    assert [a for a, n in authors.items() if n > 1] == []
