"""主流程：連結或文章 JSON 檔 → 文章 → 抽取 → 寫入。"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from service.nominatim import NominatimClient

from ..place import ANY, KINDS, PlaceError, Places
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


async def run(urls: list[str], use_cache: bool = False, force: bool = False, nominatim=None,
              ptt: bool = False, db_path: Path = store.DB_PATH, jobs: int = 1) -> Report:
    """force=False 時，DB 已有資料的文章直接略過，不重抽。ptt=True 時文章 JSON 的推文接在本文後面一起抽。

    jobs 是同時抽取的篇數（下載與 LLM 並行）；驗證、地點解析、寫入仍逐篇進行，順序是誰先抽完誰先寫。
    任一篇遇到 FetchError／LLMError／PlaceError 就取消其他篇，整批停下，沒寫入的列在 Report.pending。

    每筆的地點用 `place.py` 解析，解析不到就拿掉城市和種類再查一次；仍解析不到時，那篇整篇不寫入，記在 Report.unresolved，其他篇照跑。
    """
    r = Report()
    conn = store.connect(db_path)
    places = Places(conn, nominatim or NominatimClient())
    try:
        queue = _queue(urls, conn, r, force, ptt)
        sem = asyncio.Semaphore(jobs)

        async def work(url: str, src):
            """回傳 (url, article, items, cached)；出錯時回傳 (url, 例外)，好知道是哪篇。"""
            async with sem:
                try:
                    article = src if isinstance(src, dict) else await asyncio.to_thread(load_article, src)
                    items, cached = await llm.extract(article, use_cache)
                except (Skipped, FetchError, llm.LLMError) as e:
                    return url, e
                return url, article, items, cached

        tasks = [asyncio.create_task(work(url, src)) for url, src in queue]
        handled = set()
        try:
            for fut in asyncio.as_completed(tasks):
                url, *out = await fut
                if isinstance(out[0], Skipped):
                    r.skipped.append((url, str(out[0])))
                elif isinstance(out[0], Exception):
                    r.error = str(out[0])
                    break
                else:
                    try:
                        _write(conn, places, r, url, *out)
                    except PlaceError as e:
                        r.error = str(e)
                        break
                handled.add(url)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if r.error:
            r.pending = [url for url, _ in queue if url not in handled]
    finally:
        conn.close()
    return r


def _queue(urls: list[str], conn, r: Report, force: bool, ptt: bool) -> list[tuple[str, object]]:
    """逐篇讀檔或解析連結，略過 DB 已有和重複的；回傳要抽的 (url, 文章 dict 或 Target)。"""
    queue, seen = [], set()
    for url in urls:
        try:
            if url.lower().endswith(".json"):
                src = load_file(Path(url), ptt=ptt)
                article_id = src["id"]
            else:
                src = parse_url(url)
                article_id = src.article_id
            if article_id in seen:
                raise Skipped("重複")
            if not force and store.has_article(conn, article_id):
                raise Skipped("DB 已有")
        except (ValueError, Skipped) as e:
            r.skipped.append((url, str(e)))
            continue
        seen.add(article_id)
        queue.append((url, src))
    return queue


def _write(conn, places: Places, r: Report, url: str, article: dict, items: list[dict], cached: bool) -> None:
    good = []
    for it in items:
        if valid(it):
            good.append(it)
        else:
            r.dropped += 1
            log.warning("%s 丟掉格式不合的資料：%s", article["id"], it)

    found = [_resolve(places, it) for it in good]
    missing = [_describe(it) for it, p in zip(good, found) if p is None]
    if missing:
        r.unresolved.append((article["id"], list(dict.fromkeys(missing))))
        print(f"{article['id']}: 有地點解析不到，整篇不寫入", flush=True)
        return
    r.written += store.replace_article(conn, article["id"], good, [p.id for p in found])
    r.done.append(url)
    print(f"{article['id']}: {len(good)} 筆{'（快取）' if cached else ''}", flush=True)


def _describe(item: dict) -> str:
    return f"{item['poi_name']}（{item['name_ja']}，{item['city'] or '不限城市'}，{item['kind']}）"


def _resolve(places: Places, item: dict):
    """先照城市和種類查；查不到就拿掉城市和種類，取 Nominatim 的第一筆，不再檢查對不對。"""
    return (places.resolve(item["name_ja"], item["city"], item["kind"], name_zh=item["poi_name"])
            or places.resolve(item["name_ja"], None, ANY, name_zh=item["poi_name"]))
