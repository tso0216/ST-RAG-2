r"""PTT 日本旅遊板（Japan_Travel）遊記爬取工具。

usage: python3 scripts/ptt/ptt.py [--count 100] [--out data/ptt_article] [--keyword 京都 [紅葉 ...]] [--restart]
       python3 scripts/ptt/ptt.py --ids M.1573263329.A.24C [...] [--out .archive/ptt_article]

給了 --ids 時不翻搜尋頁，直接抓指定的文章（文章 id 可以帶 `ptt_` 前綴），存法相同；
已存在的略過，抓不到（刪文、404）的列在最後並以 exit 1 結束。

用 PTT 看板搜尋（/bbs/Japan_Travel/search?q=[遊記]）由新到舊翻頁，挑標題含 [遊記] 的文章
（略過 Re: 回文）。

給了 --keyword 時：PTT 搜尋不支援多詞 AND，所以改用第一個關鍵字搜尋，再於本地篩出
標題同時含 [遊記] 與所有關鍵字的文章。

每篇存成 OUT/ptt_<文章ID>.json，格式：

    {
      "title": "[遊記] ...",
      "time": "Sat Jul 11 20:58:54 2026",
      "url": "https://www.ptt.cc/bbs/Japan_Travel/M.xxxx.A.xxx.html",
      "text": "（內文）",
      "comments": [
        {"tag": "推", "user": "someone", "content": "內容", "time": "07/11 21:03"},
        ...
      ]
    }

已存在的檔案會略過不重抓，也不算進 --count（--count 是「這次新抓幾篇」）。

接續爬：每次結束時把停下的搜尋頁碼記在腳本旁的 .ptt_state.json（依輸出目錄＋搜尋條件分開記），
下次同條件再跑會從該頁往前退一頁開始（新文只會把舊文往後推，退一頁是為了吸收
刪文造成的往前位移；重疊的文章會因檔案已存在而略過）。
上次之後新發的文章不在接續範圍內，要補新文請加 --restart 從第 1 頁重翻。
"""
import argparse
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.ptt.cc"
BOARD = "Japan_Travel"
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


def iter_search(session, query, page=1):
    """由新到舊產生 (page, title, url)。"""
    while True:
        html = get(session, f"{BASE}/bbs/{BOARD}/search?" + requests.compat.urlencode({"q": query, "page": page}))
        if not html:
            return
        soup = BeautifulSoup(html, "html.parser")
        entries = soup.select("div.r-ent div.title a")
        if not entries:
            return
        for a in entries:
            yield page, a.get_text(strip=True), BASE + a["href"]
        page += 1


def is_travelogue(title, keywords=()):
    if "[遊記]" not in title or title.lower().startswith("re:"):
        return False
    t = title.lower()
    return all(k.lower() in t for k in keywords)


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
        when = push.select_one(".push-ipdatetime")
        if tag and user and content:
            comments.append({
                "tag": tag.get_text(strip=True),
                "user": user.get_text(strip=True),
                "content": content.get_text().lstrip(":").strip(),
                "time": when.get_text(strip=True) if when else "",
            })
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


def to_json(meta, body, comments, url):
    return {
        "title": meta.get("標題", ""),
        "time": meta.get("時間", ""),
        "url": url,
        "text": body,
        "comments": comments,
    }


STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ptt_state.json")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(STATE_PATH)))


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    path = STATE_PATH
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(path + ".tmp", path)


def fetch_ids(session, ids, out, delay):
    """抓指定的文章；回傳 0（全部有了）或 1（有抓不到的）。"""
    failed = []
    for raw in ids:
        article_id = raw.removeprefix("ptt_")
        path = os.path.join(out, f"ptt_{article_id}.json")
        if os.path.exists(path):
            continue
        url = f"{BASE}/bbs/{BOARD}/{article_id}.html"
        time.sleep(delay)
        html = get(session, url)
        parsed = parse_article(html) if html else None
        if not parsed or not parsed[1]:
            failed.append(article_id)
            print(f"  抓不到 {url}", file=sys.stderr, flush=True)
            continue
        meta, body, comments = parsed
        with open(path, "w", encoding="utf-8") as f:
            json.dump(to_json(meta, body, comments, url), f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{article_id}：{meta.get('標題', '')} ({len(comments)} 則留言)", flush=True)
    print(f"done: 指定 {len(ids)} 篇，抓不到 {len(failed)} 篇" + (f"：{' '.join(failed)}" if failed else ""), flush=True)
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--out", default="data/ptt_article")
    ap.add_argument("--keyword", nargs="+", default=[], help="標題須含的關鍵字（可多個，全部都要符合）")
    ap.add_argument("--restart", action="store_true", help="忽略上次停下的頁碼，從第 1 頁開始")
    ap.add_argument("--delay", type=float, default=0.5, help="每次請求間隔秒數")
    ap.add_argument("--ids", nargs="+", default=[], help="直接抓這些文章 id，不翻搜尋頁")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("over18", "1", domain="www.ptt.cc")
    if args.ids:
        sys.exit(fetch_ids(session, args.ids, args.out, args.delay))

    saved, seen = 0, set()
    query = args.keyword[0] if args.keyword else "[遊記]"
    out_rel = os.path.relpath(os.path.abspath(args.out), REPO_ROOT)
    state_key = json.dumps({"out": out_rel, "q": query, "keyword": args.keyword}, ensure_ascii=False, sort_keys=True)
    state = load_state()
    start = 1 if args.restart else max(1, state.get(state_key, 1) - 1)
    if start > 1:
        print(f"接續上次：從第 {start} 頁開始（--restart 可從頭）", flush=True)
    page = start
    exhausted = False
    try:
        for page, title, url in iter_search(session, query, start):
            if url in seen or not is_travelogue(title, args.keyword):
                continue
            seen.add(url)
            article_id = url.rsplit("/", 1)[-1].removesuffix(".html")
            path = os.path.join(args.out, f"ptt_{article_id}.json")
            if os.path.exists(path):
                continue
            time.sleep(args.delay)
            html = get(session, url)
            parsed = parse_article(html) if html else None
            if not parsed or not parsed[1]:
                print(f"  skip {url} (deleted or empty)", file=sys.stderr)
                continue
            meta, body, comments = parsed
            with open(path, "w", encoding="utf-8") as f:
                json.dump(to_json(meta, body, comments, url), f, ensure_ascii=False, indent=2)
                f.write("\n")
            saved += 1
            print(f"[{saved}/{args.count}] {title} ({len(comments)} 則留言)", flush=True)
            if saved >= args.count:
                break
        else:
            exhausted = True
    finally:
        # 中途 Ctrl+C 或出錯也記下頁碼，下次可接續
        state[state_key] = page
        save_state(state)
        print(f"done: 新抓 {saved} 篇 -> {args.out}（停在第 {page} 頁）", flush=True)
    if exhausted:
        print("已翻到搜尋結果最後一頁；要補新文請加 --restart", flush=True)

if __name__ == "__main__":
    main()
