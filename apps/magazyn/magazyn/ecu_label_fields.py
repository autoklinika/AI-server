"""Conservative, typed field mapping for text already transcribed from ECU labels.

This is intentionally independent of the image model: transcription is not the
same as deciding what each number means. When evidence is ambiguous, supply
candidates for human review rather than silently filling a different field.
"""
from __future__ import annotations

import re
import unicodedata


_BOSCH = re.compile(r"(?<![A-Za-z0-9])0[\s.-]*2\d{2}[\s.-]*\d{3}[\s.-]*\d{3}(?![A-Za-z0-9])")
_MODEL = re.compile(
    r"(?i)(?<![A-Z0-9])(?:EDC(?:7|15|16|17)[A-Z0-9.-]{0,15}|"
    r"MD1[A-Z0-9.-]{2,15}|MG1[A-Z0-9.-]{2,15}|"
    r"DCM\d[A-Z0-9.-]{0,12}|SID\d{2,4}[A-Z0-9.-]{0,12}|"
    r"EMS\d[A-Z0-9.-]{0,10})(?![A-Z0-9])"
)
_MAKERS = (
    ("Bosch", re.compile(r"\bBOSCH\b", re.I)),
    ("Continental", re.compile(r"\bCONTINENTAL\b|\bSIEMENS\s+VDO\b", re.I)),
    ("Delphi", re.compile(r"\bDELPHI\b", re.I)),
    ("Denso", re.compile(r"\bDENSO\b", re.I)),
    ("Marelli", re.compile(r"\b(?:MAGNETI\s+MARELLI|MARELLI)\b", re.I)),
)
_BRANDS = {
    "DAF": "DAF", "MAN": "MAN", "SCANIA": "Scania",
    "IVECO": "Iveco", "VOLVO": "Volvo",
    "MERCEDES": "Mercedes-Benz", "MERCEDES-BENZ": "Mercedes-Benz",
    "BMW": "BMW", "VW": "Volkswagen", "VOLKSWAGEN": "Volkswagen",
    "AUDI": "Audi", "RENAULT": "Renault", "FORD": "Ford",
    "KIA": "Kia", "OPEL": "Opel", "FIAT": "Fiat",
}
# Number labels are kept distinct; one generic "number" regex silently mixes
# product numbers, OEM references, HW/SW revisions and serial numbers.
_PART = re.compile(
    r"(?i)(?<![A-Z0-9])(?:P\s*/\s*N|PART\s*(?:NUMBER|NO\.?|NR\.?)|"
    r"PRODUCT\s*(?:NUMBER|NO\.?)|BOSCH\s*(?:NUMBER|NO\.?|NR\.?)|"
    r"NR\s*KATALOGOWY)\s*[:#=\-]?\s*"
)
_OEM = re.compile(
    r"(?i)(?<![A-Z0-9])(?:OEM|OE)\s*(?:(?:PART\s*)?(?:NUMBER|NO\.?|NR\.?))?"
    r"\s*[:#=\-]?\s*"
)
_TAG = {
    "hardware": re.compile(r"(?i)(?<![A-Z0-9])(?:HW|H/W|HARDWARE)(?:\s*(?:VER|VERSION|NO\.?))?\s*[:#=\-]\s*([A-Z0-9][A-Z0-9._/-]{0,39})"),
    "software": re.compile(r"(?i)(?<![A-Z0-9])(?:SW|S/W|SOFTWARE)(?:\s*(?:VER|VERSION|NO\.?))?\s*[:#=\-]\s*([A-Z0-9][A-Z0-9._/-]{0,39})"),
    "serialNumber": re.compile(r"(?i)(?<![A-Z0-9])(?:S/N|SERIAL\s*(?:NO\.?|NUMBER)?|SN)\s*[:#=\-]\s*([A-Z0-9][A-Z0-9._/-]{2,39})"),
}
_NEXT_LABEL = re.compile(
    r"(?i)\s+(?=(?:HW|SW|H/W|S/W|HARDWARE|SOFTWARE|S/N|SERIAL|SN|"
    r"OEM|OE|PART\s*NO|PART\s*NUMBER|P/N)\s*[:#=])"
)
_FORBIDDEN = re.compile(r"(?i)(?<![A-Z0-9])(?:S/N|SERIAL|SN|HW|SW)\s*[:#=]")


def normalized(raw: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKC", str(raw)).upper()
        if c.isascii() and c.isalnum()
    )


def _all_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text)[:12000].splitlines() if line.strip()]


def _serials(lines: list[str]) -> list[str]:
    results = []
    for line in lines:
        for match in _TAG["serialNumber"].finditer(line):
            value = match.group(1).strip()
            if value not in results: results.append(value)
    return results


def _labeled(lines: list[str], regex: re.Pattern) -> list[str]:
    values = []
    for line in lines:
        # Another field on the same line must not be swallowed into a part ID.
        for match in regex.finditer(line):
            remainder = line[match.end():]
            remainder = _NEXT_LABEL.split(remainder, maxsplit=1)[0]
            # If an OCR output puts multiple values on one line, keep just the
            # first unambiguously separated identifier, not an invented joined ID.
            remainder = re.split(r"\s{2,}|[,;]", remainder, maxsplit=1)[0].strip()
            if "[?]" in remainder: continue
            value = normalized(remainder)
            if 7 <= len(value) <= 25 and any(c.isdigit() for c in value):
                if value not in values: values.append(value)
    return values


def _line_brand(lines: list[str]) -> str:
    found = set()
    for line in lines:
        plain = re.sub(r"\s+", " ", line).strip()
        m = re.fullmatch(r"(?i)(?:VEHICLE|POJAZD|MARKA|BRAND)\s*[:=]\s*([A-Z][A-Z -]{1,22})", plain)
        if m:
            token = m.group(1).strip().upper()
            if token in _BRANDS: found.add(_BRANDS[token])
        elif plain.upper() in _BRANDS:
            found.add(_BRANDS[plain.upper()])
    return next(iter(found)) if len(found) == 1 else ""


def _maker(text: str, found_bosch: list[str]) -> str:
    matches = [name for name, regex in _MAKERS if regex.search(text)]
    if len(matches) == 1: return matches[0]
    if not matches and found_bosch: return "Bosch"
    return ""


def _tagged(text: str, name: str) -> list[str]:
    values = []
    for line in _all_lines(text):
        for match in _TAG[name].finditer(line):
            value = match.group(1).strip()
            if value and value not in values: values.append(value)
    return values


def _bosch_numbers(text: str) -> list[str]:
    return list(dict.fromkeys(normalized(m.group(0)) for m in _BOSCH.finditer(text)))


def classify(ai_text: str, phone_text: str, barcodes: list[str]) -> dict:
    ai = str(ai_text)[:12000]
    phone = str(phone_text)[:6000]
    barcodes = [str(x)[:160] for x in barcodes[:12]]
    ai_lines = _all_lines(ai)
    phone_lines = _all_lines(phone)

    bosch_ai = _bosch_numbers(ai)
    bosch_phone = _bosch_numbers(phone)
    main_ai = _labeled(ai_lines, _PART)
    main_phone = _labeled(phone_lines, _PART)
    oem_ai = _labeled(ai_lines, _OEM)
    oem_phone = _labeled(phone_lines, _OEM)

    # Prefer an explicit Bosch number, then an explicitly labeled part number;
    # use an OEM as the main number only when no other kind is available.
    def preferred(bosch: list[str], parts: list[str], oems: list[str]) -> list[str]:
        return bosch or parts or oems

    suggested_ai = preferred(bosch_ai, main_ai, oem_ai)
    suggested_phone = preferred(bosch_phone, main_phone, oem_phone)
    primary = ""
    warnings = []
    if len(suggested_ai) == 1:
        if suggested_phone and suggested_ai[0] not in suggested_phone:
            warnings.append("Rozbieżne numery OCR telefonu i AI; wybierz numer główny ręcznie.")
        elif len(suggested_phone) > 1 and suggested_ai[0] not in suggested_phone:
            warnings.append("Kilka numerów na etykiecie; wybierz numer główny.")
        else:
            primary = suggested_ai[0]
    elif len(suggested_ai) > 1:
        warnings.append("Znaleziono kilka numerów tego samego typu. Wybierz numer główny.")
    elif len(suggested_phone) == 1:
        primary = suggested_phone[0]
    elif len(suggested_phone) > 1:
        warnings.append("OCR telefonu znalazł kilka numerów; wybierz ręcznie.")

    # Do not turn a serial number into an OEM alias or a part number.
    serial_values = _tagged(ai, "serialNumber") or _tagged(phone, "serialNumber")
    serial_normalized = {normalized(x) for x in serial_values}
    barcode_values = list(dict.fromkeys(
        normalized(b) for b in barcodes if 7 <= len(normalized(b)) <= 40
    ))
    candidate_values = list(dict.fromkeys(
        [*bosch_ai, *main_ai, *oem_ai, *bosch_phone, *main_phone, *oem_phone,
         *[b for b in barcode_values if len(b) <= 25]]
    ))
    candidates = [x for x in candidate_values if x not in serial_normalized][:20]
    if bosch_ai and bosch_phone and set(bosch_ai).isdisjoint(bosch_phone):
        primary = ""
        warnings.append("Konflikt numerów Bosch: AI i OCR telefonu podają inne wartości.")

    # Extra OEMs only if explicitly marked OEM on the photograph; never
    # pull in random barcodes, serials, HW, SW, unlabelled product codes.
    oem_numbers = [
        x for x in dict.fromkeys([*oem_ai, *oem_phone])
        if x != primary and x not in serial_normalized
    ][:12]

    def tag(name: str) -> str:
        a = _tagged(ai, name)
        p = _tagged(phone, name)
        if len(a) > 1 or (not a and len(p) > 1):
            warnings.append(f"Kilka wartości {name}; sprawdź oznaczenie.")
            return ""
        if a and p and a[0] != p[0]:
            warnings.append(f"Niepewna wartość {name}: AI i OCR telefonu różnią się.")
            return ""
        return (a or p or [""])[0]

    model_values = list(dict.fromkeys(
        m.group(0).upper() for m in _MODEL.finditer(ai)
    ))
    if not model_values:
        model_values = list(dict.fromkeys(m.group(0).upper() for m in _MODEL.finditer(phone)))
    model = model_values[0] if len(model_values) == 1 else ""
    if len(model_values) > 1:
        warnings.append("Więcej niż jeden model ECU; sprawdź oznaczenie.")

    maker = _maker(ai + "\n" + phone, bosch_ai + bosch_phone)
    brand = _line_brand(ai_lines) or _line_brand(phone_lines)
    designation = " ".join(x for x in (maker, model) if x).strip() if model else ""
    if "[?]" in ai:
        warnings.append("Odczyt zawiera nieczytelne znaki; sprawdź zdjęcie.")

    return {
        "primaryNumber": primary,
        "manufacturer": maker,
        "vehicleBrand": brand,
        "designation": designation,
        "model": model,
        "hardware": tag("hardware"),
        "software": tag("software"),
        "serialNumber": tag("serialNumber"),
        "oemNumbers": oem_numbers,
        "candidates": candidates,
        "barcodes": barcodes,
        "rawText": ai,
        "phoneText": phone,
        "evidence": "barcode_and_ocr" if primary and primary in barcode_values else "ocr_only",
        "warnings": list(dict.fromkeys(warnings)),
        "engine": "server_vision_ocr",
    }
