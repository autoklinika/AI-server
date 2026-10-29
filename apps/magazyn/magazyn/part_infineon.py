"""Verified, public Infineon product metadata when PDF download is unavailable.

Only Infineon's canonical /part/<MPN> endpoint is requested. The HTML is
untrusted: parse schema.org JSON-LD ProductGroup, require an EXACT identifier,
and expose bounded, evidence-backed values. No inference from Mouser search,
no guessed MPN suffix, no arbitrary URL selection, and no stock mutation.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from .store import Problem

_MAX_HTML_BYTES = 3_500_000
_SCRIPT_RE = re.compile(
    r"<script\b[^>]*type\s*=\s*['\"]application/ld\+json['\"][^>]*>"
    r"(.*?)</script\s*>", re.I | re.S,
)
_INFINEON_PREFIXES = (
    "BTS", "BTF", "BSP", "BTT", "BTG", "BCR", "TLE", "TLD",
    "IRF", "IRL", "IPD", "IPP", "IPB",
)


def eligible(part_no: str, manufacturer: str) -> bool:
    maker = str(manufacturer or "").strip().casefold()
    if maker and not any(name in maker for name in
                         ("infineon", "international rectifier")):
        return False
    return maker != "" or part_no.upper().startswith(_INFINEON_PREFIXES)


def _page_url(part_no: str) -> str:
    return "https://www.infineon.com/part/" + quote(part_no, safe="")


def parse_product(html_bytes: bytes, part_no: str) -> dict:
    """Exact product-group name + URL must match the requested MPN."""
    if len(html_bytes) > _MAX_HTML_BYTES or not html_bytes:
        raise Problem(413, "Strona producenta jest zbyt duża")
    try:
        markup = html_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        raise Problem(422, "Nie można odczytać strony producenta") from exc
    if not markup.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise Problem(422, "Źródło nie zwróciło strony produktu")
    requested = str(part_no).strip().upper()
    for match in _SCRIPT_RE.finditer(markup):
        try:
            graph = json.loads(html.unescape(match.group(1).strip()))
        except (ValueError, TypeError):
            continue
        if not isinstance(graph, dict):
            continue
        products = graph.get("@graph", [])
        if not isinstance(products, list):
            continue
        for node in products:
            if not isinstance(node, dict) or node.get("@type") != "ProductGroup":
                continue
            identities = (node.get("name"), node.get("productID"), node.get("sku"))
            if not any(str(v or "").strip().upper() == requested for v in identities):
                continue
            if node.get("url") != _page_url(requested):
                continue
            props = {}
            raw_props = node.get("additionalProperty", [])
            if isinstance(raw_props, list):
                for entry in raw_props[:90]:
                    if not isinstance(entry, dict):
                        continue
                    name, val = entry.get("name"), entry.get("value")
                    if isinstance(name, str) and isinstance(val, (str, int, float)):
                        key = name.strip()
                        value = str(val).strip()
                        if key and value and len(key) <= 130 and len(value) <= 160:
                            props[key] = value

            variants = []
            for variant in (node.get("hasVariant") or [])[:35]:
                if not isinstance(variant, dict) or variant.get("@type") != "Product":
                    continue
                vcode = str(variant.get("mpn") or "").strip()
                if not vcode or len(vcode) > 100:
                    continue
                properties = {
                    p.get("name"): str(p.get("value"))
                    for p in (variant.get("additionalProperty") or [])[:40]
                    if isinstance(p, dict) and isinstance(p.get("name"), str)
                    and isinstance(p.get("value"), str)
                }
                variants.append({"mpn": vcode, "properties": properties})

            documents = []
            for doc in (node.get("subjectOf") or [])[:90]:
                if not isinstance(doc, dict) or doc.get("@type") != "DigitalDocument":
                    continue
                if str(doc.get("description", "")).lower() != "datasheet":
                    continue
                url = doc.get("url")
                if (isinstance(url, str) and
                        url.startswith("https://www.infineon.com/assets/") and
                        "/documents/" in url and url.lower().endswith(".pdf") and
                        len(url) < 1200):
                    documents.append(url)
            return {
                "part_no": requested,
                "source_url": _page_url(requested),
                "description": str(node.get("description") or "")[:320],
                "category": str(node.get("category") or "")[:150],
                "properties": props,
                "variants": variants,
                "datasheet_url": documents[0] if documents else "",
            }
    raise Problem(404, "Nie znaleziono dokładnego oznaczenia na stronie Infineon")


def _suggest(field: str, value: str, evidence: str,
             *, confidence: str = "source") -> dict:
    # The evidence is a literal manufacturer label/value, not an AI guess.
    return {
        "field": field,
        "value": value[:160],
        "evidence": evidence[:210],
        "page": 0,
        "confidence": confidence,
    }


def inspect_product(profile: dict) -> dict:
    props = profile["properties"]
    part_no = profile["part_no"]
    suggested = []

    def add(field: str, value: str, label: str) -> None:
        if value:
            suggested.append(_suggest(field, value, label))

    add("primary_number", part_no, "Oficjalny numer produktu: " + part_no)
    add("manufacturer", "Infineon Technologies", "Oficjalny producent: Infineon Technologies")
    add("category", "Układy scalone",
        "Rodzina producenta: " + str(profile["category"]))
    if profile.get("category"):
        add("spec_interface", "HITFET / Smart Low-Side Switch",
            "Rodzina: " + str(profile["category"]))

    # Each value is tied to its native meaning, not an arbitrary 42 V input
    # voltage. Keep physical context directly inside the suggested form value.
    voltage = props.get("VDS max", "")
    if voltage:
        add("spec_voltage", voltage + " (VDS max)", "VDS max: " + voltage)
    current = props.get("Nominal Load Current per channel", "")
    if current:
        add("spec_current", current + " (prąd nominalny)",
            "Nominal Load Current per channel: " + current)
    power = props.get("Ptot max", "")
    if power:
        add("spec_power", power + " (Ptot max)", "Ptot max: " + power)
    ron = props.get("RDS (on) (@ Tj = 25°C)", "")
    if ron:
        add("spec_resistance", ron + " (RDS(on), 25°C)",
            "RDS (on) (@ Tj = 25°C): " + ron)
    temperature = props.get("Operating Temperature range", "")
    if temperature:
        add("spec_temperature", temperature,
            "Operating Temperature range: " + temperature)

    # Package is only reliable when *all* orderable variants share the same
    # package identity. Else leave it to the person holding the physical IC.
    variants = profile.get("variants") or []
    names = {
        variant["properties"].get("Package Name", "").strip()
        for variant in variants if isinstance(variant, dict)
    }
    if len(names) == 1 and "" not in names:
        only = next(iter(names))
        add("package", only, "Package Name: " + only)

    warnings = [
        "Odczytano oficjalną kartę produktu Infineon. Dokument PDF nie został "
        "automatycznie pobrany — można otworzyć go przez podany link.",
        "Przed zastosowaniem sprawdź oznaczenie obudowy i wersję konkretnego elementu.",
    ]
    if len(variants) > 1:
        warnings.append(
            "Producent wymienia kilka wariantów zamówieniowych; sprawdź obudowę i kod OPN."
        )
    return {
        "part_number": part_no,
        "source_name": "Infineon — oficjalna karta produktu",
        "source_url": profile["source_url"],
        "source_kind": "manufacturer_product",
        "datasheet_url": profile.get("datasheet_url", ""),
        "manufacturer": "Infineon Technologies",
        "pages_checked": 0,
        "family_datasheet": len(variants) > 1,
        "suggestions": suggested,
        "warnings": warnings,
        "pdf_base64": "",
        "filename": "",
    }
