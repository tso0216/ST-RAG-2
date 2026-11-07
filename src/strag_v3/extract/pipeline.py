"""主流程：連結或文章 JSON 檔 → 文章 → 抽取 → 寫入。"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import llm, store
from .fetch import FetchError, Skipped, load_article, load_file, parse_url

log = logging.getLogger(__name__)

_HOUR = r"(?:[0-9]|1[0-9]|2[0-3])"
TIME_RE = re.compile(rf"^(?:{_HOUR}|{_HOUR}-{_HOUR}|早上|中午|下午|晚上|全天|不明)$")
_MONTH = r"(?:[1-9]|1[0-2])"
MONTH_RE = re.compile(rf"^(?:{_MONTH}|{_MONTH}-{_MONTH}|春|夏|秋|冬|不明)$")


def valid(item: dict) -> bool:
    return (
        bool(TIME_RE.match(item["time"]))
        and bool(MONTH_RE.match(item["month"]))
        and bool(item["poi_name"].strip())
    )


@dataclass
class Report:
    done: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    written: int = 0
    dropped: int = 0
    error: str | None = None


async def run(urls: list[str], use_cache: bool = False, force: bool = False) -> Report:
    """force=False 時，DB 已有資料的文章直接略過，不重抽。"""
    r = Report()
    conn = store.connect()
    try:
        for i, url in enumerate(urls):
            try:
                if url.lower().endswith(".json"):
                    article = load_file(Path(url))
                    if not force and store.has_article(conn, article["id"]):
                        raise Skipped("DB 已有")
                else:
                    target = parse_url(url)
                    if not force and store.has_article(conn, target.article_id):
                        raise Skipped("DB 已有")
                    article = load_article(target)
            except (ValueError, Skipped) as e:
                r.skipped.append((url, str(e)))
                continue
            except FetchError as e:
                r.error, r.pending = str(e), urls[i:]
                break

            try:
                items, cached = await llm.extract(article, use_cache)
            except llm.LLMError as e:
                r.error, r.pending = str(e), urls[i:]
                break

            good = []
            for it in items:
                if valid(it):
                    good.append(it)
                else:
                    r.dropped += 1
                    log.warning("%s 丟掉格式不合的資料：%s", article["id"], it)
            r.written += store.replace_article(conn, article["id"], good)
            r.done.append(url)
            print(f"{article['id']}: {len(good)} 筆{'（快取）' if cached else ''}", flush=True)
    finally:
        conn.close()
    return r
