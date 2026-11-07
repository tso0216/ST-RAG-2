r"""Reddit 經驗文爬取工具（透過 Arctic Shift 封存 API），單一入口、四個子命令。

usage: python3 scripts/reddit/reddit.py <command> ...

  search  用關鍵字找貼文，印出貼文 ID（大版很慢，會被限流）
  fetch   用貼文 ID 抓整串貼文與留言，存成 RAW_DIR/<post_id>.json（快）
  find    在抓下來的串裡，用地點／時間 regex 篩出候選內容供人工判斷
  export  把挑好的貼文或留言 ID 寫成 data/article/reddit_<id>.json

典型流程：
  python3 scripts/reddit/reddit.py fetch  data/raw/reddit 1erb8kc 1hnpg57
  python3 scripts/reddit/reddit.py find   data/raw/reddit --place 'fushimi|inari' --time '\b[4-8](:[0-5]\d)?\s?am\b|sunrise'
  python3 scripts/reddit/reddit.py export data/raw/reddit m48ay8l li6kqt0

貼文 ID 是 Reddit 網址 /comments/ 後面那段，例如 1erb8kc。
API 文件：https://github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md
用 ID 查（posts/ids、comments/search?link_id=）很便宜；關鍵字查（posts/search?query=）
在 r/JapanTravel 這種大版很貴，伺服器會回 422「Timeout. Maybe slow down a bit」，
這裡會照 X-RateLimit-Reset 等待後重試。
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://arctic-shift.photon-reddit.com/api"
USER_AGENT = "strag-research/0.1"
POST_FIELDS = "id,subreddit,title,author,created_utc,num_comments,selftext,url"
COMMENT_FIELDS = "id,author,body,created_utc,parent_id,score"


# ---------- Arctic Shift client ----------

def api_get(path, params, retries=6):
    """GET API_BASE/path，回傳 data list；每次重試都被限流則回傳 None。"""
    url = f"{API_BASE}/{path}?" + urllib.parse.urlencode(params)
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["data"] or []
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            if e.code == 400:
                raise ValueError(f"bad request: {body}") from None
            wait = int(e.headers.get("X-RateLimit-Reset") or 20) + 3
            print(f"  {e.code} {body} -> wait {wait}s ({attempt}/{retries})", file=sys.stderr, flush=True)
            time.sleep(wait)
    return None


def posts_by_ids(ids):
    return {p["id"]: p for p in api_get("posts/ids", {"ids": ",".join(ids), "fields": POST_FIELDS}) or []}


def comments_of(link_id):
    """一篇貼文的全部留言，依 created_utc 分頁。"""
    out, seen, after = [], set(), None
    while True:
        params = {"link_id": link_id, "limit": 100, "sort": "asc", "fields": COMMENT_FIELDS}
        if after:
            params["after"] = after
        page = api_get("comments/search", params)
        if page is None:
            raise RuntimeError(f"rate limited while fetching comments of {link_id}")
        new = [c for c in page if c["id"] not in seen]
        out += new
        seen.update(c["id"] for c in new)
        if len(page) < 100 or not new:
            return out
        after = page[-1]["created_utc"]
        time.sleep(1)


# ---------- thread files ----------

def load_threads(raw_dir):
    for fn in sorted(glob.glob(os.path.join(raw_dir, "*.json"))):
        with open(fn) as f:
            yield json.load(f)


def thread_items(thread):
    """(item_id, kind, author, created_utc, text)，貼文本身加上每則留言。"""
    p = thread["post"]
    yield p["id"], "post", p["author"], p["created_utc"], f"{p['title']}\n{p.get('selftext') or ''}"
    for c in thread["comments"]:
        yield c["id"], "comment", c["author"], c["created_utc"], c["body"] or ""


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def thread_articles(thread):
    """(item_id, article dict)，article 即 data/article 的格式。"""
    p = thread["post"]
    sub, tid = p["subreddit"], p["id"]
    base = {"source": "reddit", "subreddit": sub, "thread_id": tid, "thread_title": p["title"]}
    yield tid, {"id": f"reddit_{tid}", "kind": "post", **base,
                "url": f"https://www.reddit.com/r/{sub}/comments/{tid}/",
                "author": p["author"], "created_at": iso(p["created_utc"]), "text": p.get("selftext") or ""}
    for c in thread["comments"]:
        yield c["id"], {"id": f"reddit_{c['id']}", "kind": "comment", **base,
                        "url": f"https://www.reddit.com/r/{sub}/comments/{tid}/comment/{c['id']}/",
                        "author": c["author"], "created_at": iso(c["created_utc"]), "text": c["body"] or ""}


# ---------- commands ----------

def months(start, end):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01"
        y, m = ny, nm


def cmd_search(a):
    windows = list(months(*a.months)) if a.months else [(None, None)]
    out = open(a.out, "a") if a.out else None
    for after, before in windows:
        params = {"subreddit": a.subreddit, "query": a.query, "limit": 100, "fields": POST_FIELDS}
        if after:
            params.update(after=after, before=before)
        data = api_get("posts/search", params)
        label = after or "all time"
        if data is None:
            print(f"== {label}: FAILED (rate limited)", flush=True)
            continue
        print(f"== {label}: {len(data)}{' (capped at 100)' if len(data) == 100 else ''}", flush=True)
        for p in data:
            print(p["id"], p["num_comments"], datetime.date.fromtimestamp(p["created_utc"]), p["title"][:90], flush=True)
            if out:
                out.write(json.dumps(p, ensure_ascii=False) + "\n")
        time.sleep(3)


def cmd_fetch(a):
    os.makedirs(a.raw_dir, exist_ok=True)
    posts = posts_by_ids(a.post_ids)
    for pid in a.post_ids:
        if pid not in posts:
            print(f"{pid}: not found in archive", flush=True)
            continue
        comments = comments_of(pid)
        with open(os.path.join(a.raw_dir, f"{pid}.json"), "w") as f:
            json.dump({"post": posts[pid], "comments": comments}, f, ensure_ascii=False)
        print(f"{pid}: {len(comments)} comments | r/{posts[pid]['subreddit']} | {posts[pid]['title'][:70]}", flush=True)
        time.sleep(1)


def cmd_find(a):
    place = re.compile(a.place, re.I)
    when = re.compile(a.time, re.I) if a.time else None
    hits = 0
    for thread in load_threads(a.raw_dir):
        tid = thread["post"]["id"]
        for iid, kind, author, ts, text in thread_items(thread):
            m = place.search(text)
            if not m or (when and not when.search(text)):
                continue
            hits += 1
            s = max(0, m.start() - a.context)
            snippet = text[s:m.end() + a.context * 2].replace("\n", " ")
            print(f"== {iid} ({kind} in {tid}) u/{author} {datetime.date.fromtimestamp(ts)}\n{snippet}\n")
    print(f"{hits} matches")


def cmd_export(a):
    wanted = set(a.item_ids)
    os.makedirs(a.out, exist_ok=True)
    for thread in load_threads(a.raw_dir):
        for iid, doc in thread_articles(thread):
            if iid in wanted:
                with open(os.path.join(a.out, f"{doc['id']}.json"), "w") as f:
                    json.dump(doc, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                print("wrote", doc["id"])
                wanted.discard(iid)
    if wanted:
        print("not found in", a.raw_dir, ":", " ".join(sorted(wanted)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="用關鍵字找貼文（標題＋內文）",
                       description="語法：a b 兩字都要有；\"a b\" 片語；a OR b；a -b。結果上限 100 筆，--months 可逐月查。")
    s.add_argument("subreddit")
    s.add_argument("query")
    s.add_argument("--months", nargs=2, metavar=("START", "END"), help="YYYY-MM YYYY-MM，逐月查")
    s.add_argument("--out", help="把原始貼文附加寫入 JSONL")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("fetch", help="用貼文 ID 抓整串貼文與留言")
    s.add_argument("raw_dir", help="輸出資料夾，每串存成 <post_id>.json")
    s.add_argument("post_ids", nargs="+")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("find", help="用地點／時間 regex 篩出候選內容（不分大小寫）")
    s.add_argument("raw_dir")
    s.add_argument("--place", required=True, help="地點 regex，例：'fushimi|inari'")
    s.add_argument("--time", help="時間 regex，例：'\\b[4-8](:[0-5]\\d)?\\s?am\\b|sunrise'")
    s.add_argument("--context", type=int, default=400, help="地點前後顯示的字數")
    s.set_defaults(func=cmd_find)

    s = sub.add_parser("export", help="把挑好的貼文／留言 ID 寫成 data/article 格式",
                       description="每則寫成 <out>/reddit_<id>.json，不含標註；證據標註放 src/strag_v3/eval/question/questions.json。")
    s.add_argument("raw_dir")
    s.add_argument("item_ids", nargs="+", help="find 印出的貼文或留言 ID")
    s.add_argument("--out", default="data/article")
    s.set_defaults(func=cmd_export)

    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
