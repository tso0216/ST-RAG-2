r"""PTT 旅遊版（Travel）遊記爬取工具。

usage: python3 scripts/ptt/ptt.py [--count 100] [--out data/ptt_article] [--query "[遊記]"]

用 PTT 看板搜尋（/bbs/Travel/search?q=[遊記]）由新到舊翻頁，挑標題含 [遊記] 的文章
（略過 Re: 回文），每篇存成 OUT/ptt_<文章ID>.txt，格式：

    標題：[遊記] ...
    作者：...
    時間：...
    網址：https://www.ptt.cc/bbs/Travel/M.xxxx.A.xxx.html

    文章：
    （內文）

    ----------------------------------------
    留言1: 推 someone: 內容
    留言2: → other: 內容
    ...

已存在的檔案會略過不重抓（但仍算進篇數）。
"""
import argparse
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.ptt.cc"
BOARD = "Travel"
SEPARATOR = "-" * 40
HEADERS = {"User-Agent": "Mozilla/5.0 (strag-research/0.1)"}


def get(session, url, retries=4):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  {url}: {e} -> retry in {wait}s ({attempt}/{retries})", file=sys.stderr, flush=True)
            time.sleep(wait)
    return None


def iter_search(session, query):
    """由新到舊產生 (title, url)。"""
    page = 1
    while True:
        html = get(session, f"{BASE}/bbs/{BOARD}/search?" + requests.compat.urlencode({"q": query, "page": page}))
        if not html:
            return
        soup = BeautifulSoup(html, "html.parser")
        entries = soup.select("div.r-ent div.title a")
        if not entries:
            return
        for a in entries:
            yield a.get_text(strip=True), BASE + a["href"]
        page += 1


def is_travelogue(title):
    return "[遊記]" in title and not title.lower().startswith("re:")


def parse_article(html):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("#main-content")
    if main is None:
        return None

    meta = {}
    for line in main.select("div.article-metaline, div.article-metaline-right"):
        tag = line.select_one(".article-meta-tag")
        val = line.select_one(".article-meta-value")
        if tag and val:
            meta[tag.get_text(strip=True)] = val.get_text(strip=True)
        line.decompose()

    comments = []
    for push in main.select("div.push"):
        tag = push.select_one(".push-tag")
        user = push.select_one(".push-userid")
        content = push.select_one(".push-content")
        if tag and user and content:
            text = content.get_text().lstrip(":").strip()
            comments.append(f"{tag.get_text(strip=True)} {user.get_text(strip=True)}: {text}")
        push.decompose()

    # 內嵌圖片預覽與系統訊息（發信站、編輯紀錄）不算內文
    for el in main.select("div.richcontent"):
        el.decompose()
    for el in main.select("span.f2"):
        if el.get_text().startswith("※"):
            el.decompose()

    body = main.get_text()
    # 簽名檔分隔線 "--" 之後不要
    body = re.split(r"\n--\n", body)[0]
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return meta, body, comments


def format_article(meta, body, comments, url):
    lines = [
        f"標題：{meta.get('標題', '')}",
        f"作者：{meta.get('作者', '')}",
        f"時間：{meta.get('時間', '')}",
        f"網址：{url}",
        "",
        "文章：",
        body,
        "",
        SEPARATOR,
    ]
    lines += [f"留言{i}: {c}" for i, c in enumerate(comments, 1)]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--out", default="data/ptt_article")
    ap.add_argument("--query", default="[遊記]")
    ap.add_argument("--delay", type=float, default=0.5, help="每次請求間隔秒數")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("over18", "1", domain="www.ptt.cc")

    saved, seen = 0, set()
    for title, url in iter_search(session, args.query):
        if saved >= args.count:
            break
        if url in seen or not is_travelogue(title):
            continue
        seen.add(url)
        article_id = url.rsplit("/", 1)[-1].removesuffix(".html")
        path = os.path.join(args.out, f"ptt_{article_id}.txt")
        if os.path.exists(path):
            saved += 1
            continue
        time.sleep(args.delay)
        html = get(session, url)
        parsed = parse_article(html) if html else None
        if not parsed or not parsed[1]:
            print(f"  skip {url} (deleted or empty)", file=sys.stderr)
            continue
        meta, body, comments = parsed
        with open(path, "w", encoding="utf-8") as f:
            f.write(format_article(meta, body, comments, url))
        saved += 1
        print(f"[{saved}/{args.count}] {title} ({len(comments)} 則留言)", flush=True)

    print(f"done: {saved} 篇 -> {args.out}")


if __name__ == "__main__":
    main()
