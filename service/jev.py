"""JEV 服務：用 TypeSafe 的 `system_one` 問一題 noul，回傳機率和實際回答的模型版本。

JEV 的呼叫只在這裡；問什麼、快取在 `strag_v3.rag.relevance`（相關判斷）和 `strag_v3.eval.baseline.judge`（評審）。
金鑰從環境變數 `TYPESAFE_API_KEY` 讀（SDK 自己讀）；重試交給 SDK 的 `RetryPolicy`，不另外包。
"""
from dataclasses import dataclass

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria, RetryPolicy, TypeSafeError

RETRIES = 3
# 問題在 `questions` 裡的預設名稱（相關判斷用）
NAME = "relevant"


class JEVError(Exception):
    """JEV 呼叫失敗（沒有金鑰、HTTP 錯誤或連線失敗，重試後仍不行）。"""


@dataclass(frozen=True)
class NoulAnswer:
    noul: float
    # 回應裡的模型名稱：實際回答的版本
    model: str


class JEVClient:
    """包住 `AsyncTypeSafeClient`；測試時傳入假的 client。"""

    def __init__(self, client=None):
        if client is None:
            try:
                client = AsyncTypeSafeClient(retry=RetryPolicy(max_retries=RETRIES))
            except TypeSafeError as e:
                raise JEVError(f"TypeSafe client 建不起來：{e}") from None
        self.client = client

    async def noul(self, model: str, state: dict, instructions: str, criteria: dict[str, str],
                   name: str = NAME) -> NoulAnswer:
        """criteria：`true`、`false` 兩個結果的描述。name：問題在 `questions` 裡的名稱。"""
        question = Noul(instructions=instructions, criteria=NoulCriteria(true=criteria["true"], false=criteria["false"]))
        try:
            r = await self.client.system_one(state=state, questions={name: question}, model=model)
        except TypeSafeError as e:
            raise JEVError(f"JEV 呼叫失敗：{type(e).__name__}: {e}") from None
        answer = r.answers.get(name)
        if answer is None or not hasattr(answer, "noul"):
            raise JEVError(f"JEV 回應裡沒有 {name} 的 noul")
        return NoulAnswer(answer.noul, r.model)

    async def aclose(self) -> None:
        await self.client.aclose()
