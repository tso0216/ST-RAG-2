"""`.env` 載入：只補沒設定的變數。"""
import os

from service.env import load_env


def test_fills_missing_variables_only_and_strips_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# 註解\nSTRAG_TEST_A="from file"\nexport STRAG_TEST_B=b\nSTRAG_TEST_C=file\n\nnot a pair\n')
    monkeypatch.delenv("STRAG_TEST_A", raising=False)
    monkeypatch.delenv("STRAG_TEST_B", raising=False)
    monkeypatch.setenv("STRAG_TEST_C", "already set")

    load_env(env)

    assert os.environ["STRAG_TEST_A"] == "from file"
    assert os.environ["STRAG_TEST_B"] == "b"
    assert os.environ["STRAG_TEST_C"] == "already set"
    monkeypatch.delenv("STRAG_TEST_A")
    monkeypatch.delenv("STRAG_TEST_B")


def test_missing_file_is_fine(tmp_path):
    load_env(tmp_path / "nope")
