"""出題工具（配合 `.scratch/ptt-v2-questions/generate.md`）：候選片段、題目檔驗證。

候選片段和檢索用同一套規則（`Places.scope`、`TimeQuery.matches`、`TimeQuery.widened`、`Places.outer`），
所以「哪些片段要判」由程式決定，不靠人工篩。DB 以唯讀開啟。
評審校準在 `python -m strag_v3.eval.baseline calibrate`。

    python scripts/eval/qgen.py places [--min 3]               # 有片段的地點（id、種類、名稱、片段數）
    python scripts/eval/qgen.py areas                           # 有範圍的區域，和範圍內的片段數（找地點題用）
    python scripts/eval/qgen.py pool 50 --when '{"month": ["3"], "time": ["晚上"]}' [--widen]
    python scripts/eval/qgen.py outer 50                        # 空間退讓會去的外圍行政區
    python scripts/eval/qgen.py layers 50 [--when '<json>']     # 檢索依序試的每層：地點、時間條件、候選數、限定維度不明的筆數
    python scripts/eval/qgen.py frag 6 611                      # 印指定的片段（格式跟 pool 一樣）
    python scripts/eval/qgen.py usage [資料夾]                  # 題目檔用掉的地點（各題型、合計、到上限的）和出過的組合
    python scripts/eval/qgen.py merge <題目檔> <草稿>...        # 草稿依 id 排序合併成題目檔；id 重複就報錯、不寫檔
    python scripts/eval/qgen.py blind-input <題目檔> [題目 id...]   # 給盲審子代理的 JSON（不帶標註）
    python scripts/eval/qgen.py blind-diff <題目檔> <盲審檔>...     # 標註 × 盲審的對照表、一致率和不一致的片段
    python scripts/eval/qgen.py check <題目檔>...               # 機械檢查，全部通過才 exit 0
    python scripts/eval/qgen.py plan <題目檔>...                # 讓 planner 只讀題目文字，比對還原出的地點和時間
    python scripts/eval/qgen.py answer <題目檔> <題目 id>       # 只用證據原句拼成的正向答案
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from strag_v3.eval.baseline.calibrate import positive_answer  # noqa: E402
from strag_v3.eval.baseline.fragments import load_fragments  # noqa: E402
from strag_v3.eval.baseline.questions import Question  # noqa: E402
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

    def judged_layers(self, space: dict, when: dict | None, coverage: str) -> list[tuple[str, set[int]]]:
        """必須逐筆判的層：從原條件試到 coverage 那層為止（none 是每一層）。"""
        lay = self.layers(space["place_id"], when)
        names = [n for n, _ in lay]
        stop = names.index(coverage) + 1 if coverage in names else len(lay)
        return lay[:stop]

    def must_judge(self, space: dict, when: dict | None, coverage: str) -> set[int]:
        """必須逐筆判過的候選：從原條件試到 coverage 那層為止的所有候選（none 是每一層）。"""
        return set().union(*(ids for _, ids in self.judged_layers(space, when, coverage)))


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


def frag_line(f: dict) -> str:
    """`pool`、`frag` 印一筆片段的格式；有 `unknown_dims` 才標「限定維度不明」。"""
    flag = f" | 限定維度不明：{'、'.join(f['unknown_dims'])}" if f.get("unknown_dims") else ""
    return f"{f['id']} | {f['poi']} | {f['month']}/{f['day_type']}/{f['time']}{flag} | {f['content']}"


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def when_text(f: dict) -> str:
    """片段的時間標籤寫成一句話（不明的維度不寫）。"""
    m = f["month"]
    month = "" if m == "不明" else f"{m} 月" if m[0].isdigit() else f"{m}天"
    parts = [month, *(x for x in (f["day_type"], f["time"]) if x != "不明")]
    return " ".join(p for p in parts if p) or "時間沒寫"


# ---------- 檢索的層 ----------

def layer_place(db: DB, place_id: int, layer: str) -> int:
    """這層撈哪個地點：空間退讓撈外圍行政區，其餘撈原地點。"""
    return db.outer(place_id) if layer == "space_backoff" else place_id


def layer_when(when: dict | None, layer: str) -> dict | None:
    """這層用的時間條件，寫成 when 的格式：時間退讓層是擴大後的條件，其餘是原條件。"""
    if layer != "time_backoff":
        return when
    w = parse_time(when).widened()
    return {k: v for k, v in (("month", list(w.month)), ("day_type", w.day_type), ("time", list(w.time))) if v}


def place_text(db: DB, place_id: int) -> str:
    p = db.places.get(place_id)
    return f"{place_id} {p.name}（{p.kind}）"


def cond_text(when: dict | None) -> str:
    return json.dumps(when, ensure_ascii=False) if when else "時間不限"


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


# ---------- 題目檔 ----------

ANNOTATION_NOTE = "依 src/strag_v3/eval/questions/generate.md 出題與標註"


def _id_key(qid: str) -> list:
    """stay-2 排在 stay-10 前面。"""
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", qid)]


def _units(q: dict) -> list[dict]:
    """有自己 space／when 的單位：比較題是每個選項，其餘是題目本身。"""
    return (q.get("options") or []) if q.get("type") == "比較" else [q]


def usage(db: DB, folder: Path) -> None:
    """資料夾裡所有題目檔用掉的地點：各題型和合計的題數（到上限的標出來），和出過的（地點、面向、時間條件）組合。"""
    qs = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            qs += data["questions"]
    if not qs:
        print("還沒有題目")
        return

    def mark(n: int, cap: int) -> str:
        return f"{n}（到上限）" if n >= cap else str(n)

    per: dict[int, Counter] = defaultdict(Counter)
    for q in qs:
        for p in places_of(q):
            per[p][q.get("type")] += 1
    print(f"各地點的題數（同一題型上限 {MAX_PER_PLACE_TYPE} 題，跨題型合計上限 {MAX_PER_PLACE} 題）：")
    for p, c in sorted(per.items(), key=lambda x: (-x[1].total(), x[0])):
        types = [*TYPES, *sorted(str(t) for t in c if t not in TYPES)]
        counts = "、".join(f"{t} {mark(c[t], MAX_PER_PLACE_TYPE)}" for t in types if c[t])
        print(f"{place_text(db, p)}：{counts}；合計 {mark(c.total(), MAX_PER_PLACE)}")

    combos: dict[tuple, list[str]] = defaultdict(list)
    for q in qs:
        for u in _units(q):
            if "space" in u:
                combos[(u["space"]["place_id"], q.get("aspect") or "", cond_text(u.get("when")))].append(str(q.get("id")))
    print("已出過的（地點、面向、時間條件）組合：")
    for (p, aspect, when), ids in sorted(combos.items()):
        print(f"{place_text(db, p)}｜{aspect}｜{when}｜{'、'.join(sorted(ids, key=_id_key))}")


def merge(out: Path, drafts: list[Path]) -> int:
    """把草稿的題目依 id 排序寫成題目檔；id 重複就報錯，不寫檔。"""
    qs, where = [], {}
    for path in drafts:
        for q in json.loads(path.read_text())["questions"]:
            qs.append(q)
            where.setdefault(q.get("id"), []).append(str(path))
    if dup := {i: ps for i, ps in where.items() if len(ps) > 1}:
        print("\n".join(f"id 重複：{i}（{'、'.join(ps)}）" for i, ps in dup.items()) + f"\n沒有寫入 {out}")
        return 1
    qs.sort(key=lambda q: _id_key(str(q.get("id"))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"annotation_note": ANNOTATION_NOTE, "questions": qs}, ensure_ascii=False, indent=2) + "\n")
    print(f"{out}：{len(qs)} 題（{'、'.join(str(q.get('id')) for q in qs)}）")
    return 0


# ---------- 盲審 ----------

BLIND_FIELDS = ("id", "type", "question", "when", "asks", "aspect", "aspect_rule")  # 盲審只看得到這些欄位
BLIND_NOTE = [
    "每題照 generate.md〈收不收片段〉，逐筆判 layers[].judge 列的片段：收，或不收並附理由碼（無關、別處、時間矛盾、時間不明）。",
    "每層的 space、when 是這層撈片段的地點範圍和時間條件，判這層的片段就照它們判（time_backoff 是擴大後的時間，"
    "space_backoff 是外圍行政區）。片段全文從專案根目錄跑這層的 pool 指令看；pool 印的是整層的候選，"
    "只判 judge 列的：同一筆只列在第一次出現的那層。",
    "比較題每個選項各有自己的層（option 是選項標籤）；in_options 標出同時是好幾個選項候選的片段，只判一次。",
    "結果寫成 JSON：{題目 id: {\"relevant\": {片段 id: 算數那句原文}, \"excluded\": {片段 id: 理由碼}}}。"
    "原文從片段逐字複製，可以截短，不能改字；每筆 judge 列的片段都要出現在 relevant 或 excluded 其中一邊。",
]


def scope_text(db: DB, place_id: int) -> str:
    """撈片段的地點範圍：景點只撈自己，區域撈本身和範圍內所有地點。"""
    p = db.places.get(place_id)
    return f"{place_id} {p.name}（{'區域：區域本身和範圍內所有地點' if p.kind == '區域' else p.kind}）"


def pool_cmd(place_id: int, when: dict | None, widen: bool) -> str:
    cmd = f".venv/bin/python scripts/eval/qgen.py pool {place_id}"
    if when:
        cmd += f" --when '{json.dumps(when, ensure_ascii=False)}'"
    return cmd + (" --widen" if widen else "")


def blind_input(db: DB, q: dict) -> dict:
    """給盲審子代理的一題：只有題目要素（BLIND_FIELDS），和跟 must_judge 一樣的要判的層。
    標註（coverage、收不收、expect…）一律不帶。"""
    compare = q.get("type") == "比較"
    layers: list[dict] = []
    first: dict[int, dict] = {}            # 片段 → 它第一次出現的那層
    owners: dict[int, list[str]] = {}      # 比較題：片段 → 它是哪些選項的候選
    for u in _units(q):
        for name, ids in db.judged_layers(u["space"], u.get("when"), q.get("coverage")):
            pid = layer_place(db, u["space"]["place_id"], name)
            entry = {"layer": name, **({"option": u.get("label")} if compare else {}),
                     "space": scope_text(db, pid), "when": layer_when(u.get("when"), name),
                     "pool": pool_cmd(pid, u.get("when"), name == "time_backoff"),
                     "judge": sorted(ids - first.keys())}
            first |= {i: entry for i in entry["judge"]}
            if compare:
                for i in ids:
                    if u.get("label") not in owners.setdefault(i, []):
                        owners[i].append(u.get("label"))
            layers.append(entry)
    for i in sorted(owners):
        if len(owners[i]) > 1:
            first[i].setdefault("in_options", {})[str(i)] = owners[i]
    return {**{k: q[k] for k in BLIND_FIELDS if k in q}, "layers": layers}


CATEGORIES = ("收", "不計分", "其他不收")  # 不計分＝時間不明；其他不收＝無關、別處、時間矛盾


def _judgement(kind: str, value: str) -> tuple[str, str]:
    """(三類之一, 顯示用的判斷)；kind 是 relevant 或 excluded，value 是引文或理由碼。"""
    if kind == "relevant":
        return "收", "收"
    return ("不計分" if value == "時間不明" else "其他不收"), f"不收（{value}）"


def _content(db: DB, cid: int) -> str:
    try:
        return db.frag(cid)["content"]
    except KeyError:
        return ""


def blind_diff(db: DB, path: Path, blind_paths: list[Path]) -> int:
    """標註 × 盲審的三類對照表和一致率，逐筆列出不一致的；再列盲審漏判、判到候選以外、引文不是原文的。
    只對照盲審檔裡有的題目。全部一致、沒有其他問題才 exit 0。"""
    qs = {q.get("id"): q for q in json.loads(path.read_text())["questions"]}
    blind: dict[str, dict[int, tuple[str, str]]] = {}
    odd: list[str] = []
    for bp in blind_paths:
        for qid, j in json.loads(bp.read_text()).items():
            rel = {int(c): t for c, t in (j.get("relevant") or {}).items()}
            exc = {int(c): r for c, r in (j.get("excluded") or {}).items()}
            odd += [f"{qid} | {c} | 同時寫在 relevant 和 excluded" for c in sorted(rel.keys() & exc.keys())]
            odd += [f"{qid} | {c} | 理由碼「{r}」不是 {'、'.join(REASONS)}" for c, r in exc.items() if r not in REASONS]
            blind.setdefault(qid, {}).update({c: ("excluded", r) for c, r in exc.items()}
                                             | {c: ("relevant", t) for c, t in rel.items()})

    table: Counter = Counter()
    diffs, missed, outside, bad_quotes = [], [], [], []
    odd += [f"{qid} | 題目檔裡沒有這題" for qid in blind if qid not in qs]
    for qid in sorted((i for i in blind if i in qs), key=_id_key):
        q, mine = qs[qid], blind[qid]
        cands = set().union(*(db.must_judge(u["space"], u.get("when"), q.get("coverage")) for u in _units(q)))
        rel = set(q.get("relevant_contents") or [])
        exc = {int(i): r for i, r in (q.get("excluded") or {}).items()}
        for c in sorted(cands & mine.keys() & (rel | exc.keys())):  # 標註漏判的不對照，check 會抓
            ours, ours_text = _judgement("relevant", "") if c in rel else _judgement("excluded", exc[c])
            theirs, theirs_text = _judgement(*mine[c])
            table[ours, theirs] += 1
            if ours != theirs:
                quote = mine[c][1] if mine[c][0] == "relevant" else "—"
                diffs.append(f"{qid} | {c} | 標註：{ours_text} | 盲審：{theirs_text} | 盲審引文：{quote}")
        if miss := sorted(cands - mine.keys()):
            missed.append(f"{qid}：{'、'.join(map(str, miss))}")
        if out := sorted(mine.keys() - cands):
            outside.append(f"{qid}：{'、'.join(map(str, out))}")
        for c, (kind, quote) in sorted(mine.items()):
            if kind == "relevant" and not (quote and _norm(quote) in _norm(_content(db, c))):
                bad_quotes.append(f"{qid} | {c} | {quote}")

    n = table.total()
    agree = sum(table[x, x] for x in CATEGORIES)
    print("標註＼盲審 | " + " | ".join(CATEGORIES))
    for x in CATEGORIES:
        print(f"{x} | " + " | ".join(str(table[x, y]) for y in CATEGORIES))
    print(f"一致率：{agree}/{n}（{agree / n:.1%}）" if n else "一致率：沒有可以對照的片段")
    sections = [("不一致的", diffs), ("盲審漏判的候選", missed), ("判了候選以外的片段", outside),
                ("盲審引文不是片段原文的", bad_quotes), ("盲審檔看不懂的", odd)]
    for title, lines in sections:
        print(f"{title}：" + ("\n" + "\n".join(lines) if lines else "無"))
    return 1 if any(lines for _, lines in sections) else 0


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


# ---------- 命令列 ----------

def main(argv: list[str] | None = None) -> int:
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
    s = sub.add_parser("layers")
    s.add_argument("place_id", type=int)
    s.add_argument("--when", type=json.loads, default=None)
    s = sub.add_parser("frag")
    s.add_argument("ids", type=int, nargs="+")
    s = sub.add_parser("usage")
    s.add_argument("folder", type=Path, nargs="?", default=ROOT / "src/strag_v3/eval/questions/ptt_v2")
    s = sub.add_parser("merge")
    s.add_argument("file", type=Path, help="要寫的題目檔")
    s.add_argument("drafts", type=Path, nargs="+")
    s = sub.add_parser("blind-input")
    s.add_argument("file", type=Path)
    s.add_argument("qids", nargs="*", help="只帶這些題目（預設全部）")
    s = sub.add_parser("blind-diff")
    s.add_argument("file", type=Path)
    s.add_argument("blinds", type=Path, nargs="+", help="盲審檔；同一題同一筆，後面的檔蓋過前面的")
    s = sub.add_parser("check")
    s.add_argument("files", type=Path, nargs="+")
    s = sub.add_parser("plan")
    s.add_argument("files", type=Path, nargs="+")
    s.add_argument("--concurrency", type=int, default=4)
    s = sub.add_parser("answer")
    s.add_argument("file", type=Path)
    s.add_argument("qid")
    a = ap.parse_args(argv)
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
            print(frag_line(f))
    elif a.cmd == "outer":
        o = db.outer(a.place_id)
        print(o and f"{o} | {db.places.get(o).name_ja}")
    elif a.cmd == "layers":
        for name, ids in db.layers(a.place_id, a.when):
            widen = name == "time_backoff"
            unk = sum(bool(unknown_dims(db.frag(i), a.when, widen=widen)) for i in ids)
            print(f"{name} | {place_text(db, layer_place(db, a.place_id, name))} | "
                  f"{cond_text(layer_when(a.when, name))} | 候選 {len(ids)} | 限定維度不明 {unk}")
    elif a.cmd == "frag":
        missing = 0
        for cid in a.ids:
            try:
                print(frag_line(db.frag(cid)))
            except KeyError as ex:
                print(ex.args[0])
                missing += 1
        return 1 if missing else 0
    elif a.cmd == "usage":
        usage(db, a.folder)
    elif a.cmd == "merge":
        return merge(a.file, a.drafts)
    elif a.cmd == "blind-input":
        qs = json.loads(a.file.read_text())["questions"]
        if miss := [i for i in a.qids if i not in {q.get("id") for q in qs}]:
            print(f"{a.file} 裡沒有這些題目：{'、'.join(miss)}")
            return 1
        items = [blind_input(db, q) for q in qs if not a.qids or q.get("id") in a.qids]
        print(json.dumps({"說明": BLIND_NOTE, "題目": items}, ensure_ascii=False, indent=2))
    elif a.cmd == "blind-diff":
        return blind_diff(db, a.file, a.blinds)
    elif a.cmd == "check":
        return 1 if check_files(db, a.files) else 0
    elif a.cmd == "plan":
        return 1 if asyncio.run(plan_check(db, a.files, a.concurrency)) else 0
    elif a.cmd == "answer":
        q = next(q for q in json.loads(a.file.read_text())["questions"] if q["id"] == a.qid)
        print(positive_answer(Question.from_dict(q), load_fragments(db.conn)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
