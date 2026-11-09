import json

from strag_v3.extract.fetch import load_file, load_ptt_article


def test_ptt_json_without_id_uses_file_name_and_title(tmp_path):
    p = tmp_path / "ptt_M.1794064127.A.010.json"
    p.write_text(json.dumps({
        "title": "[遊記] 奧入瀨自駕",
        "time": "Sat Nov  7 23:08:44 2026",
        "url": "https://www.ptt.cc/bbs/Japan_Travel/M.1794064127.A.010.html",
        "text": "造訪日期：2026-11-01",
        "comments": [{"tag": "推", "user": "u", "content": "推", "time": "11/08 17:06"}],
    }, ensure_ascii=False))

    doc = load_file(p)

    assert doc["id"] == "ptt_M.1794064127.A.010"
    assert doc["kind"] == "post"
    assert doc["text"] == "[遊記] 奧入瀨自駕\n造訪日期：2026-11-01"
    assert doc["post_text"] == "" and doc["parents"] == []

    assert load_file(p, ptt=True)["text"] == "[遊記] 奧入瀨自駕\n造訪日期：2026-11-01\n\n推文：\nu：推"


def test_ptt_comments_merge_consecutive_lines_of_same_user():
    comments = [
        {"tag": "推", "user": "a", "content": "不懂為何突然積雪，氣象預報還", "time": "11/08 17:06"},
        {"tag": "→", "user": "a", "content": "不太準", "time": "11/08 17:06"},
        {"tag": "推", "user": "b", "content": "", "time": "11/08 17:07"},
        {"tag": "推", "user": "b", "content": "好美", "time": "11/08 17:08"},
    ]
    assert load_ptt_article("本文\n", comments) == "本文\n\n推文：\na：不懂為何突然積雪，氣象預報還不太準\nb：好美"
    assert load_ptt_article("本文", []) == "本文"


def test_explicit_id_wins_over_file_name(tmp_path):
    p = tmp_path / "whatever.json"
    p.write_text(json.dumps({"id": "mock_1", "text": "遊記"}))
    assert load_file(p)["id"] == "mock_1"
