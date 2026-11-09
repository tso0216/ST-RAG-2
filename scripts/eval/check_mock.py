"""檢查 mock 題目集跟 main.db 的片段對不對得上：逐題用 `gold_plan` 的子查詢（地點範圍 + 時間硬過濾）找出範圍內的片段。

錯誤（結束碼 1）：
- 負例遊記的片段落進某題的範圍。
- 某題範圍內沒有正例片段。
- 片段靠 `不明` 通過子查詢限定的欄位（例如子查詢限 `平日`，片段的日別是 `不明`）。
- `relevant_contents` 的片段不存在，或不在該題的範圍內。

提醒（只列出來給人看）：
- 已經標了 `relevant_contents` 的題目，範圍內還有沒標的正例片段：檢索會撈到它，確認它不會把回答帶偏。

加 `--llm`：每題把範圍內的片段和 `expect` 交給 LLM，回報找不到的 `expect`，以及內容跟 `expect` 矛盾的片段
（會有誤判，只當參考）。

    PYTHONPATH=src:. .venv/bin/python scripts/eval/check_mock.py [--llm] [--md 片段清單.md]
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from service.nominatim import NominatimClient  # noqa: E402
from strag_v3.place import Places  # noqa: E402
from strag_v3.rag.plan import Plan  # noqa: E402
from strag_v3.rag.timematch import UNKNOWN, TimeQuery, TimeSpec  # noqa: E402

EVAL = ROOT / "data" / "mock_article" / "eval"
LLM_MODEL = "claude-sonnet-5-5"


def unknown_leaks(t: TimeQuery, c: TimeSpec) -> list[str]:
    """子查詢有限定、片段卻是 `不明` 的欄位（`matches` 會放行）。"""
    leaks = []
    if t.months is not None and c.month == UNKNOWN:
        leaks.append("月份")
    if t.day_type is not None and c.day_type == UNKNOWN:
        leaks.append("日別")
    if t.slots is not None and c.time == UNKNOWN:
        leaks.append("時段")
    return leaks


def load():
    files = {f.stem: json.loads(f.read_text()) for f in sorted(EVAL.glob("*.json"))}
    role = {}
    for d in files.values():
        role.update({a: "正" for a in d["articles"]})
        role.update({a: "負" for a in d["negative_articles"]})
    return files, role


def scan(conn, files, role):
    """逐題逐子查詢列出範圍內的片段。回傳 [(檔名, 題目, [(子查詢, TimeQuery, [片段列])])]。"""
    places = Places(conn, NominatimClient())
    rows = conn.execute("SELECT id, article_id, poi_id, poi_name, day_type, time, month, content FROM content"
                        " WHERE article_id LIKE 'mock_%' ORDER BY id").fetchall()
    out = []
    for name, d in files.items():
        for q in d["questions"]:
            subs = []
            for sq in Plan.from_dict(q["gold_plan"]).sub_queries:
                scope = places.scope(places.resolve(sq.space.name_ja, sq.space.city, sq.space.kind))
                t = sq.time or TimeQuery()
                hit = [r for r in rows if r[2] in scope and t.matches(TimeSpec(r[6], r[4], r[5]))]
                subs.append((sq, t, hit))
            out.append((name, q, subs))
    return out


def check(scanned, role, ids):
    errors, warnings = [], []
    for name, q, subs in scanned:
        label = f"{name}/{q['id']}"
        in_scope = set()
        for sq, t, hit in subs:
            for cid, aid, _, pname, dt, tm, mo, _ in hit:
                in_scope.add(cid)
                if role.get(aid) != "正":
                    errors.append(f"{label}：負例片段 {cid}（{aid}）落進範圍，{pname} {mo}/{dt}/{tm}")
                if leaks := unknown_leaks(t, TimeSpec(mo, dt, tm)):
                    errors.append(f"{label}：片段 {cid}（{aid}）的{'、'.join(leaks)}是不明，靠不明通過子查詢「{sq.space.name}」")
        if not any(role.get(r[1]) == "正" for _, _, hit in subs for r in hit):
            errors.append(f"{label}：範圍內沒有正例片段")
        for cid in q.get("relevant_contents", []):
            if cid not in ids:
                errors.append(f"{label}：relevant_contents 的 {cid} 不存在")
            elif cid not in in_scope:
                errors.append(f"{label}：relevant_contents 的 {cid} 不在範圍內（會被時間或地點過濾掉）")
        if rel := set(q.get("relevant_contents", [])):
            pos = {r[0] for _, _, hit in subs for r in hit if role.get(r[1]) == "正"}
            if extra := sorted(pos - rel):
                warnings.append(f"{label}：範圍內沒標的正例片段 {extra}")
    return errors, warnings


LLM_SYSTEM = """你是資料集審稿員。給你一題旅遊問題、答案應包含的重點（expect）、以及檢索範圍內的遊記片段（每篇遊記是不同旅客寫的）。
1. 逐條判斷每個重點能不能只靠這些片段寫出來（意思對就算，不必字面相同；需要推論才得到的算 found=false 並在 note 說明）。
   fragment_ids 填支持這個重點的片段 id。
2. 列出內容跟任何重點矛盾、回答時可能把答案帶偏的片段（conflicts）；只是多餘的資訊不算。"""
LLM_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"expect": {"type": "string"}, "found": {"type": "boolean"},
                       "fragment_ids": {"type": "array", "items": {"type": "integer"}}, "note": {"type": "string"}},
        "required": ["expect", "found", "fragment_ids", "note"]}},
        "conflicts": {"type": "array", "items": {
            "type": "object",
            "properties": {"fragment_id": {"type": "integer"}, "note": {"type": "string"}},
            "required": ["fragment_id", "note"]}}},
    "required": ["results", "conflicts"],
}


async def llm_check(scanned):
    from service.llm import call
    sem = asyncio.Semaphore(4)

    async def one(name, q, subs):
        frags = {r[0]: r for _, _, hit in subs for r in hit}
        user = (f"問題：{q['question']}\n\n重點：\n" + "\n".join(f"- {e}" for e in q["expect"]) + "\n\n片段：\n"
                + "\n".join(f"[{cid}] 遊記 {aid}｜{p} {mo}/{dt}/{tm}：{c}"
                           for cid, aid, _, p, dt, tm, mo, c in frags.values()))
        async with sem:
            out = await call(LLM_SYSTEM, user, LLM_SCHEMA, LLM_MODEL)
        label = f"{name}/{q['id']}"
        return ([f"{label}：找不到「{r['expect']}」（{r['note']}）" for r in out["results"] if not r["found"]]
                + [f"{label}：片段 {c['fragment_id']} 可能矛盾（{c['note']}）" for c in out["conflicts"]])

    results = await asyncio.gather(*(one(*s) for s in scanned))
    return [m for r in results for m in r]


def listing(scanned, role):
    out = []
    for name, q, subs in scanned:
        out.append(f"\n### {name}/{q['id']}（{q['type']}，{q['split']}）{q['question']}")
        for sq, t, hit in subs:
            out.append(f"- 子查詢：{sq.space.name} {'、'.join(t.month)}/{t.day_type or ''}/{'、'.join(t.time)}")
            out += [f"  - [{role.get(aid, '?')}] {cid} {p} {mo}/{dt}/{tm} `{aid}`：{c}"
                    for cid, aid, _, p, dt, tm, mo, c in hit]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--llm", action="store_true", help="用 LLM 檢查每條 expect 在範圍內的片段找不找得到")
    ap.add_argument("--md", type=Path, help="把逐題片段清單寫到這個檔")
    args = ap.parse_args()

    conn = sqlite3.connect(ROOT / "data" / "main.db")
    files, role = load()
    scanned = scan(conn, files, role)
    ids = {r[0] for r in conn.execute("SELECT id FROM content")}
    errors, warnings = check(scanned, role, ids)

    print(f"錯誤：{len(errors)}", *(f"  {e}" for e in errors), sep="\n")
    print(f"提醒：{len(warnings)}", *(f"  {w}" for w in warnings), sep="\n")
    if args.llm:
        missing = asyncio.run(llm_check(scanned))
        print(f"LLM（找不到的 expect、可能矛盾的片段）：{len(missing)}", *(f"  {m}" for m in missing), sep="\n")
    if args.md:
        args.md.write_text(listing(scanned, role))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
