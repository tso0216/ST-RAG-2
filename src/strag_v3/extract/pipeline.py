"""主流程：連結或文章 JSON 檔 → 文章 → 抽取 → 寫入。"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..place import KINDS, NominatimClient, PlaceError, Places
from . import llm, store
from .fetch import FetchError, Skipped, load_article, load_file, parse_url

log = logging.getLogger(__name__)

TIME_RE = re.compile(r"^(?:早上|中午|下午|晚上|全天|不明)$")
_MONTH = r"(?:[1-9]|1[0-2])"
MONTH_RE = re.compile(rf"^(?:{_MONTH}|{_MONTH}-{_MONTH}|春|夏|秋|冬|不明)$")


def valid(item: dict) -> bool:
    return (
        bool(TIME_RE.match(item["time"]))
        and bool(MONTH_RE.match(item["month"]))
        and bool(item["poi_name"].strip())
        and bool(item["name_ja"].strip())
        and item["kind"] in KINDS
    )


@dataclass
class Report:
    done: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    # 地點解析不到的文章：(文章 id, 解析不到的地點)。這些文章整篇不寫入
    unresolved: list[tuple[str, list[str]]] = field(default_factory=list)
    written: int = 0
    dropped: int = 0
    error: str | None = None


async def run(urls: list[str], use_cache: bool = False, force: bool = False, nominatim=None) -> Report:
    """force=False 時，DB 已有資料的文章直接略過，不重抽。

    每筆的地點用 `place.py` 解析；有地點解析不到時，那篇整篇不寫入，記在 Report.unresolved，其他篇照跑。
    """
    r = Report()
    conn = store.connect()
    places = Places(conn, nominatim or NominatimClient())
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

            try:
                found = [places.resolve(it["name_ja"], it["city"], it["kind"], name_zh=it["poi_name"]) for it in good]
            except PlaceError as e:
                r.error, r.pending = str(e), urls[i:]
                break
            missing = [_describe(it) for it, p in zip(good, found) if p is None]
            if missing:
                r.unresolved.append((article["id"], list(dict.fromkeys(missing))))
                print(f"{article['id']}: 有地點解析不到，整篇不寫入", flush=True)
                continue
            r.written += store.replace_article(conn, article["id"], good, [p.id for p in found])
            r.done.append(url)
            print(f"{article['id']}: {len(good)} 筆{'（快取）' if cached else ''}", flush=True)
    finally:
        conn.close()
    return r


def _describe(item: dict) -> str:
    return f"{item['poi_name']}（{item['name_ja']}，{item['city'] or '不限城市'}，{item['kind']}）"
