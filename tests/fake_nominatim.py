"""假的 Nominatim：一個固定的小世界，回傳跟真的 `/search` 一樣格式的原始回應。不打外部 API。"""
import json
from dataclasses import dataclass

from strag_v3.place import SPOT


@dataclass(frozen=True)
class Osm:
    """假世界裡的一個 OSM 物件。座標是方格上的點，區域的範圍是方框 (west, south, east, north)。"""
    osm_id: int
    names: tuple[str, ...]          # 查得到它的寫法，第一個是 OSM 上的名稱
    addresstype: str                # 景點是 tourism 這類，區域是 quarter、city 這類行政區類型
    lon: float
    lat: float
    rank: int
    outer: tuple[tuple[str, str], ...] = ()   # addressdetails 裡在它之外的地址，由小到大
    box: tuple[float, float, float, float] | None = None

    @property
    def layer(self) -> str:
        return "poi" if self.addresstype in ("tourism", "amenity", "shop") else "address"

    @property
    def settlement(self) -> bool:
        """`featureType=settlement` 留得下來的：地名類，不含道路。"""
        return self.layer == "address" and self.addresstype != "road"

    def result(self) -> dict:
        r = {
            "osm_type": "relation" if self.box else "way",
            "osm_id": self.osm_id,
            "addresstype": self.addresstype,
            "name": self.names[0],
            "lat": str(self.lat),
            "lon": str(self.lon),
            "place_rank": self.rank,
            "address": {self.addresstype: self.names[0], **dict(self.outer), "country": "日本"},
        }
        if self.box:
            w, s, e, n = self.box
            r["geojson"] = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
        return r


OSHIAGE_1 = (("neighbourhood", "押上一丁目"), ("quarter", "押上"), ("city", "墨田区"))
OSHIAGE_2 = (("neighbourhood", "押上二丁目"), ("quarter", "押上"), ("city", "墨田区"))

# 墨田区 ⊃ 押上 ⊃ 押上一丁目（晴空塔、晴空塔城）、押上二丁目（北十間川）；墨田区 ⊃ 向島（向島百花園）
# 台東区 ⊃ 淺草（淺草寺）；渋谷区 ⊃ 渋谷（澀谷 SKY）
# 東山区：查「東山区」時前 LIMIT 筆都是地址含東山区的道路，行政區本身排在後面，只有 settlement 查得到
WORLD = (
    Osm(100, ("墨田区",), "city", 5, 5, 16, box=(0, 0, 10, 10)),
    Osm(101, ("押上",), "quarter", 2, 2, 20, (("city", "墨田区"),), box=(0, 0, 4, 4)),
    Osm(102, ("押上一丁目",), "neighbourhood", 1, 1.8, 22, (("quarter", "押上"), ("city", "墨田区")), box=(0, 0, 2, 2)),
    Osm(103, ("押上二丁目",), "neighbourhood", 3, 1.8, 22, (("quarter", "押上"), ("city", "墨田区")), box=(2, 0, 4, 2)),
    Osm(104, ("向島",), "quarter", 6, 6, 20, (("city", "墨田区"),), box=(5, 5, 8, 8)),
    Osm(1, ("東京スカイツリー", "スカイツリー", "晴空塔", "東京晴空塔"), "tourism", 1, 1, 30, OSHIAGE_1),
    Osm(2, ("東京スカイツリータウン", "晴空塔城"), "tourism", 1.5, 1.5, 30, OSHIAGE_1),
    Osm(3, ("北十間川",), "tourism", 3, 1, 30, OSHIAGE_2),
    Osm(4, ("向島百花園",), "tourism", 6, 6.5, 30, (("quarter", "向島"), ("city", "墨田区"))),
    Osm(200, ("台東区",), "city", 15, 5, 16, box=(10, 0, 20, 10)),
    Osm(201, ("浅草", "淺草"), "suburb", 12, 2, 20, (("city", "台東区"),), box=(10, 0, 14, 4)),
    Osm(5, ("浅草寺", "淺草寺"), "amenity", 12, 1, 30, (("suburb", "浅草"), ("city", "台東区"))),
    Osm(300, ("渋谷区",), "city", 25, 5, 16, box=(20, 0, 30, 10)),
    Osm(301, ("渋谷",), "quarter", 22, 2, 20, (("city", "渋谷区"),), box=(20, 0, 24, 4)),
    Osm(6, ("渋谷スカイ", "SHIBUYA SKY", "澀谷 SKY"), "tourism", 22, 1, 30, (("quarter", "渋谷"), ("city", "渋谷区"))),
    *(Osm(400 + i, ("東山区",), "road", 35, i, 26, (("city", "東山区"),)) for i in range(1, 6)),
    Osm(400, ("東山区",), "city", 35, 5, 16, box=(30, 0, 40, 10)),
)

LIMIT = 5


class FakeNominatim:
    """假的 Nominatim：在 WORLD 裡依寫法找，回傳跟真的一樣格式的原始回應，最多 LIMIT 筆。
    景點只找 poi，區域只找 address；settlement_only 時只留地名類。"""

    def __init__(self, world=WORLD):
        self.world = world
        self.calls: list[tuple[str, str, str, bool]] = []

    def search(self, name_ja, city, kind, settlement_only=False):
        self.calls.append((name_ja, city, kind, settlement_only))
        layer = "poi" if kind == SPOT else "address"
        hits = [o for o in self.world
                if name_ja in o.names and o.layer == layer and (o.settlement or not settlement_only)]
        return json.dumps([o.result() for o in hits[:LIMIT]], ensure_ascii=False)
