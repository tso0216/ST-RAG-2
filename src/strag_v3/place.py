"""地點解析：把日文名稱、城市、景點或區域解析成一個 OSM 物件（見 `docs/adr/0002-osm-place-resolution.md`）。

抽取和規劃器共用這個模組：

- 先查 `nominatim_cache` 表（名稱＋城市＋種類 → 原始回應），查不到才打 Nominatim，回應原樣存進快取。
  快取就是論文用的快照，重跑時只讀快取。
- 一律取第一筆。景點查 `layer=poi`；區域查 `layer=address`，只接受行政區類型（所以不會對到車站）。
- 解析到的 OSM 物件寫進 `place` 表，一列一個物件；不同寫法解析到同一個物件就是同一個地點。
  景點存座標；區域另存範圍（geojson）。
- 每個地點記錄外圍行政區：從 `addressdetails` 由小到大找第一個有範圍、而且範圍包住這個地點的行政區
  （景點是包含它的最小行政區，區域是上一層），外圍行政區本身也照區域的規則解析。

Nominatim 走 `Nominatim` 介面，測試時換成假的固定實作。
"""
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

SPOT = "景點"
AREA = "區域"
KINDS = (SPOT, AREA)

# addressdetails 裡算行政區的鍵（Nominatim 的地址鍵；`administrative` 是沒歸類的行政界，例如丁目）
ADMIN_TYPES = frozenset({
    "administrative", "neighbourhood", "quarter", "city_block", "suburb", "borough", "subdivision",
    "city_district", "district", "hamlet", "village", "town", "city", "municipality", "county",
    "state_district", "state", "province", "region",
})
# 查外圍行政區時，拿來當「城市」的上層地址鍵
_CITY_TYPES = ("city", "town", "village", "municipality", "county", "province", "state")
_AREA_SHAPES = ("Polygon", "MultiPolygon")

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS nominatim_cache (
    name_ja    TEXT NOT NULL,
    city       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    response   TEXT NOT NULL,             -- Nominatim 原始回應（JSON 陣列）
    osm_type   TEXT,                      -- 解析結果；解析不到是 NULL
    osm_id     INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (name_ja, city, kind)
)
"""


class PlaceError(Exception):
    """Nominatim 呼叫失敗，或快取沒有又不能呼叫。"""


class Nominatim(Protocol):
    def search(self, name_ja: str, city: str, kind: str) -> str:
        """回傳 Nominatim `/search` 的原始回應（JSON 陣列的文字）。"""
        ...


class NominatimClient:
    """公開的 nominatim.openstreetmap.org：限每秒 1 次請求，帶自訂 User-Agent。"""

    URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "strag-research/0.1 (spatio-temporal RAG research prototype)"
    _last = 0.0  # 所有 client 共用，確保整個行程每秒最多 1 次

    def __init__(self, retries: int = 4):
        self.retries = retries

    def search(self, name_ja: str, city: str, kind: str) -> str:
        params = {
            "q": f"{name_ja} {city}".strip(),
            "format": "jsonv2",
            "countrycodes": "jp",
            "accept-language": "ja",
            "addressdetails": 1,
            "limit": 5,
            "layer": "poi" if kind == SPOT else "address",
        }
        if kind == AREA:
            params["polygon_geojson"] = 1
        url = f"{self.URL}?{urllib.parse.urlencode(params)}"
        for attempt in range(1, self.retries + 1):
            wait = NominatimClient._last + 1.0 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            NominatimClient._last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read().decode()
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500 or attempt == self.retries:
                    raise PlaceError(f"Nominatim HTTP {e.code}：{name_ja}") from None
            except urllib.error.URLError as e:
                if attempt == self.retries:
                    raise PlaceError(f"Nominatim 連線失敗：{e.reason}") from None
            time.sleep(2 ** attempt)
        raise PlaceError("Nominatim 重試失敗")


@dataclass(frozen=True)
class Place:
    """`place` 表的一列：一個 OSM 物件。"""
    id: int
    osm_type: str
    osm_id: int
    kind: str
    name_ja: str
    name_zh: str | None
    city: str
    lat: float
    lon: float
    rank: int
    boundary: dict | None
    outer_id: int | None

    @property
    def name(self) -> str:
        """顯示用的名稱：第一次抽到的繁中名稱，沒有就用 OSM 上的名稱。"""
        return self.name_zh or self.name_ja

    def contains(self, lat: float, lon: float) -> bool:
        """點落在這個區域的範圍裡。沒有範圍的地點什麼都不包含。"""
        if not self.boundary:
            return False
        polygons = ([self.boundary["coordinates"]] if self.boundary["type"] == "Polygon"
                    else self.boundary["coordinates"])
        return any(_in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, hole) for hole in rings[1:])
                   for rings in polygons)


def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


_COLUMNS = "id, osm_type, osm_id, kind, name_ja, name_zh, city, lat, lon, place_rank, boundary, outer_id"


def _row(r) -> Place:
    *head, boundary, outer_id = r
    return Place(*head, json.loads(boundary) if boundary else None, outer_id)


class Places:
    """地點解析和 `place` 表的查詢。nominatim 是 None 時只讀快取，快取沒有就報錯。"""

    def __init__(self, conn: sqlite3.Connection, nominatim: Nominatim | None = None):
        self.conn = conn
        self.nominatim = nominatim
        conn.execute(CACHE_SCHEMA)

    # ---------- 解析 ----------

    def resolve(self, name_ja: str, city: str | None, kind: str, name_zh: str | None = None) -> Place | None:
        """解析成一個地點；解析不到傳回 None。name_zh 只在這個 OSM 物件第一次寫進 `place` 時記下。"""
        if kind not in KINDS:
            raise ValueError(f"地點種類只能是 {'、'.join(KINDS)}，不是「{kind}」")
        name_ja, city = name_ja.strip(), (city or "").strip()
        hit = _first(json.loads(self._response(name_ja, city, kind)), kind)
        if hit is None:
            return None
        existing = self._by_osm(hit["osm_type"], int(hit["osm_id"]))
        if existing:
            if name_zh and not existing.name_zh:
                with self.conn:
                    self.conn.execute("UPDATE place SET name_zh = ? WHERE id = ?", (name_zh, existing.id))
                return self.get(existing.id)
            return existing
        place = self._insert(hit, kind, city, name_zh)
        outer = self._find_outer(place, hit.get("address") or {})
        if outer:
            with self.conn:
                self.conn.execute("UPDATE place SET outer_id = ? WHERE id = ?", (outer.id, place.id))
            place = self.get(place.id)
        return place

    def _response(self, name_ja: str, city: str, kind: str) -> str:
        row = self.conn.execute("SELECT response FROM nominatim_cache WHERE name_ja = ? AND city = ? AND kind = ?",
                                (name_ja, city, kind)).fetchone()
        if row:
            return row[0]
        if self.nominatim is None:
            raise PlaceError(f"快取裡沒有「{name_ja}」（{city or '不限城市'}，{kind}），也沒有設定 Nominatim")
        response = self.nominatim.search(name_ja, city, kind)
        hit = _first(json.loads(response), kind)
        with self.conn:
            self.conn.execute(
                "INSERT INTO nominatim_cache (name_ja, city, kind, response, osm_type, osm_id, fetched_at)"
                " VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (name_ja, city, kind, response, hit and hit["osm_type"], hit and int(hit["osm_id"])))
        return response

    def _insert(self, hit: dict, kind: str, city: str, name_zh: str | None) -> Place:
        geo = hit.get("geojson")
        boundary = json.dumps(geo) if kind == AREA and geo and geo.get("type") in _AREA_SHAPES else None
        with self.conn:
            pid = self.conn.execute(
                "INSERT INTO place (osm_type, osm_id, kind, name_ja, name_zh, city, lat, lon, place_rank, boundary)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (hit["osm_type"], int(hit["osm_id"]), kind, hit.get("name") or hit.get("display_name", ""),
                 name_zh, city, float(hit["lat"]), float(hit["lon"]), int(hit.get("place_rank") or 30),
                 boundary)).lastrowid
        return self.get(pid)

    def _find_outer(self, place: Place, address: dict) -> Place | None:
        """addressdetails 由小到大，第一個解析得到、有範圍、包住這個地點、而且比它大的行政區。"""
        entries = list(address.items())[1:]  # 第一個是地點自己
        for i, (key, name) in enumerate(entries):
            if key not in ADMIN_TYPES:
                continue
            city = next((v for k, v in entries[i + 1:] if k in _CITY_TYPES), "")
            outer = self.resolve(name, city, AREA)
            if (outer and outer.id != place.id and outer.rank < place.rank
                    and outer.contains(place.lat, place.lon)):
                return outer
        return None

    # ---------- 查詢 ----------

    def get(self, place_id: int) -> Place:
        return _row(self.conn.execute(f"SELECT {_COLUMNS} FROM place WHERE id = ?", (place_id,)).fetchone())

    def _by_osm(self, osm_type: str, osm_id: int) -> Place | None:
        r = self.conn.execute(f"SELECT {_COLUMNS} FROM place WHERE osm_type = ? AND osm_id = ?",
                              (osm_type, osm_id)).fetchone()
        return _row(r) if r else None

    def within(self, area: Place) -> list[Place]:
        """區域範圍裡的所有地點：座標落在範圍裡的景點，加上代表點落在範圍裡的小區域。"""
        rows = self.conn.execute(f"SELECT {_COLUMNS} FROM place WHERE id != ?", (area.id,))
        return [p for p in map(_row, rows)
                if (p.kind == SPOT or p.rank > area.rank) and area.contains(p.lat, p.lon)]

    def scope(self, place: Place) -> frozenset[int]:
        """問這個地點時要取哪些地點的片段：景點只有自己；區域是自己加上範圍裡的所有地點。"""
        if place.kind == SPOT:
            return frozenset({place.id})
        return frozenset({place.id, *(p.id for p in self.within(place))})

    def outer(self, place: Place) -> Place | None:
        return self.get(place.outer_id) if place.outer_id else None


def _first(results: list[dict], kind: str) -> dict | None:
    """取第一筆；區域只看行政區類型的結果。"""
    if kind == AREA:
        results = [r for r in results if r.get("addresstype") in ADMIN_TYPES]
    return results[0] if results else None
