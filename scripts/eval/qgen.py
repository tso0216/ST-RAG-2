"""出題工具（配合 `src/strag_v3/eval/questions/generate.md`）：候選片段、題目檔驗證、評審校準。

候選片段和檢索用同一套規則（`Places.scope`、`TimeQuery.matches`、`TimeQuery.widened`、`Places.outer`），
所以「哪些片段要判」由程式決定，不靠人工篩。DB 以唯讀開啟；評審校準的快取放記憶體，不寫進 DB。

    python scripts/eval/qgen.py places [--min 3]               # 有片段的地點（id、種類、名稱、片段數）
    python scripts/eval/qgen.py areas                           # 有範圍的區域，和範圍內的片段數（找地點題用）
    python scripts/eval/qgen.py pool 50 --when '{"month": ["3"], "time": ["晚上"]}' [--widen]
    python scripts/eval/qgen.py outer 50                        # 空間退讓會去的外圍行政區
    python scripts/eval/qgen.py check <題目檔>...               # 機械檢查，全部通過才 exit 0
    python scripts/eval/qgen.py plan <題目檔>...                # 讓 planner 只讀題目文字，比對還原出的地點和時間
    python scripts/eval/qgen.py answer <題目檔> <題目 id>       # 只用證據原句拼成的正向答案
    python scripts/eval/qgen.py calibrate <題目檔> --negatives <反向答案.json>   # 用真正的評審校準 expect
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from strag_v3.place import Places  # noqa: E402
from strag_v3.rag.plan import parse_time  # noqa: E402
from strag_v3.rag.timematch import TimeSpec, months_of  # noqa: E402

TYPES = ("停留經驗", "移動經驗", "找地點", "找時間", "比較")
COVERAGES = ("exact", "time_backoff", "space_backoff", "none")
REASONS = ("無關", "別處", "時間矛盾", "時間不明")
FIELDS = ("id", "article", "poi_id", "poi", "month", "day_type", "time", "content")
SELECT = "SELECT id, article_id, poi_id, poi_name, month, day_type, time, content FROM content"
MAX_RELEVANT = 8
MAX_POINTS = 8
# 一個題型（一個檔）內的上限
MAX_NON_EXACT = 2      # 退讓題和 none 題
MAX_SINGLE = 3         # 只收一個片段的題目
MAX_PER_PLACE_TYPE = 2
MAX_PER_PLACE = 6      # 跨題型
NEEDS_WHEN = ("停留經驗", "移動經驗", "找地點")  # 時間是條件的題型
# 原句沒有、卻出現在 expect 裡就算錯的詞：推論、概括、建議、對答案的要求
HEDGES = ("通常", "大多", "大部分", "一般", "往往", "總是", "可能", "不一定", "建議", "應該", "最好",
          "結論", "總之", "整體", "倍", "要說明", "要講明", "要指出", "不能", "無法判斷")
NUM = re.compile(r"\d+(?:[.:]\d+)?")
ZH_NUM = re.compile(r"[一二三四五六七八九十兩]+\s*(?:月|點|分|小時|人|成|度|筆|號|日)")


class DB:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.places = Places(self.conn)  # 沒給 nominatim：只讀 DB，不打網路
        self._layers: dict = {}

    def frag(self, cid: int) -> dict:
        r = self.conn.execute(f"{SELECT} WHERE id = ?", (cid,)).fetchone()
        if r is None:
            raise KeyError(f"沒有片段 {cid}")
        return dict(zip(FIELDS, r))

    def pool(self, place_id: int, when: dict | None = None, widen: bool = False) -> list[dict]:
        """跟檢索同一套規則的候選：景點只取自己，區域取範圍內所有地點；時間照 TimeQuery.matches（不明算相符）。
        widen=True 是時間退讓的條件（時段、月份各往外擴一格）。
        每筆附 `unknown_dims`：題目有限定、片段卻標成不明的維度（沒限定的維度不明不算）。"""
        ids = sorted(self.places.scope(self.places.get(place_id)))
        q = parse_time(when)
        if widen:
            q = q.widened() if q else None
        rows = self.conn.execute(f"{SELECT} WHERE poi_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)
        out = []
        for r in rows:
            f = dict(zip(FIELDS, r))
            if q is None or q.matches(TimeSpec(f["month"], f["day_type"], f["time"])):
                out.append({**f, "unknown_dims": unknown_dims(f, when, widen=widen)})
        return out

    def content_places(self) -> list:
        return [self.places.get(pid) for (pid,) in self.conn.execute("SELECT DISTINCT poi_id FROM content")]

    def outer(self, place_id: int) -> int | None:
        o = self.places.outer(self.places.get(place_id))
        return o.id if o else None

    def layers(self, place_id: int, when: dict | None) -> list[tuple[str, set[int]]]:
        """檢索依序嘗試的候選，跟 Retriever._retrieve_one 同順序：原條件 → 時間退讓 → 空間退讓（用原本的時間）。
        時間不限就沒有時間退讓那層，沒有外圍行政區就沒有空間退讓那層。"""
        key = (place_id, json.dumps(when, sort_keys=True))
        if key not in self._layers:
            out = [("exact", {f["id"] for f in self.pool(place_id, when)})]
            if (q := parse_time(when)) and q.widened():
                out.append(("time_backoff", {f["id"] for f in self.pool(place_id, when, widen=True)}))
            if (o := self.outer(place_id)) is not None:
                out.append(("space_backoff", {f["id"] for f in self.pool(o, when)}))
            self._layers[key] = out
        return self._layers[key]

    def must_judge(self, space: dict, when: dict | None, coverage: str) -> set[int]:
        """必須逐筆判過的候選：從原條件試到 coverage 那層為止的所有候選（none 是每一層）。"""
        lay = self.layers(space["place_id"], when)
        names = [n for n, _ in lay]
        stop = names.index(coverage) + 1 if coverage in names else len(lay)
        return set().union(*(ids for _, ids in lay[:stop]))


DIMS = {"month": "月份", "day_type": "平日／假日", "time": "時段"}


def unknown_dims(f: dict, when: dict | None, asks: str | None = None, widen: bool = False) -> list[str]:
    """題目限定的維度（when 有填的，加上找時間題問的 asks）裡，片段說不準是否符合的：
    標成不明，或月份標籤比條件粗、不完全落在條件裡（例：問 3 月，片段標「春」，可能是 4、5 月）。
    widen=True 時用時間退讓後的條件判斷。"""
    q = parse_time(when)
    if widen and q:
        q = q.widened()
    out = []
    if q and q.months is not None and (f["month"] == "不明" or not set(months_of(f["month"])) <= q.months):
        out.append("月份" if f["month"] == "不明" else f"月份（標「{f['month']}」比條件粗）")
    elif asks == "month" and f["month"] == "不明":
        out.append("月份")
    if (q and q.day_type or asks == "day_type") and f["day_type"] == "不明":
        out.append("平日／假日")
    if (q and q.slots is not None or asks == "time") and f["time"] == "不明":
        out.append("時段")
    return out


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def when_text(f: dict) -> str:
    """片段的時間標籤寫成一句話（不明的維度不寫）。"""
    m = f["month"]
    month = "" if m == "不明" else f"{m} 月" if m[0].isdigit() else f"{m}天"
    parts = [month, *(x for x in (f["day_type"], f["time"]) if x != "不明")]
    return " ".join(p for p in parts if p) or "時間沒寫"


# ---------- 驗證 ----------

def check(db: DB, q: dict) -> list[str]:
    """一題的機械檢查；回傳錯誤清單，空的才算通過。"""
    k = q.get("id", "?")
    e: list[str] = []
    try:
        tq = parse_time(q.get("when"))
    except Exception as ex:  # noqa: BLE001
        return [f"{k}：when 看不懂（{ex}）"]
    if q.get("type") not in TYPES:
        e.append(f"{k}：type 只能是 {'、'.join(TYPES)}")
    if q.get("type") in NEEDS_WHEN and tq is None:
        e.append(f"{k}：{q.get('type')}題的時間是條件，when 不能是空的")
    cov = q.get("coverage")
    if cov not in COVERAGES:
        return e + [f"{k}：coverage 只能是 {'、'.join(COVERAGES)}"]
    if cov != "exact" and q.get("type") in ("找時間", "比較"):
        e.append(f"{k}：{q.get('type')}題只出 exact")
    rel = set(q.get("relevant_contents") or [])
    excluded = {int(i): r for i, r in (q.get("excluded") or {}).items()}
    if bad := {i: r for i, r in excluded.items() if r not in REASONS}:
        e.append(f"{k}：excluded 的理由只能是 {'、'.join(REASONS)}：{bad}")

    # 候選：每筆都要判過，收的要在候選裡
    units = q.get("options") if q.get("type") == "比較" else [q]
    if not units or any("space" not in u for u in units):
        return e + [f"{k}：缺 space（比較題寫在每個 options 裡）"]
    must = set().union(*(db.must_judge(u["space"], u.get("when"), cov) for u in units))
    if miss := must - rel - set(excluded):
        e.append(f"{k}：這些候選沒判：{sorted(miss)}")
    if extra := (rel | set(excluded)) - must:
        e.append(f"{k}：判了候選以外的片段：{sorted(extra)}")
    if both := rel & set(excluded):
        e.append(f"{k}：同時收又不收：{sorted(both)}")
    if cov == "none" and rel:
        e.append(f"{k}：coverage=none 不能有 relevant_contents")
    if cov != "none" and not 1 <= len(rel) <= MAX_RELEVANT:
        e.append(f"{k}：relevant_contents 有 {len(rel)} 筆，要 1–{MAX_RELEVANT}")
    if q.get("type") != "比較":
        e += check_layers(db, q, cov, rel, excluded)
    if q.get("type") == "找地點" and cov != "none" and len({db.frag(c)["poi_id"] for c in rel}) < 2:
        e.append(f"{k}：找地點題收的片段要涵蓋至少 2 個地點")
    if q.get("type") == "比較":
        for o in units:
            orel = set(o.get("relevant_contents") or [])
            if not orel or not orel <= rel:
                e.append(f"{k}：選項「{o.get('label')}」的 relevant_contents 要非空，且包含在題目的 relevant_contents 裡")
            elif out := orel - {f["id"] for f in db.pool(o["space"]["place_id"], o.get("when"))}:
                e.append(f"{k}：選項「{o.get('label')}」收了不在它原條件候選裡的片段：{sorted(out)}")
        if set().union(*(set(o.get("relevant_contents") or []) for o in units)) != rel:
            e.append(f"{k}：各選項 relevant_contents 的聯集要等於題目的 relevant_contents")
    if sorted({db.frag(c)["article"] for c in rel}) != sorted(q.get("relevant_articles") or []):
        e.append(f"{k}：relevant_articles 要由 relevant_contents 推得")

    # 時間不明：題目限定（或找時間題問的）維度標成不明的片段不收；內文明寫了符合的時間才例外，要記進 label_issues
    asks = q.get("asks")
    if q.get("type") == "找時間" and asks not in DIMS:
        e.append(f"{k}：找時間題要寫 asks（問的是哪個維度：{'、'.join(DIMS)}）")
    issues = {int(x["id"]) for x in q.get("label_issues") or []}
    widen = cov == "time_backoff"
    for u in units:
        mine = set(u.get("relevant_contents") or []) if q.get("type") == "比較" else rel
        for c in sorted(mine):
            if (dims := unknown_dims(db.frag(c), u.get("when"), asks, widen)) and c not in issues:
                e.append(f"{k}：片段 {c} 的{'、'.join(dims)}說不準卻收了；原句明寫了符合條件的時間才能收，並記進 label_issues")
    for c, why in excluded.items():
        f = db.frag(c)
        if why == "時間不明" and not any(unknown_dims(f, u.get("when"), asks, w) for u in units for w in (False, True)):
            e.append(f"{k}：片段 {c} 限定的時間維度都確定，不能用「時間不明」排除")

    # expect
    exp, src = q.get("expect") or [], q.get("expect_sources") or []
    if len(exp) != len(src):
        return e + [f"{k}：expect 和 expect_sources 條數不同"]
    # 揭露條：空間退讓要先講明問的地點本身沒有；none 只講沒有。時間退讓不寫揭露條，靠事實條開頭的實際時間
    disclose = {"exact": 0, "time_backoff": 0, "space_backoff": 1, "none": 1}[cov]
    facts = len(exp) - disclose
    if cov == "none" and facts:
        e.append(f"{k}：coverage=none 只有一條揭露條")
    if cov != "none" and not 1 <= facts <= MAX_POINTS:
        e.append(f"{k}：事實條有 {facts} 條，要 1–{MAX_POINTS}")
    cited: set[int] = set()
    for i, (p, s) in enumerate(zip(exp, src)):
        tag = f"{k}：expect[{i}]"
        if i < disclose:
            if s or not p.startswith("說明"):
                e.append(f"{tag} 應是揭露條：以「說明」開頭，expect_sources 是 {{}}")
            continue
        if not s:
            hint = "（時間退讓不寫揭露條，實際時間寫在事實條開頭）" if cov == "time_backoff" and p.startswith("說明") else ""
            e.append(f"{tag} 沒有來源{hint}")
            continue
        ids = {int(c) for c in s}
        if not ids <= rel:
            e.append(f"{tag} 引用了 relevant_contents 以外的片段：{sorted(ids - rel)}")
            continue
        cited |= ids
        frs = {c: db.frag(c) for c in ids}
        quotes = ""
        for c, quote in s.items():
            if not quote or _norm(quote) not in _norm(frs[int(c)]["content"]):
                e.append(f"{tag} 的 quote 不是片段 {c} 的原文子字串")
            quotes += _norm(quote) + "\n"
        allowed = set(NUM.findall(quotes + " ".join(f"{f['month']} " for f in frs.values())))
        if bad := sorted(set(NUM.findall(_norm(p))) - allowed):
            e.append(f"{tag} 有原句和月份標籤裡都沒有的數字：{bad}")
        if bad := [w for w in HEDGES if w in p and w not in quotes]:
            e.append(f"{tag} 有原句沒有的推論／概括／要求用語：{bad}")
        if bad := [w for w in ZH_NUM.findall(p) if w not in quotes]:
            e.append(f"{tag} 數字要用阿拉伯數字：{bad}")
    if cited != rel:
        e.append(f"{k}：relevant_contents 裡沒被任何 expect 用到的：{sorted(rel - cited)}")
    return e


def check_layers(db: DB, q: dict, cov: str, rel: set[int], excluded: dict[int, str]) -> list[str]:
    """coverage 要停在檢索第一個有相關片段的那層：前面的層不能有收進來的片段，也不能有「內容相關但時間不明」的片段
    （不明算相符，系統會在那層就拿它們回答）；收的片段要在停的那層的候選裡。"""
    k = q.get("id", "?")
    lay = db.layers(q["space"]["place_id"], q.get("when"))
    names = [n for n, _ in lay]
    if cov != "none" and cov not in names:
        return [f"{k}：沒有 {cov} 這層（時間不限就沒有時間退讓，沒有外圍行政區就沒有空間退讓）"]
    stop = names.index(cov) if cov != "none" else len(lay)
    e = []
    for name, ids in lay[:stop]:
        if hit := ids & rel:
            e.append(f"{k}：{name} 這層就有收進來的片段 {sorted(hit)}，coverage 應該停在 {name}")
        if unk := sorted(i for i in ids if excluded.get(i) == "時間不明"):
            e.append(f"{k}：{name} 這層有內容相關但時間不明的片段 {unk}，系統會在這層就拿它們回答，"
                     f"跟 coverage={cov} 對不起來，換題")
    if cov != "none" and (out := rel - lay[stop][1]):
        e.append(f"{k}：收進來的片段不在 {cov} 這層的候選裡：{sorted(out)}")
    return e


def places_of(q: dict) -> set[int]:
    units = q.get("options") if q.get("type") == "比較" else [q]
    return {u["space"]["place_id"] for u in units or [] if "space" in u}


def check_set(qs: list[dict]) -> list[str]:
    """一個題型（一個檔）內的分布上限。"""
    e = []
    ids = [q.get("id") for q in qs]
    e += [f"id 重複：{i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if (n := sum(q.get("coverage") != "exact" for q in qs)) > MAX_NON_EXACT:
        e.append(f"不是 exact 的題目有 {n} 題，上限 {MAX_NON_EXACT}")
    if (n := sum(len(q.get("relevant_contents") or []) == 1 for q in qs)) > MAX_SINGLE:
        e.append(f"只收一個片段的題目有 {n} 題，上限 {MAX_SINGLE}")
    per = Counter(p for q in qs for p in places_of(q))
    if over := {p: n for p, n in per.items() if n > MAX_PER_PLACE_TYPE}:
        e.append(f"同一個地點在這個題型超過 {MAX_PER_PLACE_TYPE} 題（地點 id: 題數）：{over}")
    return e


def check_all(qs: list[dict]) -> list[str]:
    """所有題型合起來的上限。"""
    e = []
    per = Counter(p for q in qs for p in places_of(q))
    if over := {p: n for p, n in per.items() if n > MAX_PER_PLACE}:
        e.append(f"同一個地點跨題型超過 {MAX_PER_PLACE} 題（地點 id: 題數）：{over}")
    keys = Counter((q["space"]["place_id"], q.get("aspect"), json.dumps(q.get("when"), sort_keys=True, ensure_ascii=False))
                   for q in qs if q.get("type") != "比較" and "space" in q)
    if dup := [x for x, n in keys.items() if n > 1]:
        e.append(f"地點、面向、時間條件都一樣的題目重複：{dup}")
    return e


def check_files(db: DB, paths: list[Path]) -> int:
    n_err = 0
    every: list[dict] = []
    for path in paths:
        qs = json.loads(path.read_text())["questions"]
        every += qs
        errs = [m for q in qs for m in check(db, q)] + check_set(qs)
        print("\n".join(errs) if errs else f"{path}：{len(qs)} 題全部通過")
        n_err += len(errs)
    if errs := check_all(every):
        print("\n".join(errs))
        n_err += len(errs)
    return n_err


# ---------- planner 讀題 ----------

def _time_key(t) -> tuple:
    """語意相同就算一樣（例：春＝3、4、5 月；全天＝不限時段）。"""
    return (None, None, None) if t is None else (t.months, t.day_type, t.slots)


def _time_text(t) -> str:
    if t is None or _time_key(t) == (None, None, None):
        return "時間不限"
    return "／".join(("、".join(t.month) or "月份不限", t.day_type or "平假日不限", "、".join(t.time) or "時段不限"))


async def plan_check(db: DB, paths: list[Path], concurrency: int) -> int:
    """讓 planner 只讀題目文字：每個子查詢解析出的地點和時間條件，要跟標註的 space／when（比較題是各選項）一樣。
    不一樣代表題目文字可能有別的讀法。地點只用快取解析（不打 Nominatim）。"""
    from service.env import load_env
    from strag_v3.rag import llm

    load_env()
    sem = asyncio.Semaphore(concurrency)
    problems: list[str] = []

    async def one(q: dict):
        async with sem:
            try:
                plan = await llm.plan(q["question"])
            except Exception as ex:  # noqa: BLE001
                problems.append(f"[planner 失敗] {q['id']}｜{ex}")
                return
        got = []
        for sq in plan.sub_queries:
            pid, name = None, "不限地點"
            if sq.space:
                name = f"{sq.space.name}（{sq.space.name_ja}，{sq.space.kind}）"
                try:
                    p = db.places.resolve(sq.space.name_ja, sq.space.city, sq.space.kind)
                    pid = p.id if p else None
                except Exception:  # noqa: BLE001  快取沒有，實際跑會去查 Nominatim
                    pid = None
            got.append(((pid, _time_key(sq.time)), f"{pid or '快取解析不到'} {name} {_time_text(sq.time)}"))
        units = q["options"] if q.get("type") == "比較" else [q]
        want = [((u["space"]["place_id"], _time_key(parse_time(u.get("when")))),
                 f"{u['space']['place_id']} {u['space'].get('name')} {_time_text(parse_time(u.get('when')))}")
                for u in units]
        if Counter(x for x, _ in got) != Counter(x for x, _ in want):
            problems.append(f"[讀法不同] {q['id']}｜{q['question']}\n  標註：{'；'.join(s for _, s in want)}"
                            f"\n  planner：{'；'.join(s for _, s in got)}")

    qs = [q for path in paths for q in json.loads(path.read_text())["questions"]]
    await asyncio.gather(*(one(q) for q in qs))
    print("\n".join(sorted(problems)) if problems else f"{len(qs)} 題的讀法都跟標註一樣")
    return len(problems)


# ---------- 評審校準 ----------

def positive_answer(db: DB, q: dict) -> str:
    """只用證據原句拼成的答案：揭露條照抄（去掉「說明」），其餘每個來源寫成「地點（時間標籤）：原句」。"""
    lines = []
    for p, s in zip(q["expect"], q["expect_sources"]):
        if not s:
            lines.append(p.removeprefix("說明") + "。")
        for c, quote in s.items():
            f = db.frag(int(c))
            lines.append(f"{f['poi']}（{when_text(f)}）：{quote} [{c}]")
    return "\n".join(lines)


async def calibrate(db: DB, path: Path, negatives: dict[str, str], concurrency: int) -> int:
    """真正的評審（judge.md）：正向答案每條都要判涵蓋，反向答案每條都要判不涵蓋。印出沒過的條目。"""
    from service.env import load_env
    from strag_v3.eval.full.judge import Judge
    from strag_v3.eval.metrics import Outcome
    from strag_v3.eval.questions import load_questions

    load_env()
    judge = Judge(sqlite3.connect(":memory:"))
    raw = {q["id"]: q for q in json.loads(path.read_text())["questions"]}
    sem = asyncio.Semaphore(concurrency)
    problems: list[str] = []

    async def one(q):
        qid = q.key.split("/", 1)[1]
        async with sem:
            jp = await judge.judge(q, Outcome(answer=positive_answer(db, raw[qid])))
            jn = await judge.judge(q, Outcome(answer=negatives[qid])) if qid in negatives else None
        problems.extend(f"[正向沒涵蓋] {qid}｜{c.point}｜{c.reason}" for c in jp.expect if not c.covered)
        problems.extend(f"[反向沒擋住] {qid}｜{c.point}｜{c.reason}" for c in (jn.expect if jn else ()) if c.covered)
        if qid not in negatives:
            problems.append(f"[缺反向答案] {qid}")

    await asyncio.gather(*(one(q) for q in load_questions(path)))
    print("\n".join(sorted(problems)) if problems else f"{path}：正向全部涵蓋、反向全部擋住")
    return len(problems)


# ---------- 命令列 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=ROOT / "data/ptt.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("places")
    s.add_argument("--min", type=int, default=1, help="至少幾筆片段")
    sub.add_parser("areas")
    s = sub.add_parser("pool")
    s.add_argument("place_id", type=int)
    s.add_argument("--when", type=json.loads, default=None)
    s.add_argument("--widen", action="store_true")
    s = sub.add_parser("outer")
    s.add_argument("place_id", type=int)
    s = sub.add_parser("check")
    s.add_argument("files", type=Path, nargs="+")
    s = sub.add_parser("plan")
    s.add_argument("files", type=Path, nargs="+")
    s.add_argument("--concurrency", type=int, default=4)
    s = sub.add_parser("answer")
    s.add_argument("file", type=Path)
    s.add_argument("qid")
    s = sub.add_parser("calibrate")
    s.add_argument("file", type=Path)
    s.add_argument("--negatives", type=Path, required=True, help="JSON：題目 id → 反向答案")
    s.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    db = DB(a.db)

    if a.cmd == "places":
        rows = db.conn.execute(
            "SELECT p.id, p.kind, p.name_zh, p.name_ja, p.city, COUNT(c.id) n FROM place p "
            "JOIN content c ON c.poi_id = p.id GROUP BY p.id HAVING n >= ? ORDER BY n DESC", (a.min,))
        for r in rows:
            print(" | ".join(str(x) for x in r))
    elif a.cmd == "areas":
        # 跟 Places.within 同一個判斷，但只看有片段的地點（沒片段的地點不影響片段數），快很多
        counts = dict(db.conn.execute("SELECT poi_id, COUNT(*) FROM content GROUP BY poi_id"))
        spots = db.content_places()
        rows = []
        for (pid,) in db.conn.execute("SELECT id FROM place WHERE kind = '區域' AND boundary IS NOT NULL"):
            area = db.places.get(pid)
            inside = [p for p in spots if p.id != pid and (p.kind == "景點" or p.rank > area.rank)
                      and area.contains(p.lat, p.lon)]
            if n := counts.get(pid, 0) + sum(counts[p.id] for p in inside):
                rows.append((n, pid, area.name_ja, area.city, len(inside)))
        for n, pid, name, city, k in sorted(rows, reverse=True):
            print(f"{pid} | {name} | {city} | 範圍內有片段的地點 {k} | 片段 {n}")
    elif a.cmd == "pool":
        for f in db.pool(a.place_id, a.when, a.widen):
            flag = f" | 限定維度不明：{'、'.join(f['unknown_dims'])}" if f["unknown_dims"] else ""
            print(f"{f['id']} | {f['poi']} | {f['month']}/{f['day_type']}/{f['time']}{flag} | {f['content']}")
    elif a.cmd == "outer":
        o = db.outer(a.place_id)
        print(o and f"{o} | {db.places.get(o).name_ja}")
    elif a.cmd == "check":
        return 1 if check_files(db, a.files) else 0
    elif a.cmd == "plan":
        return 1 if asyncio.run(plan_check(db, a.files, a.concurrency)) else 0
    elif a.cmd == "answer":
        q = next(q for q in json.loads(a.file.read_text())["questions"] if q["id"] == a.qid)
        print(positive_answer(db, q))
    elif a.cmd == "calibrate":
        negatives = json.loads(a.negatives.read_text())
        return 1 if asyncio.run(calibrate(db, a.file, negatives, a.concurrency)) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
