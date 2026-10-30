"""Four supplier catalog adapters behind one normalized search contract."""
import re
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from .auth import OAuthManager, AuthorizationError, farnell_contract_signature
from .store import PROVIDERS
from .transport import Transport, SupplierHTTPError


class SupplierError(Exception):
    pass


def _s(value):
    if isinstance(value, dict):
        return _s(value.get("name") or value.get("Name") or value.get("Value"))
    return str(value or "")[:300]


def _link(value):
    value = str(value or "")
    return value[:1000] if urlparse(value).scheme == "https" else ""


def _list_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("elements") or value.get("products") or []
    return []


def _record(provider, mpn, manufacturer="", description="", datasheet="", product_url="",
            stock="", sku="", extra=None):
    return {
        "supplier": provider,
        "mpn": _s(mpn), "manufacturer": _s(manufacturer),
        "description": _s(description),
        "datasheet_url": _link(datasheet), "product_url": _link(product_url),
        "availability": _s(stock), "supplier_sku": _s(sku),
        "attributes": extra or {},
    }


def normalize(provider, response):
    """No assertion of exact matches; ranking is done after normalization."""
    if not isinstance(response, dict):
        return []
    items = []
    if provider == "mouser":
        items = _list_items((response.get("SearchResults") or {}).get("Parts"))
        return [_record(provider, p.get("ManufacturerPartNumber"),
                        p.get("Manufacturer"), p.get("Description"),
                        p.get("DataSheetUrl"), p.get("ProductDetailUrl"),
                        p.get("Availability"), p.get("MouserPartNumber"))
                for p in items if isinstance(p, dict)]
    if provider == "tme":
        data = response.get("data") or {}
        items = _list_items(data.get("products") or data.get("elements") or data)
        return [_record(provider,
                        p.get("mpn") or p.get("manufacturer_part_number")
                        or next(iter(p.get("manufacturer_symbols") or []), "")
                        or p.get("symbol"),
                        p.get("manufacturer") or p.get("producer"),
                        p.get("description") or p.get("name"),
                        p.get("datasheet_url") or p.get("documentation_url"),
                        p.get("product_url") or p.get("url"),
                        p.get("stock"), p.get("symbol"))
                for p in items if isinstance(p, dict)]
    if provider == "digikey":
        items = _list_items(response.get("Products") or response.get("products"))
        return [_record(provider,
                        p.get("ManufacturerProductNumber") or p.get("ManufacturerPartNumber"),
                        p.get("Manufacturer"), p.get("DetailedDescription") or p.get("Description"),
                        p.get("DatasheetUrl"), p.get("ProductUrl"),
                        p.get("QuantityAvailable"), p.get("DigiKeyProductNumber"))
                for p in items if isinstance(p, dict)]
    if provider == "farnell":
        # Manufacturer-part-number queries can return either keywordSearchReturn
        # or manufacturerPartNumberSearchReturn depending on API version.
        obj = (response.get("manufacturerPartNumberSearchReturn")
               or response.get("keywordSearchReturn") or {})
        items = _list_items(obj.get("products") or obj)
        out = []
        for p in items:
            if not isinstance(p, dict):
                continue
            sheets = p.get("datasheets") or []
            datasheet = ""
            if sheets and isinstance(sheets, list):
                first = sheets[0]
                datasheet = first.get("url", "") if isinstance(first, dict) else first
            out.append(_record(provider,
                p.get("translatedManufacturerPartNumber") or p.get("manufacturerPartNumber"),
                p.get("brandName"), p.get("displayName"), datasheet,
                p.get("productUrl"), p.get("stock") or p.get("inv"),
                p.get("sku")))
        return out
    return []


def _score(query, mpn):
    q = re.sub(r"[^A-Z0-9]", "", query.upper())
    p = re.sub(r"[^A-Z0-9]", "", (mpn or "").upper())
    if not p:
        return 0
    if q == p:
        return 100
    if q in p or p in q:
        return 60
    return 10


class SupplierEngine:
    def __init__(self, store, *, live_allowed=False, live_providers=None,
                 transport=None, oauth=None):
        self.store = store
        self.live_allowed = bool(live_allowed)
        self.live_providers = frozenset(live_providers) if live_providers is not None else None
        if self.live_providers is not None and not self.live_providers.issubset(PROVIDERS):
            raise SupplierError("Nieznane źródło LIVE-DEV.")
        self.transport = transport or Transport()
        self.oauth = oauth or OAuthManager()
        self._mouser_recent = deque()
        self._mouser_day = None
        self._mouser_daily_count = 0

    def _limit_mouser_requests(self):
        """Protect standard Mouser Search API quotas; one Uvicorn worker/lock."""
        today = datetime.now(timezone.utc).date()
        if self._mouser_day != today:
            self._mouser_day = today
            self._mouser_daily_count = 0
        now = time.monotonic()
        while self._mouser_recent and now - self._mouser_recent[0] >= 60:
            self._mouser_recent.popleft()
        # Margins below the distributor limit: 30/minute, 1000/day.
        if len(self._mouser_recent) >= 24 or self._mouser_daily_count >= 850:
            raise SupplierHTTPError("Mouser quota guard in effect", status=429)
        self._mouser_recent.append(now)
        self._mouser_daily_count += 1

    def dry_run(self, supplier, query):
        if supplier not in PROVIDERS:
            raise SupplierError("Nieznana hurtownia.")
        self._valid_query(query)
        cfg = self.store.internal(supplier)
        return {
            "supplier": supplier, "mode": "dry-run", "network_calls": 0,
            "auth": PROVIDERS[supplier]["auth"],
            "configured": all(cfg["creds"].get(x) for x in PROVIDERS[supplier]["required"]),
            "enabled": cfg["enabled"],
            "query": query,
            "endpoint": {
                "mouser": "api.mouser.com /api/v1/search/partnumber",
                "tme": "api.tme.eu /products?mpns[]",
                "digikey": "api.digikey.com /products/v4/search/keyword",
                "farnell": "api.element14.com /catalog/products",
            }[supplier],
            "note": "Symulacja budowy żądania; nie jest potwierdzeniem połączenia.",
        }

    @staticmethod
    def _valid_query(query):
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 40:
            raise SupplierError("Oznaczenie musi mieć 2–40 znaków.")
        if any(ord(c) < 32 for c in query):
            raise SupplierError("Niedozwolone znaki oznaczenia.")

    def search_one(self, supplier, query):
        if supplier not in PROVIDERS:
            raise SupplierError("Nieznana hurtownia.")
        self._valid_query(query)
        cfg = self.store.internal(supplier)
        if not cfg["enabled"]:
            return {"supplier": supplier, "status": "disabled", "results": []}
        required = PROVIDERS[supplier]["required"]
        if any(not cfg["creds"].get(field) for field in required):
            return {"supplier": supplier, "status": "credentials_required", "results": []}
        if (not self.live_allowed or
                (self.live_providers is not None and supplier not in self.live_providers)):
            return {"supplier": supplier, "status": "offline_dev", "results": []}
        try:
            results = normalize(supplier, self._request(supplier, query.strip(), cfg["creds"]))
            for product in results:
                product["match_score"] = _score(query, product["mpn"])
                product["exact_mpn"] = product["match_score"] == 100
            results.sort(key=lambda p: (-p["match_score"], p["mpn"]))
            return {"supplier": supplier, "status": "ok", "results": results[:12]}
        except (SupplierHTTPError, AuthorizationError, ValueError) as exc:
            # Do not echo sensitive request URLs, raw exceptions or response bodies.
            code = getattr(exc, "status", None)
            return {"supplier": supplier, "status": "api_error",
                    "http_status": code, "results": []}

    def search_all(self, query):
        self._valid_query(query)
        entries = self.store.public()
        return {"query": query, "sources": [
            self.search_one(row["supplier"], query) for row in entries],
            "notice": "Dane katalogowe wymagają weryfikacji przed zapisaniem do Magazynu.",
        }

    def _request(self, supplier, query, creds):
        if supplier == "mouser":
            self._limit_mouser_requests()
            url = "https://api.mouser.com/api/v1/search/partnumber?" + urlencode({
                "apiKey": creds["api_key"]})
            return self.transport.request(
                "POST", url,
                json_data={"SearchByPartRequest": {
                    "mouserPartNumber": query, "partSearchOptions": "None"}})
        if supplier == "tme":
            token = self.oauth.get_access_token("tme", creds, self.transport)
            base = "https://api.tme.eu/"
            headers = {"Authorization": "Bearer " + token, "Accept-Language": "pl"}
            exact = self.transport.request(
                "GET", base + "products?" + urlencode({"mpns[]": query, "country": "PL"}),
                headers=headers)
            if normalize("tme", exact):
                return exact
            return self.transport.request(
                "GET", base + "products/search?" +
                urlencode({"phrase": query, "scope[]": "products",
                           "limit": 12, "country": "PL"}), headers=headers)
        if supplier == "digikey":
            token = self.oauth.get_access_token("digikey", creds, self.transport)
            return self.transport.request(
                "POST", "https://api.digikey.com/products/v4/search/keyword",
                headers={"Authorization": "Bearer " + token,
                         "X-DIGIKEY-Client-Id": creds["client_id"],
                         "X-DIGIKEY-Locale-Site": "US",
                         "X-DIGIKEY-Locale-Language": "en",
                         "X-DIGIKEY-Locale-Currency": "USD"},
                json_data={"Keywords": query, "Limit": 12, "Offset": 0})
        if supplier == "farnell":
            params = {
                "term": "manuPartNum:" + query,
                "storeInfo.id": "pl.farnell.com",
                "resultsSettings.offset": 0,
                "resultsSettings.numberOfResults": 12,
                "resultsSettings.responseGroup": "medium",
                "callInfo.responseDataFormat": "JSON",
                "callInfo.apiKey": creds["api_key"],
            }
            if creds.get("customer_id") and creds.get("contract_secret"):
                now = datetime.now(timezone.utc)
                stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
                stamp, sign = farnell_contract_signature(
                    creds["contract_secret"], "searchByManufacturerPartNumber", stamp)
                params.update({"userInfo.customerId": creds["customer_id"],
                               "userInfo.timestamp": stamp, "userInfo.signature": sign})
            return self.transport.request(
                "GET", "https://api.element14.com/catalog/products?" + urlencode(params))
        raise SupplierError("Brak adaptera.")
