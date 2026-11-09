"""加地點別名，並把別名原本對到的地點合併進去。

用在同一個地方被不同寫法對到不同 OSM 物件（例如「上野公園」和「上野恩賜公園」）。做法：
1. 用 `place.py` 解析目標（名稱＋城市＋種類），每個別名寫進 `place_alias`，
   之後抽取和規劃器寫到這些別名（日文或繁中都算）就直接解析成目標。
   目標本身對錯時，先用 `pin_place.py` 把它釘到正確的 OSM 物件。
2. 合併：快取裡用別名查到、種類跟目標相同的地點，底下的片段全部改指到目標；
   另外 `content.poi_name` 是別名的片段也改指到目標。
3. 原本的地點沒有其他引用（別的寫法的快取、當外圍行政區）就刪掉。

    python scripts/db/alias_place.py 上野恩賜公園 東京 景點 上野公園 --db data/ptt.db
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from service.nominatim import NominatimClient  # noqa: E402
from strag_v3.place import KINDS, Places  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name_ja", help="目標的查詢名稱")
    ap.add_argument("city")
    ap.add_argument("kind", choices=KINDS)
    ap.add_argument("aliases", nargs="+", help="要指到目標的寫法，日文或繁中")
    ap.add_argument("--db", default=str(ROOT / "data/main.db"))
    a = ap.parse_args()

    conn = sqlite3.connect(a.db)
    conn.execute("PRAGMA foreign_keys = ON")
    places = Places(conn, NominatimClient())
    target = None
    for alias in a.aliases:
        target = places.add_alias(alias, a.name_ja, a.city, a.kind)
    print(f"別名 {'、'.join(a.aliases)} → {target.osm_type}/{target.osm_id} {target.name_ja}，place id {target.id}")

    marks = ",".join("?" * len(a.aliases))
    old_ids = {pid for (pid,) in conn.execute(
        f"SELECT DISTINCT p.id FROM nominatim_cache c JOIN place p ON p.osm_type = c.osm_type AND p.osm_id = c.osm_id"
        f" WHERE c.name_ja IN ({marks}) AND p.kind = ? AND p.id != ?", (*a.aliases, target.kind, target.id))}
    with conn:
        for old_id in sorted(old_ids):
            old = places.get(old_id)
            n = conn.execute("UPDATE content SET poi_id = ? WHERE poi_id = ?", (target.id, old_id)).rowcount
            print(f"合併 place id {old_id}（{old.osm_type}/{old.osm_id} {old.name_ja}）：片段 {n} 筆")
            if not target.name_zh and old.name_zh:
                conn.execute("UPDATE place SET name_zh = ? WHERE id = ?", (old.name_zh, target.id))
                target = places.get(target.id)
        n = conn.execute(f"UPDATE content SET poi_id = ? WHERE poi_name IN ({marks}) AND poi_id != ?",
                         (target.id, *a.aliases, target.id)).rowcount
        if n:
            print(f"poi_name 是別名的片段改指到目標：{n} 筆")
        for old_id in sorted(old_ids):
            old = places.get(old_id)
            # 還有不是別名的寫法查到它、還是別人的外圍行政區、或還有片段，就留著
            still_used = conn.execute(
                "SELECT 1 FROM nominatim_cache c WHERE c.osm_type = ? AND c.osm_id = ?"
                " AND c.name_ja NOT IN (SELECT alias FROM place_alias)"
                " UNION SELECT 1 FROM place WHERE outer_id = ?"
                " UNION SELECT 1 FROM content WHERE poi_id = ?",
                (old.osm_type, old.osm_id, old_id, old_id)).fetchone()
            if still_used:
                print(f"保留 place id {old_id}：還有其他引用")
            else:
                conn.execute("DELETE FROM place WHERE id = ?", (old_id,))
                print(f"刪掉 place id {old_id}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
