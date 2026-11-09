"""Nominatim 服務：打公開的 nominatim.openstreetmap.org `/search`，回傳原始回應。

Nominatim 的 HTTP 呼叫只在這裡；快取、取哪一筆、寫進 `place` 表都在 `strag_v3.place`。
"""
import time
import urllib.error
import urllib.parse
import urllib.request

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "strag-research/0.1 (spatio-temporal RAG research prototype)"

# 種類（strag_v3.place 的 SPOT／AREA／ANY）對到 Nominatim 的 layer；None 是不限
LAYERS = {"景點": "poi", "區域": "address", "不限": None}


class NominatimError(Exception):
    """Nominatim 呼叫失敗（HTTP 錯誤或連線失敗，重試後仍不行）。"""


class NominatimClient:
    """限每秒 1 次請求，帶自訂 User-Agent。"""

    _last = 0.0  # 所有 client 共用，確保整個行程每秒最多 1 次

    def __init__(self, retries: int = 4):
        self.retries = retries

    def search(self, name_ja: str, city: str, kind: str, settlement_only: bool = False) -> str:
        """回傳 `/search` 的原始回應（JSON 陣列的文字）。settlement_only：只要地名類，不要道路和店家。"""
        layer = LAYERS[kind]
        params = {
            "q": f"{name_ja} {city}".strip(),
            "format": "jsonv2",
            "countrycodes": "jp",
            "accept-language": "ja",
            "addressdetails": 1,
            "limit": 5,
        }
        if layer:
            params["layer"] = layer
        if settlement_only:
            params["featureType"] = "settlement"
        if layer != "poi":
            params["polygon_geojson"] = 1
        url = f"{URL}?{urllib.parse.urlencode(params)}"
        for attempt in range(1, self.retries + 1):
            wait = NominatimClient._last + 1.0 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            NominatimClient._last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read().decode()
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500 or attempt == self.retries:
                    raise NominatimError(f"Nominatim HTTP {e.code}：{name_ja}") from None
            except urllib.error.URLError as e:
                if attempt == self.retries:
                    raise NominatimError(f"Nominatim 連線失敗：{e.reason}") from None
            time.sleep(2 ** attempt)
        raise NominatimError("Nominatim 重試失敗")
