"""原文段的切法：一篇原文（內文加推文）進，原文段出。"""
from strag_v3.eval.baseline.chunks import split_article


def article(*paragraphs, comments=()):
    return {"text": "\n\n".join(paragraphs), "comments": [{"tag": "推", "user": u, "content": c} for u, c in comments]}


def test_short_article_is_one_chunk_with_body_and_comments():
    chunks = split_article(article("第一段。", "第二段。", comments=[("amy", "好美"), ("bob", "推")]))

    assert len(chunks) == 1
    assert "第一段。" in chunks[0] and "第二段。" in chunks[0]
    assert "amy：好美" in chunks[0] and "bob：推" in chunks[0]


def test_chunks_break_at_paragraph_boundaries_and_stay_near_the_size():
    paras = [f"{i}" * 180 for i in range(1, 7)]  # 六段各 180 字

    chunks = split_article(article(*paras), size=500, overlap=100)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 500 + 100 + 1
        # 除了開頭的重疊，每段都是完整的段落
        body = c.split("\n", 1)[1] if c is not chunks[0] else c
        assert all(line in paras for line in body.split("\n"))


def test_consecutive_chunks_overlap_by_about_100_characters():
    paras = [f"{i}" * 180 for i in range(1, 7)]

    chunks = split_article(article(*paras), size=500, overlap=100)

    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.startswith(prev[-100:])


def test_paragraph_longer_than_the_size_is_cut_into_overlapping_windows():
    long = "".join(chr(0x4E00 + i) for i in range(1200))

    chunks = split_article(article(long), size=500, overlap=100)

    assert all(len(c) <= 500 + 100 + 1 for c in chunks)
    joined = chunks[0]
    for c in chunks[1:]:
        assert c[:100] == joined[-100:]
        joined += c[100:].lstrip("\n")
    assert long in joined.replace("\n", "")


def test_comments_are_packed_one_per_line_after_the_body():
    comments = [(f"u{i}", "留言" * 20) for i in range(30)]

    chunks = split_article(article("內文" * 10, comments=comments), size=500, overlap=100)

    text = "".join(chunks)
    assert chunks[0].startswith("內文")
    assert all(f"u{i}：" in text for i in range(30))
