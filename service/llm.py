"""LLM 服務：送 system/user prompt，取回符合 JSON schema 的結果。

schema 為 None 時不限制輸出格式，回傳純文字。

LLM 呼叫只在這裡，之後要換成 `claude -p` 或正式 API 只改這個檔。
"""
import os

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query


class LLMError(Exception):
    """LLM 回傳錯誤（包含額度用完），整批要停下。"""


async def call(
    system: str, user: str, schema: dict | None, model: str, effort: str | None = None
) -> dict | str:
    """effort 給值時開 adaptive thinking，effort（low/medium/high/max）決定想多深；None 維持 CLI 預設。"""
    out, _ = await call_with_usage(system, user, schema, model, effort)
    return out


async def call_with_usage(
    system: str, user: str, schema: dict | None, model: str, effort: str | None = None
) -> tuple[dict | str, int]:
    """同 `call`，另外回傳這次呼叫的輸入 token 數（含快取讀寫的 token；structured output 多輪時是各輪合計）。"""
    os.environ.pop("ANTHROPIC_API_KEY", None)  # 走訂閱額度，不走 API 計費
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        tools=[],
        strict_mcp_config=True,
        setting_sources=[],
        output_format=(
            {"type": "json_schema", "schema": schema} if schema is not None else None
        ),
        verbatim_prompts=True,
        extra_args={"no-session-persistence": None},
        **({"thinking": {"type": "adaptive"}, "effort": effort} if effort else {}),
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
    if result.is_error or (schema is not None and result.structured_output is None):
        detail = result.errors or result.result or result.subtype
        status = f" HTTP {result.api_error_status}" if result.api_error_status else ""
        raise LLMError(f"{result.subtype}{status}: {detail}")
    usage = result.usage or {}
    input_tokens = sum(usage.get(k) or 0 for k in
                       ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return (result.result or "" if schema is None else result.structured_output), input_tokens
