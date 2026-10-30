"""TME v2 catalog suggestions for the existing Magazyn electronic-item form.

DEV-only; one exact manufacturer MPN, product details, parameters and file links.
Never downloads/stores TME documents or writes an inventory item.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit, urlunsplit

from .auth import AuthorizationError
from .providers import SupplierEngine
from .transport import SupplierHTTPError


def clean(value, limit=240):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value.strip() if c >= " " and c != "\x7f")[:limit]


def comparable(value):
    return re.sub(r"[^A-Z0-9]", "", clean(value, 160).upper())


def document_link(value):
    """TME may return //www.tme.eu/path (protocol-relative). Do not accept foreign hosts."""
    url = clean(value, 1800)
    if url.startswith("//"):
        url = "https:" + url
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or parsed.hostname not in ("www.tme.eu", "tme.eu")
                or not parsed.path.startswith("/")
                or parsed.fragment):
            return ""
    except ValueError:
        return ""
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


def response_elements(payload):
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        raise ValueError("TME returned an invalid response status")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("TME data object is missing")
    rows = data.get("elements")
    if not isinstance(rows, list):
        raise ValueError("TME elements array is missing")
    return rows


def match_symbol(rows, mpn):
    target = comparable(mpn)
    if not target:
        return []
    exact = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        manufacturer_symbols = item.get("manufacturer_symbols")
        if not isinstance(manufacturer_symbols, list):
            continue
        if any(comparable(x) == target for x in manufacturer_symbols if isinstance(x, str)):
            symbol = clean(item.get("symbol"), 120)
            if symbol:
                exact.append(item)
    return exact


def supplier_category(value):
    name = clean(value, 200)
    lowered = name.casefold()
    if any(x in lowered for x in ("mosfet", "tranzystor", "transistor", "fet ")):
        return "Tranzystory i MOSFET-y"
    if any(x in lowered for x in ("diody", "diodes", "dioda", "diode")):
        return "Diody"
    if any(x in lowered for x in ("rezyst", "resistor", "capacitor", "kondensat")):
        return "Rezystory i kondensatory"
    if any(x in lowered for x in ("connector", "złącza", "złącze")):
        return "Złącza"
    if any(x in lowered for x in ("mikrokontrol", "microcontrol", "pamięc", "memory")):
        return "Mikrokontrolery i pamięci"
    if any(x in lowered for x in ("układy scalone", "integrated circuit", "power switch", "ic ")) :
        return "Układy scalone"
    return name[:200]


PARAMETER_FIELDS = {
    "obudowa": "package",
    "package": "package",
    "housing": "package",
    "napięcie wyjściowe": "spec_voltage",
    "napięcie zasilania": "spec_voltage",
    "output voltage": "spec_voltage",
    "supply voltage": "spec_voltage",
    "prąd wyjściowy": "spec_current",
    "prąd obciążenia": "spec_current",
    "output current": "spec_current",
    "load current": "spec_current",
    "moc strat": "spec_power",
    "moc rozpraszana": "spec_power",
    "power dissipation": "spec_power",
    "rezystancja w stanie przewodzenia": "spec_resistance",
    "on-state resistance": "spec_resistance",
    "rds(on)": "spec_resistance",
    "pojemność": "spec_capacitance",
    "capacitance": "spec_capacitance",
    "tolerancja": "spec_tolerance",
    "tolerance": "spec_tolerance",
    "liczba pinów": "spec_pin_count",
    "number of pins": "spec_pin_count",
    "temperatura pracy": "spec_temperature",
    "operating temperature": "spec_temperature",
    "interfejs": "spec_interface",
    "interface": "spec_interface",
}


def technical_parameters(payload, symbol):
    matched = [r for r in response_elements(payload)
               if isinstance(r, dict) and clean(r.get("symbol")) == symbol]
    if len(matched) != 1:
        raise ValueError("TME parameters do not uniquely match the product")
    groups = (matched[0].get("parameters") or {}).get("elements")
    if not isinstance(groups, list):
        raise ValueError("Missing technical parameters")
    result = []
    for raw in groups[:90]:
        if not isinstance(raw, dict):
            continue
        name = clean(raw.get("name"), 160)
        values = raw.get("values")
        if not name or not isinstance(values, list):
            continue
        cleaned = [clean(x.get("value"), 180) for x in values if isinstance(x, dict)]
        cleaned = list(dict.fromkeys(x for x in cleaned if x))
        if cleaned:
            result.append({"name": name, "value": ", ".join(cleaned)[:220]})
    return result


def technical_documents(payload, symbol):
    matched = [r for r in response_elements(payload)
               if isinstance(r, dict) and clean(r.get("symbol")) == symbol]
    if len(matched) != 1:
        raise ValueError("TME documents do not uniquely match the product")
    rows = (matched[0].get("documents") or {}).get("elements")
    if not isinstance(rows, list):
        raise ValueError("TME document listing missing")
    documents = []
    for raw in rows[:40]:
        if not isinstance(raw, dict):
            continue
        url = document_link(raw.get("url"))
        if not url:
            continue
        typ = clean(raw.get("type"), 20).upper()
        filename = clean(raw.get("file_name"), 160)
        language = clean(raw.get("language"), 16)
        if typ not in ("DTE", "INS", "INB", "KCH", "PRE", "GWA"):
            continue
        documents.append({
            "type": typ, "filename": filename or "Dokument TME",
            "language": language, "url": url,
        })
    return documents[:8]


def suggestions_for_product(mpn, product, parameters):
    suggestions = []
    seen = set()

    def add(field, value, evidence, confidence="exact"):
        if field in seen:
            return
        value = clean(value, 1900 if field == "parameters" else 190)
        if not value:
            return
        seen.add(field)
        suggestions.append({
            "field": field, "value": value,
            "evidence": clean(evidence, 200),
            "confidence": confidence,
        })

    manufacturer = product.get("manufacturer")
    if isinstance(manufacturer, dict):
        manufacturer = manufacturer.get("name")
    category = product.get("category")
    if isinstance(category, dict):
        category = category.get("name")

    add("designation", mpn, "TME: dokładne oznaczenie producenta")
    add("primary_number", mpn, "TME: manufacturer_symbols (zgodne MPN)")
    add("manufacturer", manufacturer, "TME: producent")
    add("category", supplier_category(category), "TME: kategoria " + clean(category, 160))

    unused = []
    multiple = {}
    for param in parameters:
        name = param["name"]
        value = param["value"]
        field = PARAMETER_FIELDS.get(name.casefold())
        if field:
            multiple.setdefault(field, []).append((value, name))
        elif name.casefold() not in ("producent", "manufacturer"):
            unused.append(name + ": " + value)
    for field, values in multiple.items():
        # Conflicting values must not be silently selected.
        if len({x[0] for x in values}) == 1:
            add(field, values[0][0], "TME: " + ", ".join(x[1] for x in values))

    if unused:
        text = "; ".join(unused)
        if len(text) > 1900:
            text = text[:1897].rsplit(";", 1)[0]
        add("parameters", text, "TME: pozostałe atrybuty produktu")
    return suggestions


def enrich_tme(engine: SupplierEngine, mpn):
    """Read catalog, parameters and files; return suggestions with source evidence."""
    if not isinstance(mpn, str) or not 4 <= len(mpn) <= 60:
        raise ValueError("Invalid MPN")
    mpn = clean(mpn, 60)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./,_-]{3,59}", mpn):
        raise ValueError("Invalid MPN format")
    cfg = engine.store.internal("tme")
    if not cfg["enabled"]:
        return {"status": "disabled", "suggestions": [], "documents": []}
    if not cfg["creds"].get("client_token") or not cfg["creds"].get("app_secret"):
        return {"status": "credentials_required", "suggestions": [], "documents": []}
    if not engine.live_allowed or (engine.live_providers is not None
                                   and "tme" not in engine.live_providers):
        return {"status": "offline_dev", "suggestions": [], "documents": []}

    headers = {"Authorization": "Bearer " + engine.oauth.get_access_token(
        "tme", cfg["creds"], engine.transport), "Accept-Language": "pl"}
    base = "https://api.tme.eu/"
    products = engine.transport.request(
        "GET", base + "products?" + urlencode({"mpns[]": mpn, "country": "PL"}),
        headers=headers)
    matching = match_symbol(response_elements(products), mpn)
    if not matching:
        return {"status": "not_found", "suggestions": [], "documents": []}
    if len(matching) != 1:
        return {"status": "ambiguous", "suggestions": [], "documents": [],
                "warnings": ["TME zwróciło wiele pozycji o tym samym MPN. Wybierz wariant ręcznie."]}

    product = matching[0]
    symbol = clean(product["symbol"], 120)
    warnings = []
    params = []
    docs = []
    try:
        raw = engine.transport.request(
            "GET", base + "products/parameters?"
            + urlencode({"symbols[]": symbol, "country": "PL"}), headers=headers)
        params = technical_parameters(raw, symbol)
    except (SupplierHTTPError, ValueError, TypeError, KeyError, AttributeError):
        warnings.append("Parametry TME są chwilowo niedostępne. Sprawdź kartę katalogową.")
    try:
        raw = engine.transport.request(
            "GET", base + "products/files?"
            + urlencode({"symbols[]": symbol, "country": "PL"}), headers=headers)
        docs = technical_documents(raw, symbol)
    except (SupplierHTTPError, ValueError, TypeError, KeyError, AttributeError):
        warnings.append("Lista dokumentów TME jest chwilowo niedostępna.")

    return {
        "status": "ok",
        "source_name": "TME API v2",
        "source_kind": "supplier_catalog",
        "mpn": mpn,
        "supplier_symbol": symbol,
        "manufacturer": clean((product.get("manufacturer") or {}).get("name")
                              if isinstance(product.get("manufacturer"), dict) else
                              product.get("manufacturer"), 200),
        "suggestions": suggestions_for_product(mpn, product, params),
        "technical_parameters": params,
        "documents": docs,
        "warnings": warnings,
        "family_datasheet": False,
        "manual_approval_required": True,
        "notice": ("Dane i dokumenty katalogowe TME są linkowane i wyświetlane do "
                   "weryfikacji. Nie zapisujemy zewnętrznych plików automatycznie."),
    }
