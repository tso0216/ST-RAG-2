"""假的 TypeSafe client：跟 `AsyncTypeSafeClient.system_one` 一樣的呼叫方式和回應型別。不打外部 API。

預設用關鍵字判斷：片段和 aspect（沒有 aspect 時用原問題）有共同的關鍵字就是 0.9，沒有就是 0.1。
`nouls` 可以指定某段內容的 noul；`fail` 為 True 時每次呼叫都丟 SDK 的連線錯誤。
"""
from typesafe_sdk import SystemOneResponse, TypeSafeAPIConnectionError

KEYWORDS = ("富士山", "排隊", "夕陽", "拉麵")


class FakeTypeSafe:
    def __init__(self, nouls: dict[str, float] | None = None, fail: bool = False):
        self.nouls = nouls or {}
        self.fail = fail
        self.calls: list[dict] = []

    async def system_one(self, state, questions, *, model=None, **_):
        self.calls.append({"model": model, "state": state, "questions": questions})
        if self.fail:
            raise TypeSafeAPIConnectionError("假的連線失敗")
        passage = state["passage"]
        topic = state.get("aspect", state["question"])
        if passage in self.nouls:
            noul = self.nouls[passage]
        else:
            noul = 0.9 if any(k in passage and k in topic for k in KEYWORDS) else 0.1
        return SystemOneResponse.model_validate({
            "model": model,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {name: {"type": "noul", "noul": noul} for name in questions},
        })

    async def aclose(self):
        pass


class ScriptedTypeSafe:
    """可以指定回傳值的假 TypeSafe client（評審用；評審的 `state` 跟相關判斷不同）。

    `respond(state, attempt)` 決定 noul：attempt 是同一個 state 第幾次被問（從 1 起算）。預設全部 0.9。
    """

    def __init__(self, respond=None):
        self.respond = respond or (lambda state, attempt: 0.9)
        self.calls: list[dict] = []
        self._seen: dict[str, int] = {}

    async def system_one(self, state, questions, *, model=None, **_):
        self.calls.append({"model": model, "state": state, "questions": questions})
        key = repr(sorted(state.items()))
        self._seen[key] = self._seen.get(key, 0) + 1
        noul = self.respond(state, self._seen[key])
        return SystemOneResponse.model_validate({
            "model": model,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {name: {"type": "noul", "noul": noul} for name in questions},
        })

    async def aclose(self):
        pass
