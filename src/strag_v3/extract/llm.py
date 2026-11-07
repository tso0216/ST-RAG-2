"""讀 prompts/、組訊息、呼叫 LLM（structured output）、快取。

實際的 LLM 呼叫在 `service/llm.py`（專案根目錄）。
"""
import hashlib
import json
from pathlib import Path

from service.llm import LLMError, call
from .paths import CACHE_DIR, PROMPT_DIR

__all__ = ["LLMError", "extract", "prompt_version", "build_messages"]

MODEL = "claude-sonnet-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "poi_name": {"type": "string"},
                    "day_type": {"type": "string", "enum": ["平日", "假日", "不明"]},
                    "time": {"type": "string"},
                    "month": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["poi_name", "day_type", "time", "month", "content"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

PARENT_SEP = "\n\n---\n\n"


def _prompt_files() -> list[Path]:
    return sorted(p for p in PROMPT_DIR.iterdir() if p.is_file())


def prompt_version() -> str:
    h = hashlib.sha256(MODEL.encode())
    for p in _prompt_files():
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def build_messages(article: dict) -> tuple[str, str]:
    system = (PROMPT_DIR / "system.md").read_text()
    template = (PROMPT_DIR / "user.md").read_text()
    is_post = article["kind"] == "post"
    user = template.format(
        post="" if is_post else article.get("post_text", ""),
        parents=PARENT_SEP.join(article.get("parents", [])),
        target=article["text"],
    )
    return system, user


async def extract(article: dict, use_cache: bool = False) -> tuple[list[dict], bool]:
    """回傳 (items, 是否來自快取)。use_cache=False 時一律重新呼叫 LLM，但結果照樣寫進快取。"""
    cache = CACHE_DIR / f"{article['id']}.{prompt_version()}.json"
    if use_cache and cache.exists():
        return json.loads(cache.read_text())["items"], True
    system, user = build_messages(article)
    out = await call(system, user, SCHEMA, MODEL)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return out["items"], False
