"""`eval.full compare`：並排比較結果檔，舊的結果檔（沒有 gate、證據欄位叫 semantic）照樣讀得懂。"""
import json

from strag_v3.eval.full.__main__ import main

METRICS = {"n": 2, "recall": 0.98, "precision": 0.82, "f1": 0.89}


def write(path, config, evidence_key):
    path.write_text(json.dumps({
        "config": config,
        "summary": {"overall": METRICS, "by_split": {"dev": METRICS}, "by_type": {}},
        "questions": [{"sections": [{"groups": [{"evidence": [{"content_id": 1, evidence_key: 0.5}]}]}]}],
    }, ensure_ascii=False))
    return path


def test_old_run_without_gate_is_labelled_semantic_next_to_a_jev_run(tmp_path, capsys):
    old = write(tmp_path / "old.json", {"name": "full", "answer": True, "judge": False, "params": {"delta": 0.3}},
                "semantic")
    new = write(tmp_path / "new.json", {"name": "full", "answer": True, "judge": False, "gate": "jev",
                                        "jev_model": "jev-1.14.0", "params": {}}, "relevance")

    assert main(["compare", str(old), str(new)]) == 0

    out = capsys.readouterr().out
    assert "full-semantic（old）" in out and "full-jev（new）" in out
    assert "0.820" in out
