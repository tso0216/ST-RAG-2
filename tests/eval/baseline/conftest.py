"""baseline 測試共用：手寫的題目和片段，不讀 DB、不打外部 API。"""
import pytest

from strag_v3.eval.baseline.fragments import Fragment
from strag_v3.eval.baseline.questions import Question
from strag_v3.rag.timematch import TimeSpec


def frag(cid, month="3", day_type="平日", time="早上", place="淺草寺", text=None, article=None) -> Fragment:
    return Fragment(cid, article or f"a{cid}", place, (place,), TimeSpec(month, day_type, time), text or f"片段 {cid} 的內容")


def question(id="q1", type="停留經驗", when=None, relevant=(1, 2), articles=None, excluded=None,
             expect=("重點一", "重點二"), options=(), **extra) -> Question:
    d = {"id": id, "type": type, "question": f"問題 {id}", "when": when if when is not None else {"month": ["3"]},
         "relevant_contents": list(relevant), "relevant_articles": list(articles or [f"a{i}" for i in relevant]),
         "excluded": {str(k): v for k, v in (excluded or {}).items()}, "expect": list(expect),
         "options": list(options), **extra}
    return Question.from_dict(d)


@pytest.fixture
def fragments():
    return {i: frag(i) for i in range(1, 10)}


class KeywordEmbedder:
    """假的 embedding：每個關鍵字一維，文字含該字就是 1；全部沒命中時給一個共同的底。"""

    model = "fake-keyword"

    def __init__(self, keywords=("富士山", "排隊", "夕陽", "拉麵")):
        self.keywords = keywords

    def embed(self, texts):
        return [[1.0 if k in t else 0.0 for k in self.keywords] + [0.1] for t in texts]


@pytest.fixture
def embedder():
    return KeywordEmbedder()
