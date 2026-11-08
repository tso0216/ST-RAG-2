"""把 PTT [問題] 文拆成一個個提問，標記是否為時空問題、類別、需要的資訊來源。

用法（專案根目錄）：
PYTHONPATH=. .venv/bin/python <this> ptt_questions.json out.json
"""
import asyncio, json, sys

from service.llm import call

MODEL = "claude-sonnet-5-5"
BATCH = 8

SYSTEM = """你是旅遊研究的標註員。你會拿到幾篇 PTT 日本旅遊板的 [問題] 文（標題＋內文）。
把每篇裡旅客真正提出的問題逐一列出（一篇可能有好幾個問題；只是描述背景的句子不算）。每個問題標：

- quote：問題的原文節錄（40 字內）。
- spatial：問題牽涉具體的空間嗎（地點、區域、路線、起訖點，作為條件或答案都算；只有「日本」這種國家層級不算）。
- temporal：問題牽涉具體的時間嗎（日期、月份、季節、平日假日、星期幾、時刻、時段；作為條件或答案都算；「要待幾天」「要多久」這種耗時、天數不算）。
- category：從下列挑一個最貼切的：
  - 何時去：要決定日期、月份、季節，或某時期去適不適合。
  - 去哪：時間已定，要找去哪裡、哪裡有。
  - 排程：多個地點／活動怎麼排進一天或幾天、順序、時間夠不夠、某時間點前後接得上嗎。
  - 單點狀況：某地點在某時間的狀況（人潮、排隊、景觀、開不開、氣氛、值不值得）。
  - 移動：某時間的交通（擁擠、班次、末班車、塞車、移動時間）。
  - 限時活動：某時期才有的活動或現象（祭典、點燈、花季、紅葉、雪、煙火、市集、特定日期的營業）。
  - 天氣穿著：某地某時的天氣、氣溫、穿著。
  - 票券交通工具：買哪種票、交通方式怎麼選（跟時空無關的那種）。
  - 住宿：住哪裡、旅館選擇。
  - 其他：都不符合，用 other_desc 簡述。
- info_source：要回答這個問題，主要需要哪種資訊：
  - 經驗：要靠去過的人的親身經驗（實際人多不多、排多久、值不值得、走起來累不累、實際花多久）。
  - 官方：官網、時刻表、營業時間、票價、規定就查得到。
  - 混合：兩者都要。
- chained_time：題目裡至少有一個地點的時間是「由前後行程推出來的」，不是旅客直接給的（例如「早上逛完 A 再去 B，B 還來得及嗎」「傍晚想在 C 看夕陽，前面 A、B 要怎麼排」）。
- other_desc：category 是其他時填簡述，否則空字串。

只輸出 JSON。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quote": {"type": "string"},
                                "spatial": {"type": "boolean"},
                                "temporal": {"type": "boolean"},
                                "category": {"type": "string", "enum": [
                                    "何時去", "去哪", "排程", "單點狀況", "移動", "限時活動",
                                    "天氣穿著", "票券交通工具", "住宿", "其他"]},
                                "info_source": {"type": "string", "enum": ["經驗", "官方", "混合"]},
                                "chained_time": {"type": "boolean"},
                                "other_desc": {"type": "string"},
                            },
                            "required": ["quote", "spatial", "temporal", "category", "info_source",
                                         "chained_time", "other_desc"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["idx", "questions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}


async def main(src, dst):
    posts = [p for p in json.load(open(src)) if p.get("body")]
    sem = asyncio.Semaphore(4)

    async def one(start):
        chunk = posts[start:start + BATCH]
        user = "\n\n".join(f"=== 文章 idx={start + i} ===\n標題：{p['title']}\n{p['body'][:2500]}"
                           for i, p in enumerate(chunk))
        async with sem:
            out = await call(SYSTEM, user, SCHEMA, MODEL)
        print("batch", start, flush=True)
        return out["posts"]

    results = await asyncio.gather(*(one(s) for s in range(0, len(posts), BATCH)))
    by_idx = {r["idx"]: r["questions"] for batch in results for r in batch}
    for i, p in enumerate(posts):
        p["questions"] = by_idx.get(i)
    json.dump(posts, open(dst, "w"), ensure_ascii=False, indent=1)
    missing = sum(p["questions"] is None for p in posts)
    print("done", len(posts), "missing", missing)


asyncio.run(main(sys.argv[1], sys.argv[2]))
