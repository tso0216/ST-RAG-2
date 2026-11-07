"""LLM 服務：送 system/user prompt，取回符合 JSON schema 的結果。

LLM 呼叫只在這裡，之後要換成 `claude -p` 或正式 API 只改這個檔。
"""
import os

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query


class LLMError(Exception):
    """LLM 回傳錯誤（包含額度用完），整批要停下。"""


async def call(system: str, user: str, schema: dict, model: str) -> dict:
    os.environ.pop("ANTHROPIC_API_KEY", None)  # 走訂閱額度，不走 API 計費
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        tools=[],
        strict_mcp_config=True,
        setting_sources=[],
        output_format={"type": "json_schema", "schema": schema},
        verbatim_prompts=True,
        extra_args={"no-session-persistence": None},
    )
    result = None
    try:
        async for msg in query(prompt=user, options=options):
            if isinstance(msg, ResultMessage):
                result = msg
    except Exception as e:
        raise LLMError(f"{type(e).__name__}: {e}") from e
    if result is None:
        raise LLMError("沒有收到結果")
    if result.is_error or result.structured_output is None:
        detail = result.errors or result.result or result.subtype
        status = f" HTTP {result.api_error_status}" if result.api_error_status else ""
        raise LLMError(f"{result.subtype}{status}: {detail}")
    return result.structured_output
