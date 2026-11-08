"""重抓每篇文章的推文，拆成 tag / user / content / time，寫回 questions_classified.json 的 pushes。

用法（專案根目錄）：python3 .scratch/travel-question-survey/crawl_pushes.py data/ptt_japan_travel/questions_classified.json
"""
import html, json, re, sys, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0 research-survey"}
PUSH = re.compile(
    r'<div class="push">\s*<span[^>]*push-tag">(.*?)</span>\s*<span[^>]*push-userid">(.*?)</span>'
    r'\s*<span[^>]*push-content">(.*?)</span>\s*<span[^>]*push-ipdatetime">(.*?)</span>', re.S)
DATE = re.compile(r'(\d{2}/\d{2}(?: \d{2}:\d{2})?)')


def get(url):
    for _ in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "replace")
        except Exception as e:
            err = e; time.sleep(2)
    raise err


def parse(page):
    out = []
    for tag, user, content, ipdt in PUSH.findall(page):
        content = html.unescape(re.sub(r"<[^>]+>", "", content)).strip()
        content = content[1:].strip() if content.startswith(":") else content
        m = DATE.search(ipdt)  # 只留日期時間，不留 IP
        out.append({"tag": html.unescape(tag).strip(), "user": html.unescape(user).strip(),
                    "content": content, "time": m.group(1) if m else ""})
    return out


path = sys.argv[1]
posts = json.load(open(path))
for i, p in enumerate(posts):
    p["pushes"] = parse(get(p["url"]))
    if i % 25 == 0: print(i, flush=True)
    time.sleep(0.4)
json.dump(posts, open(path, "w"), ensure_ascii=False, indent=1)
print("done", len(posts), "pushes", sum(len(p["pushes"]) for p in posts))
