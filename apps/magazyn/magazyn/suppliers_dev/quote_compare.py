"""Read-only, bounded TME/Mouser price and stock comparison for DEV WebGUI.

Never writes item balances, orders or supplier credentials.
Unknown stock/price remains unknown; no assumptions about variant equivalence.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, quote

from .providers import SupplierEngine, _score, normalize
from .store import PROVIDERS
from .transport import SupplierHTTPError
from .auth import AuthorizationError


ALLOWED_SUPPLIERS = ("tme", "mouser")


def _label(value, limit=160):
    if not isinstance(value, (str, int, float)):
        return ""
    return "".join(ch for ch in str(value).strip() if ord(ch) >= 32 and ord(ch) != 127)[:limit]


def _quantity(value):
    if type(value) is int:
        return value if 0 <= value <= 2_000_000_000 else None
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(",", "")
        if re.fullmatch(r"\d{1,10}", value):
            number = int(value)
            return number if number <= 2_000_000_000 else None
    return None


def _money(value):
    if type(value) in (int, float):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return ""
    # Do not turn arbitrary supplier text into prices or infer an FX rate.
    if not 1 <= len(text) <= 45 or any(ord(ch) < 32 for ch in text):
        return ""
    if not re.search(r"\d", text) or any(ch in "<>{}[]\\|" for ch in text):
        return ""
    return text


def _product_link(value, supplier):
    value = _label(value, 1000)
    try:
        u = urlsplit(value)
        host = (u.hostname or "").casefold()
        allowed = (host in ("tme.eu", "www.tme.eu") if supplier == "tme"
                   else host in ("mouser.com", "www.mouser.com", "mouser.pl",
                                 "www.mouser.pl", "eu.mouser.com"))
        if (u.scheme == "https" and allowed and u.path.startswith("/")
                and not u.username and not u.password and u.port in (None, 443)
                and not u.fragment):
            return value
    except ValueError:
        pass
    return ""


def _tme_catalog_search_url(symbol):
    """TME v2 omits a PiP URL; provide a clearly labeled SKU search fallback.

    Do not claim this is a verified product page or fabricate category slugs.
    """
    sku = _label(symbol, 120)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/+,-]{0,119}", sku):
        return ""
    return "https://www.tme.eu/pl/katalog/?search=" + quote(sku, safe="")


def _base_row(item):
    supplier = item["supplier"]
    return {
        "supplier": supplier,
        "mpn": _label(item.get("mpn")),
        "manufacturer": _label(item.get("manufacturer")),
        "description": _label(item.get("description"), 300),
        "supplier_sku": _label(item.get("supplier_sku")),
        "product_url": _product_link(item.get("product_url"), supplier),
        "exact_mpn": bool(item.get("exact_mpn", False)),
        "stock_quantity": None,
        "stock_text": _label(item.get("availability")),
        "currency": "",
        "price_type": "",
        "price_breaks": [],
    }


def _tme_detail(data):
    if not isinstance(data, dict) or data.get("status") != "OK":
        raise ValueError("Nieprawidłowa odpowiedź /products/data")
    rows = (data.get("data") or {}).get("elements")
    if not isinstance(rows, list):
        raise ValueError("Brak listy ofert TME")
    return {row["symbol"]: row for row in rows
            if isinstance(row, dict) and isinstance(row.get("symbol"), str)}


def _tme_tiers(record):
    prices = record.get("prices")
    if not isinstance(prices, dict):
        return [], "", ""
    currency = _label(prices.get("currency"), 5).upper()
    currency = currency if re.fullmatch(r"[A-Z]{3}", currency) else ""
    tax = _label(prices.get("type"), 12).upper()
    tax = tax if tax in ("GROSS", "NET") else ""
    tiers = []
    for tier in (prices.get("elements") or [])[:20]:
        if not isinstance(tier, dict):
            continue
        qty,price = _quantity(tier.get("amount")),_money(tier.get("price"))
        if qty is None or qty < 1 or not price:
            continue
        tiers.append({"quantity":qty,"price":price})
    tiers.sort(key=lambda r:r["quantity"])
    return tiers[:12],currency,tax


def _tme_search(engine, query):
    response = engine.search_one("tme", query)
    if response["status"] != "ok":
        return response
    rows = [_base_row(row) for row in response.get("results",[])][:12]
    for row in rows:
        if row["product_url"]:
            row["link_kind"] = "product"
        else:
            row["product_url"] = _tme_catalog_search_url(row["supplier_sku"])
            row["link_kind"] = "catalog_search" if row["product_url"] else ""
    result = {"supplier":"tme","status":"ok","results":rows}
    if not rows:
        return result
    symbols = list(dict.fromkeys(row["supplier_sku"] for row in rows
                                 if row["supplier_sku"]))[:12]
    if not symbols:
        result["status"] = "partial"
        return result
    try:
        cfg = engine.store.internal("tme")
        token = engine.oauth.get_access_token("tme", cfg["creds"], engine.transport)
        params = [("country","PL"),("currency","PLN"),
                  ("scope[]","prices"),("scope[]","stock")]
        params.extend(("symbols[]",symbol) for symbol in symbols)
        raw = engine.transport.request("GET","https://api.tme.eu/products/data?"
            + urlencode(params),headers={"Authorization":"Bearer "+token,
                                          "Accept-Language":"pl"})
        details = _tme_detail(raw)
        for row in rows:
            item = details.get(row["supplier_sku"])
            if not item:
                continue
            row["stock_quantity"] = _quantity(item.get("stock_quantity"))
            row["price_breaks"],row["currency"],row["price_type"] = _tme_tiers(item)
    except (SupplierHTTPError, AuthorizationError, ValueError, KeyError, TypeError):
        # A catalog hit does NOT imply that price/stock data was obtained.
        result["status"] = "partial"
    return result


def _mouser_search(engine, query):
    cfg = engine.store.internal("mouser")
    quota_guard = getattr(engine, "_limit_mouser_requests", None)
    if callable(quota_guard):
        quota_guard()
    url = "https://api.mouser.com/api/v1/search/partnumber?" + urlencode(
        {"apiKey":cfg["creds"]["api_key"]})
    payload = engine.transport.request(
        "POST",url,json_data={"SearchByPartRequest":{
            "mouserPartNumber":query,"partSearchOptions":"None"}})
    if not isinstance(payload, dict) or payload.get("Errors"):
        raise ValueError("Niepoprawna odpowiedź Mouser")
    parts=(payload.get("SearchResults") or {}).get("Parts") or []
    if not isinstance(parts, list):
        raise ValueError("Mouser: brak listy")
    rows=[]
    for original in parts:
        if not isinstance(original, dict):
            continue
        base = normalize("mouser",{"SearchResults":{"Parts":[original]}})
        if not base:
            continue
        row = base[0]
        row["exact_mpn"] = _score(query,row["mpn"])==100
        out = _base_row(row)
        out["stock_quantity"] = _quantity(original.get("AvailabilityInStock"))
        # Text availability is kept verbatim when a numeric stock is unavailable.
        if out["stock_quantity"] is None:
            out["stock_text"] = _label(original.get("Availability"),140)
        tiers=[]
        for tier in (original.get("PriceBreaks") or [])[:20]:
            if not isinstance(tier,dict):
                continue
            qty,price = _quantity(tier.get("Quantity")),_money(tier.get("Price"))
            if qty is None or qty < 1 or not price:
                continue
            tiers.append({"quantity":qty,"price":price})
            currency=_label(tier.get("Currency"),5).upper()
            if re.fullmatch(r"[A-Z]{3}", currency):
                out["currency"]=currency
        out["price_breaks"]=sorted(tiers,key=lambda r:r["quantity"])[:12]
        rows.append(out)
    rows.sort(key=lambda r:(not r["exact_mpn"],r["mpn"]))
    return {"supplier":"mouser","status":"ok","results":rows[:12]}


def compare(engine:SupplierEngine,query):
    engine._valid_query(query)
    results=[]
    for supplier in ALLOWED_SUPPLIERS:
        cfg=engine.store.internal(supplier)
        required=PROVIDERS[supplier]["required"]
        if not cfg["enabled"]:
            results.append({"supplier":supplier,"status":"disabled","results":[]})
            continue
        if any(not cfg["creds"].get(k) for k in required):
            results.append({"supplier":supplier,"status":"credentials_required","results":[]})
            continue
        if not engine.live_allowed or (engine.live_providers is not None and
                                      supplier not in engine.live_providers):
            results.append({"supplier":supplier,"status":"offline_dev","results":[]})
            continue
        try:
            rows = (_tme_search(engine,query) if supplier=="tme"
                    else _mouser_search(engine,query))
            results.append(rows)
        except (SupplierHTTPError, AuthorizationError, ValueError, KeyError, TypeError) as error:
            # Never expose raw API messages, response bodies, request URLs or credentials.
            results.append({"supplier":supplier,"status":"api_error","results":[],
                            "http_status":getattr(error,"status",None)})
    return {
        "query":query,
        "checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources":results,
        "notice":"Ceny i stany pochodzą z odpowiedzi API. Brak danych ≠ 0 szt. "
                 "Walut nie przeliczamy; progi ilościowe i warianty MPN wymagają sprawdzenia."
    }
