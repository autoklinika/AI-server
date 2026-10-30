"""Mouser Search API -> reviewed suggestions for electronic part form (DEV only).

No purchasing, no automatic product creation and no PDF downloads.
Only an unambiguous exact manufacturer part number can populate suggestions.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from .providers import SupplierEngine
from .tme_enrich import clean, supplier_category


def verified_https_url(value):
    url = clean(value, 1200)
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if (p.scheme != "https" or not host or not p.path.startswith("/")
                or p.username or p.password or p.port not in (None, 443)
                or p.fragment or "." not in host
                or not re.fullmatch(r"[a-z0-9.-]{4,253}", host)):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        return urlunsplit(("https", host, p.path, p.query, ""))
    except ValueError:
        return ""


def exact_parts(response, mpn):
    if not isinstance(response, dict):
        raise ValueError("Mouser response must be an object")
    if response.get("Errors"):
        raise ValueError("Mouser search reported an error")
    search = response.get("SearchResults")
    if not isinstance(search, dict):
        raise ValueError("Mouser results missing")
    rows = search.get("Parts") or []
    if not isinstance(rows, list):
        raise ValueError("Mouser parts must be an array")
    # Do not merge different part-number suffixes, punctuation or variants.
    exact = mpn.strip().casefold()
    return [p for p in rows if isinstance(p, dict)
            and isinstance(p.get("ManufacturerPartNumber"), str)
            and p["ManufacturerPartNumber"].strip().casefold() == exact]


def product_attributes(part):
    rows = part.get("ProductAttributes") or []
    if not isinstance(rows, list):
        return []
    attrs = []
    for row in rows[:80]:
        if not isinstance(row, dict):
            continue
        name = clean(row.get("AttributeName"), 140)
        value = clean(row.get("AttributeValue"), 160)
        if name and value:
            attrs.append({"name": name, "value": value})
    return attrs


ATTRIBUTE_FIELDS = {
    "package / case": "package", "package": "package", "case": "package",
    "housing": "package", "obudowa": "package",
    "output voltage": "spec_voltage", "supply voltage": "spec_voltage",
    "napięcie wyjściowe": "spec_voltage",
    "output current": "spec_current", "maximum output current": "spec_current",
    "prąd wyjściowy": "spec_current",
    "power dissipation": "spec_power",
    "moc strat": "spec_power",
    "on-resistance": "spec_resistance", "rds(on)": "spec_resistance",
    "rezystancja w stanie przewodzenia": "spec_resistance",
    "capacitance": "spec_capacitance", "tolerance": "spec_tolerance",
    "number of pins": "spec_pin_count", "pin count": "spec_pin_count",
    "operating temperature": "spec_temperature",
    "interface type": "spec_interface",
}


def proposed_fields(mpn, part, attributes):
    result, used = [], set()

    def add(field, value, evidence, confidence="exact"):
        limit = 1900 if field == "parameters" else 190
        value = clean(value, limit)
        if value and field not in used:
            used.add(field)
            result.append({"field": field, "value": value,
                           "confidence": confidence,
                           "evidence": clean(evidence, 160)})
    add("designation", mpn, "Mouser: dokładny ManufacturerPartNumber")
    add("primary_number", mpn, "Mouser: ManufacturerPartNumber")
    add("manufacturer", part.get("Manufacturer"), "Mouser: Manufacturer")
    category = clean(part.get("Category"), 200)
    if category:
        suggested = supplier_category(category)
        if suggested not in {
            "Układy scalone", "Tranzystory i MOSFET-y",
            "Diody", "Mikrokontrolery i pamięci",
            "Rezystory i kondensatory", "Złącza"
        }:
            suggested = "Pozostałe elementy"
        add("category", suggested, "Mouser: " + category)

    grouped = {}
    leftovers = []
    for item in attributes:
        name, value = item["name"], item["value"]
        field = ATTRIBUTE_FIELDS.get(name.casefold())
        if field:
            grouped.setdefault(field, []).append((name, value))
        elif name.casefold() not in (
            "opakowanie", "packaging", "standardowa ilość w opak.",
            "reeling", "rohs", "lifecycle status"):
            leftovers.append(name + ": " + value)
    for field, pairs in grouped.items():
        if len({v for _, v in pairs}) == 1:
            add(field, pairs[0][1], "Mouser: " + pairs[0][0])

    desc = clean(part.get("Description"), 320)
    rest = (["Opis katalogowy: " + desc] if desc else []) + leftovers
    if rest:
        # Free-text descriptions may describe a component family. Never guess
        # individual electrical ratings (voltage/current) from such text.
        add("parameters", "; ".join(rest), "Mouser: opis katalogowy",
            confidence="verify_variant")
    return result


def enrich_mouser(engine: SupplierEngine, mpn):
    if (not isinstance(mpn, str) or not
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./,_-]{3,59}", mpn)):
        raise ValueError("Invalid MPN format")
    cfg = engine.store.internal("mouser")
    if not cfg["enabled"]:
        return {"status": "disabled", "suggestions": [], "documents": []}
    if not cfg["creds"].get("api_key"):
        return {"status": "credentials_required", "suggestions": [], "documents": []}
    if (not engine.live_allowed or (engine.live_providers is not None
                                     and "mouser" not in engine.live_providers)):
        return {"status": "offline_dev", "suggestions": [], "documents": []}

    response = engine._request("mouser", mpn, cfg["creds"])
    matching = exact_parts(response, mpn)
    if not matching:
        return {"status": "not_found", "suggestions": [], "documents": []}
    if len(matching) > 1:
        return {"status": "ambiguous", "suggestions": [], "documents": [],
                "warnings": ["Kilka dokładnych wyników MPN. Wybierz wariant ręcznie."]}

    part = matching[0]
    attributes = product_attributes(part)
    datasheet_url = verified_https_url(part.get("DataSheetUrl"))
    product_url = verified_https_url(part.get("ProductDetailUrl"))
    docs = ([{"type": "DTE", "filename": "Datasheet — " + mpn,
              "language": "", "url": datasheet_url}]
            if datasheet_url else [])
    return {
        "status": "ok", "source_name": "Mouser Search API",
        "source_kind": "supplier_catalog", "mpn": mpn,
        "manufacturer": clean(part.get("Manufacturer"), 190),
        "supplier_symbol": clean(part.get("MouserPartNumber"), 100),
        "description": clean(part.get("Description"), 320),
        "availability": clean(part.get("Availability"), 130),
        "product_url": product_url,
        "suggestions": proposed_fields(mpn, part, attributes),
        "technical_parameters": attributes, "documents": docs,
        "warnings": [], "family_datasheet": False,
        "manual_approval_required": True,
        "notice": ("Dane z Mouser wyłącznie do potwierdzenia wariantu; "
                   "nie są zapisywane automatycznie do Magazynu."),
    }
