"""解析 Reddit 連結、透過 Arctic Shift 抓取、寫成 data/article/reddit_<id>.json。

Arctic Shift client 沿用 scripts/reddit/reddit.py。
API 文件：https://github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md
"""
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import ARTICLE_DIR

API_BASE = "https://arctic-shift.photon-reddit.com/api"
USER_AGENT = "strag-research/0.1"
POST_FIELDS = "id,subreddit,title,author,created_utc,selftext"
COMMENT_FIELDS = "id,subreddit,author,body,created_utc,parent_id,link_id"
DELETED = {"[deleted]", "[removed]"}


class Skipped(Exception):
    """目標抓不到或已刪除，這篇略過。"""


class FetchError(Exception):
    """API 一直被限流或出錯，無法繼續。"""


# ---------- 連結 ----------

@dataclass(frozen=True)
class Target:
    post_id: str
    comment_id: str | None = None

    @property
    def kind(self) -> str:
        return "comment" if self.comment_id else "post"

    @property
    def article_id(self) -> str:
        return f"reddit_{self.comment_id or self.post_id}"


_URL_RE = re.compile(
    r"reddit\.com/(?:r/[^/]+/)?comments/(?P<post>[a-z0-9]+)"
    r"(?:/comment/(?P<c1>[a-z0-9]+)|/[^/?#]+/(?P<c2>[a-z0-9]+))?",
    re.I,
)


def parse_url(url: str) -> Target:
    m = _URL_RE.search(url)
    if not m:
        raise ValueError(f"看不懂的 Reddit 連結：{url}")
    return Target(m["post"].lower(), (m["c1"] or m["c2"] or "").lower() or None)


# ---------- Arctic Shift client ----------

def api_get(path: str, params: dict, retries: int = 6) -> list[dict]:
    url = f"{API_BASE}/{path}?" + urllib.parse.urlencode(params)
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["data"] or []
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            if e.code == 400:
                raise FetchError(f"bad request: {body}") from None
            wait = int(e.headers.get("X-RateLimit-Reset") or 20) + 3
            print(f"  {e.code} {body} -> wait {wait}s ({attempt}/{retries})", file=sys.stderr, flush=True)
            time.sleep(wait)
        except urllib.error.URLError as e:
            print(f"  {e.reason} -> wait 10s ({attempt}/{retries})", file=sys.stderr, flush=True)
            time.sleep(10)
    raise FetchError(f"Arctic Shift 重試 {retries} 次仍失敗：{path}")


def get_post(post_id: str) -> dict | None:
    data = api_get("posts/ids", {"ids": post_id, "fields": POST_FIELDS})
    return data[0] if data else None


def get_comment(comment_id: str) -> dict | None:
    data = api_get("comments/ids", {"ids": comment_id, "fields": COMMENT_FIELDS})
    return data[0] if data else None


# ---------- 文章檔 ----------

def _iso(ts) -> str:
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(text: str | None) -> str:
    text = (text or "").strip()
    return "" if text in DELETED else text


def _post_text(post: dict) -> str:
    return "\n".join(s for s in (post.get("title") or "", _clean(post.get("selftext"))) if s)


def _parents(comment: dict) -> list[str]:
    """從目標留言往上到貼文的父留言內文，由上而下；被刪的略過，封存裡沒有就停。"""
    out, parent = [], comment.get("parent_id") or ""
    while parent.startswith("t1_"):
        c = get_comment(parent[3:])
        if c is None:
            break
        if body := _clean(c.get("body")):
            out.append(body)
        parent = c.get("parent_id") or ""
    return out[::-1]


def _build(t: Target) -> dict:
    if t.kind == "post":
        post = get_post(t.post_id)
        if post is None:
            raise Skipped("封存裡沒有")
        if (post.get("selftext") or "").strip() in DELETED:
            raise Skipped("已刪除")
        text = _post_text(post)
        author, created, parents = post["author"], post["created_utc"], []
        url = f"https://www.reddit.com/r/{post['subreddit']}/comments/{t.post_id}/"
        sub = post["subreddit"]
    else:
        c = get_comment(t.comment_id)
        if c is None:
            raise Skipped("封存裡沒有")
        if not _clean(c.get("body")):
            raise Skipped("已刪除")
        post = get_post(t.post_id) or {}
        text, author, created = c["body"], c["author"], c["created_utc"]
        parents = _parents(c)
        sub = c.get("subreddit") or post.get("subreddit", "")
        url = f"https://www.reddit.com/r/{sub}/comments/{t.post_id}/comment/{t.comment_id}/"
    return {
        "id": t.article_id,
        "kind": t.kind,
        "source": "reddit",
        "subreddit": sub,
        "thread_id": t.post_id,
        "thread_title": post.get("title", ""),
        "url": url,
        "author": author,
        "created_at": _iso(created),
        "text": text,
        "post_text": _post_text(post) if post else "",
        "parents": parents,
    }


def load_article(t: Target, article_dir: Path = ARTICLE_DIR) -> dict:
    """回傳文章；已經有含 post_text／parents 的文章檔就直接讀，不重抓。"""
    path = article_dir / f"{t.article_id}.json"
    if path.exists():
        doc = json.loads(path.read_text())
        if "post_text" in doc and "parents" in doc:
            return doc
    doc = _build(t)
    article_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return doc


# ---------- 現成的文章 JSON ----------

def load_file(path: Path, ptt: bool = False) -> dict:
    """讀現成的文章 JSON（例如 data/mock_article/*.json、data/ptt_article/*.json），補齊抽取需要的欄位。

    沒有 id 時用檔名（不含 .json）當 id，例如 PTT 爬下來的 ptt_M.1794064127.A.010。
    ptt=True（CLI 的 --ptt）時，comments（PTT 推文）用 load_ptt_article 接在 text 後面；否則推文不用。
    只有 id、kind、text、title、post_text、parents（和 --ptt 併進 text 的推文）會進 prompt；
    place_name、visit_time、發文時間這類欄位不會給 LLM 看。
    """
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"讀不了 JSON：{e}") from None
    if not isinstance(doc, dict) or not (doc.get("text") or "").strip():
        raise ValueError("JSON 缺少 text")
    doc = dict(doc)
    doc["id"] = doc.get("id") or path.stem
    doc.setdefault("kind", "post")
    if doc["kind"] not in ("post", "comment"):
        raise ValueError(f"kind 只能是 post 或 comment：{doc['kind']}")
    # Reddit 貼文的 text 是「標題\n內文」，這裡比照辦理
    title = (doc.get("title") or "").strip()
    if doc["kind"] == "post" and title and not doc["text"].startswith(title):
        doc["text"] = f"{title}\n{doc['text']}"
    if ptt and isinstance(doc.get("comments"), list):
        doc["text"] = load_ptt_article(doc["text"], doc["comments"])
    doc.setdefault("post_text", "")
    doc.setdefault("parents", [])
    return doc


def load_ptt_article(text: str, comments: list[dict]) -> str:
    """PTT 文章：本文後面接「推文」段落，一行一則「user：內容」。

    PTT 一則推文太長會斷成好幾行，同一人連續的推文接成一則；空推文略過。
    推文的 tag（推／噓／→）和時間不放進去。
    """
    merged: list[list[str]] = []
    for c in comments:
        user, content = (c.get("user") or "").strip(), (c.get("content") or "").strip()
        if not content:
            continue
        if merged and merged[-1][0] == user:
            merged[-1][1] += content
        else:
            merged.append([user, content])
    if not merged:
        return text
    return text.rstrip() + "\n\n推文：\n" + "\n".join(f"{u}：{c}" for u, c in merged)
