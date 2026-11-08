"""爬 PTT Japan_Travel 最近 N 頁索引，抓所有 [問題] 文的內文（不含推文）。"""
import json, re, sys, time, urllib.request, html
BASE = "https://www.ptt.cc"
UA = {"User-Agent": "Mozilla/5.0 research-survey"}
OUT = sys.argv[1]; PAGES = int(sys.argv[2])

def get(url):
    for _ in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "replace")
        except Exception as e:
            err = e; time.sleep(2)
    raise err

page = get(f"{BASE}/bbs/Japan_Travel/index.html")
prev = int(re.search(r'href="/bbs/Japan_Travel/index(\d+)\.html">&lsaquo;', page).group(1))
posts = []
for n in range(prev + 1, prev + 1 - PAGES, -1):
    p = get(f"{BASE}/bbs/Japan_Travel/index{n}.html")
    for href, title in re.findall(r'<a href="(/bbs/Japan_Travel/M\.[^"]+)">([^<]+)</a>', p):
        title = html.unescape(title).strip()
        if title.startswith("[問題]"):
            posts.append({"url": BASE + href, "title": title})
    time.sleep(0.4)
print(f"索引 {PAGES} 頁，[問題] {len(posts)} 篇", flush=True)
for i, d in enumerate(posts):
    try:
        p = get(d["url"])
    except Exception as e:
        d["error"] = str(e); continue
    m = re.search(r'<div id="main-content"[^>]*>(.*?)<span class="f2">※ 發信站', p, re.S)
    body = m.group(1) if m else ""
    body = re.sub(r'<div class="article-metaline.*?</div>\s*</div>', "", body, flags=re.S)
    body = html.unescape(re.sub(r"<[^>]+>", "", body)).strip()
    t = re.search(r'時間</span><span class="article-meta-value">([^<]+)', p)
    d["time"] = t.group(1) if t else None
    d["body"] = body[:3000]
    if i % 25 == 0: print(i, flush=True)
    time.sleep(0.4)
json.dump(posts, open(OUT, "w"), ensure_ascii=False, indent=1)
print("done", len(posts))
