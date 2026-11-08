"""Dense retrieval baseline：只看語意分數，不管時間和地點。不打外部 API。"""
from strag_v3.rag.dense import dense_retrieve


def test_dense_takes_top_k_by_semantic_score_ignoring_time_and_place(conn, embedder, add):
    add(content="甲板很冷")
    fuji = add(month="8", time="晚上", content="富士山很清楚")
    elsewhere = add(place="淺草寺", content="富士山跟排隊")

    sections = dense_retrieve(conn, embedder, "看得到富士山嗎", 2)
    assert [e.content_id for s in sections for e in s.evidence] == [fuji, elsewhere]
