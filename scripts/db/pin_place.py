"""人工指定地點：把「名稱＋城市＋種類」釘到一個 OSM 物件，取代 Nominatim 搜尋的第一筆。

用在第一筆對錯的地點（例如搜「伏見稲荷大社」第一筆是本殿）。做法：
1. 用 Nominatim `/lookup` 取回指定物件的原始回應，寫進 `nominatim_cache` 的這個鍵，
   之後抽取和規劃器解析這個名稱時都讀到它（`--rebuild` 會保留快取，所以重新抽取也一樣）。
2. 用 `place.py` 解析，指定的物件寫進 `place` 表，外圍行政區照常計算。
3. 原本對錯的地點底下的片段改指到新地點；原本的地點沒有其他引用就刪掉。

    python scripts/db/pin_place.py 伏見稲荷大社 京都 景點 W96291583
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from strag_v3.place import AREA, KINDS, NominatimClient, Places  # noqa: E402

LOOKUP_URL = "https://nominatim.openstreetmap.org/lookup"


def lookup(osm: str, kind: str) -> str:
    """`/lookup` 的原始回應，參數跟 NominatimClient 的搜尋一致。"""
    params = {"osm_ids": osm, "format": "jsonv2", "accept-language": "ja", "addressdetails": 1}
    if kind == AREA:
        params["polygon_geojson"] = 1
    time.sleep(1.0)
    req = urllib.request.Request(f"{LOOKUP_URL}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": NominatimClient.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name_ja")
    ap.add_argument("city")
    ap.add_argument("kind", choices=KINDS)
    ap.add_argument("osm", help="OSM 物件，例如 W96291583（N=node、W=way、R=relation）")
    ap.add_argument("--db", default=str(ROOT / "data/main.db"))
    a = ap.parse_args()

    response = lookup(a.osm, a.kind)
    hits = json.loads(response)
    if not hits:
        print(f"Nominatim 查不到 {a.osm}", file=sys.stderr)
        return 1
    hit = hits[0]

    conn = sqlite3.connect(a.db)
    places = Places(conn, NominatimClient())
    old_key = conn.execute("SELECT osm_type, osm_id FROM nominatim_cache WHERE name_ja = ? AND city = ? AND kind = ?",
                           (a.name_ja, a.city, a.kind)).fetchone()
    old = places._by_osm(*old_key) if old_key and old_key[0] else None
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO nominatim_cache (name_ja, city, kind, response, osm_type, osm_id, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (a.name_ja, a.city, a.kind, response, hit["osm_type"], int(hit["osm_id"])))
    new = places.resolve(a.name_ja, a.city, a.kind, name_zh=old.name_zh if old else None)
    print(f"{a.name_ja}（{a.city}，{a.kind}）→ {new.osm_type}/{new.osm_id} {new.name_ja}，place id {new.id}，"
          f"外圍行政區：{places.outer(new).name_ja if new.outer_id else '無'}")

    if old and old.id != new.id:
        with conn:
            n = conn.execute("UPDATE content SET poi_id = ? WHERE poi_id = ?", (new.id, old.id)).rowcount
            print(f"片段改指到新地點：{n} 筆")
            still_used = conn.execute("SELECT 1 FROM nominatim_cache WHERE osm_type = ? AND osm_id = ?"
                                      " UNION SELECT 1 FROM place WHERE outer_id = ?",
                                      (old.osm_type, old.osm_id, old.id)).fetchone()
            if not still_used:
                conn.execute("DELETE FROM place WHERE id = ?", (old.id,))
                print(f"刪掉原本的地點：{old.osm_type}/{old.osm_id} {old.name_ja}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
