"""Second-pass AI ECU label interpretation with strict evidence checking.

The vision model first transcribes the image. A second text-only call to the
same resident model classifies markings that regex alone misses. Every proposed
number must occur in the literal transcription or phone OCR. The fallback is
always the existing deterministic parser. No extra model or network service.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .ecu_label_fields import classify, normalized

MAX_TRANSCRIPT = 9000
MAX_STRUCTURED_REPLY = 14000
MAX_EXTRA = 15

PROMPT = """Classify factory ECU identification-label TEXT provided below.
Return exactly one JSON object, not Markdown, using these keys:
{"manufacturer":"","vehicle_brand":"","ecu_model":"","category":"",
"primary_number":"","oem_numbers":[],"supplier_numbers":[],
"hardware":"","software":"","serial_number":"","production_date":"",
"other_numbers":[],"warnings":[]}

Rules:
* Never invent or complete any character or digit.
* Every number must appear verbatim in the input (spaces and hyphens may differ).
* Manufacturer, vehicle brand and ECU type are different things.
* Never infer a vehicle brand from an ECU maker or from a part-number prefix.
* Serial numbers, HW/SW revisions and dates are NOT interchangeable product IDs.
* If several unlabelled numbers exist, list them in other_numbers instead of
  pretending they are confirmed OEM aliases.
* OEM or supplier references without an explicit printed label may be suggested,
  but the user must confirm these before adding them to the catalog.
* category only when the text explicitly identifies a function e.g. engine ECU,
  EBS, ABS, gearbox control, body controller, EGR; otherwise empty.
* Use "" and [] for unknown values. No explanations outside the JSON.

TRANSCRIPTION:
"""


def _as_text(value: Any, max_chars: int = 100) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:max_chars]


def _tokens(value: str) -> str:
    return normalized(unicodedata.normalize("NFKC", value))


def _seen(value: str, text: str, *, min_len: int = 3) -> bool:
    """Check one physical line, never join unrelated lines into a fake ID."""
    code = _tokens(value)
    if len(code) < min_len or not any(ch.isdigit() for ch in code):
        return False
    return any(code in _tokens(line) for line in text.splitlines() if line.strip())


def _word(value: str, text: str) -> bool:
    name = _as_text(value, 80)
    return bool(name and any(name.casefold() in line.casefold() for line in text.splitlines()))


def _field_value(parsed: dict, field: str, text: str) -> str:
    candidate = _as_text(parsed.get(field), 100)
    return candidate if _seen(candidate, text, min_len=2) else ""


def _values(parsed: dict, field: str, text: str) -> list[str]:
    values = parsed.get(field)
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for raw in values[:30]:
        candidate = _as_text(raw, 100)
        code = _tokens(candidate)
        if (7 <= len(code) <= 35 and _seen(candidate, text, min_len=7)
                and code not in result):
            result.append(code)
    return result[:MAX_EXTRA]


def _json_object(answer: str) -> dict:
    if not isinstance(answer, str) or len(answer) > MAX_STRUCTURED_REPLY:
        return {}
    response = answer.strip()
    if response.startswith(chr(96)):
        response = re.sub(r"^\x60{3}(?:json)?\s*", "", response, flags=re.I)
        response = re.sub(r"\s*\x60{3}\s*$", "", response)
    try:
        value = json.loads(response)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


_CATEGORY_TERMS = (
    ("ECU silnika", ("ENGINE CONTROL", "ENGINE ECU", "ENGINE MANAGEMENT",
                     "MOTORSTEUER", "DIESEL ECU", "ECU SILNIKA", "ECM ENGINE")),
    ("EBS", ("EBS", "ELECTRONIC BRAKE", "BRAKING SYSTEM")),
    ("ABS", ("ANTI-LOCK", "ABS MODULE", "ABS CONTROL")),
    ("EGR", ("EGR", "EXHAUST GAS RECIRCULATION")),
    ("Sterownik skrzyni biegów", ("TRANSMISSION CONTROL", "GEARBOX ECU",
                                  "TCU", "TCM TRANSMISSION")),
    ("ECU nadwozia", ("BODY CONTROL", "BCM", "CENTRAL ELECTRONICS")),
)


def _category(parsed: dict, evidence: str) -> str:
    suggested = _as_text(parsed.get("category"), 60).lower()
    text = evidence.upper()
    aliases = {
        "ECU silnika": ("engine ecu", "engine control", "ecm", "engine management",
                        "diesel ecu", "ecu silnika", "silnik"),
        "EBS": ("ebs", "brake control", "braking"),
        "ABS": ("abs", "anti-lock"),
        "EGR": ("egr", "exhaust gas"),
        "Sterownik skrzyni biegów": ("transmission", "gearbox", "tcu", "tcm"),
        "ECU nadwozia": ("body control", "bcm"),
    }
    for name, terms in _CATEGORY_TERMS:
        accepted = (name.lower(), "") + aliases.get(name, ())
        if suggested in accepted and any(
            re.search(r"(?<![A-Z0-9])"+re.escape(term)+r"(?![A-Z0-9])", text)
            for term in terms
        ):
            return name
    return ""


def enrich(transcript: str, phone_ocr: str, barcodes: list[str],
           structured_answer: str) -> dict:
    """Pure, validated merger; no ungrounded model value can reach WebGUI."""
    vision = str(transcript)[:MAX_TRANSCRIPT]
    phone = str(phone_ocr)[:6000]
    evidence = vision + "\n" + phone
    parsed = _json_object(structured_answer)
    baseline = classify(vision, phone, barcodes)
    baseline["extraNumbers"] = []
    baseline["productionDate"] = ""
    baseline["fieldConfidence"] = {}
    if not parsed:
        baseline["extractionMode"] = "rules_fallback"
        baseline["warnings"].append("Dodatkowa klasyfikacja AI niedostępna; użyto rozpoznania standardowego.")
        return baseline

    warnings = list(baseline.get("warnings", []))
    confidence: dict[str, str] = {}
    maker = _as_text(parsed.get("manufacturer"), 60)
    if maker and _word(maker, evidence) and not baseline["manufacturer"]:
        baseline["manufacturer"] = maker
        confidence["manufacturer"] = "verified"

    vehicle = _as_text(parsed.get("vehicle_brand"), 60)
    if vehicle and not baseline["vehicleBrand"]:
        if any(
            re.fullmatch(r"(?i)(?:BRAND|VEHICLE|MARQUE|MARKA|POJAZD)\s*[:=]\s*"+
                         re.escape(vehicle)+r"\s*", line.strip())
            or line.strip().casefold() == vehicle.casefold()
            for line in evidence.splitlines()
        ):
            baseline["vehicleBrand"] = vehicle
            confidence["brand"] = "verified"
        else:
            warnings.append("Marka pojazdu nie jest jawnie podana; nie przypisano jej automatycznie.")

    for source, target, confidence_key in (
        ("ecu_model", "model", "model"),
        ("hardware", "hardware", "hw"),
        ("software", "software", "sw"),
        ("serial_number", "serialNumber", "serialNumber"),
    ):
        candidate = _field_value(parsed, source, evidence)
        if not candidate:
            continue
        previous = baseline.get(target, "")
        if previous and _tokens(previous) != _tokens(candidate):
            warnings.append("Różne wartości pola " + confidence_key + "; sprawdź etykietę.")
        elif not previous:
            baseline[target] = candidate
            confidence[confidence_key] = "suggestion"

    if baseline.get("model"):
        baseline["designation"] = " ".join(
            x for x in (baseline.get("manufacturer", ""), baseline["model"]) if x
        )

    primary = _field_value(parsed, "primary_number", evidence)
    # The model is not allowed to promote serial/HW/SW values to part numbers,
    # even when the value itself is undeniably present in the transcription.
    restricted_primary = {
        _tokens(baseline.get("serialNumber", "")),
        _tokens(baseline.get("hardware", "")),
        _tokens(baseline.get("software", "")),
        _tokens(_field_value(parsed, "serial_number", evidence)),
        _tokens(_field_value(parsed, "hardware", evidence)),
        _tokens(_field_value(parsed, "software", evidence)),
    }
    restricted_primary.discard("")
    if primary and _tokens(primary) not in restricted_primary:
        previous = baseline.get("primaryNumber", "")
        if previous and _tokens(previous) != _tokens(primary):
            explicit_oems = _values(parsed, "oem_numbers", evidence)
            if _tokens(previous) in explicit_oems:
                # Rules had only an OEM available as primary. The structured
                # pass found a separate supplier number on the label; suggest
                # that as main and retain the OEM as an alternate, NOT silently.
                baseline["primaryNumber"] = _tokens(primary)
                baseline["oemNumbers"] = list(dict.fromkeys(
                    [previous, *baseline.get("oemNumbers", [])]
                ))
                confidence["primary_number"] = "suggestion"
                warnings.append("AI proponuje zmianę numeru głównego z OEM na numer producenta — potwierdź.")
            else:
                warnings.append("AI proponuje inny numer główny niż reguły; zachowano dotychczasowy.")
        elif not previous:
            baseline["primaryNumber"] = _tokens(primary)
            confidence["primary_number"] = "suggestion"

    protected = {
        _tokens(baseline.get("serialNumber", "")),
        _tokens(baseline.get("hardware", "")),
        _tokens(baseline.get("software", "")),
        _tokens(baseline.get("primaryNumber", "")),
    }
    protected.discard("")
    oems = list(baseline.get("oemNumbers", []))
    extras: list[dict] = []
    oem_labels = _values(parsed, "oem_numbers", evidence)
    for code in oem_labels:
        if code in protected or code in {_tokens(x) for x in oems}:
            continue
        if any(code in _tokens(line) and re.search(r"\b(?:OEM|OE)\b", line, re.I)
               for line in evidence.splitlines()):
            oems.append(code)
        else:
            extras.append({"value": code, "role": "oem", "confidence": "suggestion"})
    for field, role in (("supplier_numbers", "supplier"),
                        ("other_numbers", "unclassified")):
        for code in _values(parsed, field, evidence):
            if (code not in protected and code not in {_tokens(x) for x in oems}
                    and code not in {r["value"] for r in extras}):
                # Classification from number FORMAT only; not a confirmed
                # interchange. Android shows these as unchecked suggestions.
                suggestion = role
                if role == "unclassified":
                    if re.fullmatch(r"(?:A2C|5WK)[0-9A-Z]{4,18}", code):
                        suggestion = "supplier"
                    elif re.fullmatch(r"[0-9]{2}[A-Z][0-9]{6}[A-Z0-9]{1,3}", code):
                        suggestion = "oem"
                extras.append({"value": code, "role": suggestion,
                               "confidence": "suggestion"})
    baseline["oemNumbers"] = oems[:12]
    baseline["extraNumbers"] = extras[:MAX_EXTRA]
    baseline["candidates"] = list(dict.fromkeys(
        list(baseline.get("candidates", [])) +
        [item["value"] for item in extras]
    ))[:25]
    date = _as_text(parsed.get("production_date"), 40)
    baseline["productionDate"] = date if date and any(
        _tokens(date) in _tokens(line) for line in evidence.splitlines()
    ) else ""
    cat = _category(parsed, evidence)
    if cat and not baseline.get("category"):
        baseline["category"] = cat
        confidence["category"] = "suggestion"
    baseline["fieldConfidence"] = confidence
    baseline["extractionMode"] = "ai_structured"
    warnings_ai = parsed.get("warnings")
    if isinstance(warnings_ai, list):
        warnings.extend(_as_text(w, 180) for w in warnings_ai[:5] if isinstance(w, str))
    baseline["warnings"] = list(dict.fromkeys(warnings))
    return baseline
