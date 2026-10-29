"""Local AI-assisted ECU label OCR (opt-in, DEV first).

This module does not run GPU models directly. It calls the EXISTING AI Gateway
at 127.0.0.1:11435, so all inference enters the established Resource Manager.
All image/text content is ephemeral and is never stored or logged here.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import threading
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .store import Problem


MAX_IMAGE_BYTES = 3_500_000
MAX_OCR_CHARS = 6_000
MAX_AI_OUTPUT_CHARS = 12_000
# One simultaneous scan per Magazyn process. Gateway itself handles RM queueing.
_ACTIVE_SCAN = threading.BoundedSemaphore(1)

_OCR_PROMPT = (
    "You are a visual transcription tool for a factory electronic control unit "
    "(ECU) identification label photographed on a workbench. "
    "Read every visible letter and digit EXACTLY as printed. "
    "Preserve line breaks, punctuation, spaces and leading zeros. "
    "Do not invent characters, complete part numbers, guess vehicle brands, "
    "or use automotive knowledge to replace unreadable digits. "
    "If a character is genuinely unreadable, write [?] in its position. "
    "Return only a literal transcription of the label, no interpretation."
)
_BOSCH = re.compile(r"(?<!\d)0[\s.-]*2\d{2}[\s.-]*\d{3}[\s.-]*\d{3}(?!\d)")
_BOSCH_NUMBER = re.compile(r"^02\d{8}$")
_LABELED_NUMBER = re.compile(
    r"(?i)(?:\bP\s*/\s*N\b|\bPART\s*(?:NO\.?|NUMBER)\b|"
    r"\bOEM\b|\bNR\s*(?:KATALOGOWY|CZESCI)\b|"
    r"\bBOSCH\s*(?:NR|NO|NUMBER)\b)"
    r"\s*[:#=\-]?\s*([A-Z0-9][A-Z0-9./ _-]{4,32})"
)
_TAGS = {
    "hardware": re.compile(r"(?i)\b(?:HW|H/W|HARDWARE)\b\s*[:#=\-]?\s*([A-Z0-9][A-Z0-9._/-]{1,29})"),
    "software": re.compile(r"(?i)\b(?:SW|S/W|SOFTWARE)\b\s*[:#=\-]?\s*([A-Z0-9][A-Z0-9._/-]{1,29})"),
    "serialNumber": re.compile(r"(?i)\b(?:S/N|SERIAL\s*(?:NO\.?|NUMBER)?|SN)\b\s*[:#=\-]?\s*([A-Z0-9][A-Z0-9._/-]{3,39})"),
}
_MODEL = re.compile(r"(?i)\b(?:EDC(?:7|15|16|17)[A-Z0-9-]{0,12}|MD1[A-Z0-9-]{2,15}|DCM\d[A-Z0-9-]{0,12}|SID\d{2,4}[A-Z0-9-]*)\b")


def normalize_number(raw: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", raw).upper() if ch.isascii() and ch.isalnum())


def _manufacturer(text: str, bosch: list[str]) -> str:
    for pattern, name in (
        (r"\bBOSCH\b", "Bosch"),
        (r"\bCONTINENTAL\b|\bSIEMENS\s*VDO\b", "Continental"),
        (r"\bDELPHI\b", "Delphi"),
        (r"\bDENSO\b", "Denso"),
        (r"\bMARELLI\b", "Marelli"),
    ):
        if re.search(pattern, text, re.I):
            return name
    return "Bosch" if bosch else ""


def _candidates(text: str) -> tuple[list[str], list[str]]:
    # Only explicitly labeled identifiers or the well-known ten-digit Bosch
    # pattern are eligible for prefill. Never use unconstrained digit strings.
    bosch = list(dict.fromkeys(normalize_number(x.group(0)) for x in _BOSCH.finditer(text)))
    labeled = []
    for line in text.splitlines():
        # Serial numbers and software revisions are not product-number aliases.
        if re.search(r"(?i)\b(?:S/N|SERIAL|SOFTWARE|HARDWARE|HW|SW)\b", line) and not re.search(
            r"(?i)\b(?:P\s*/\s*N|PART\s*(?:NO|NUMBER)|OEM|BOSCH\s*(?:NR|NO))\b", line
        ):
            continue
        for match in _LABELED_NUMBER.finditer(line):
            fragment = re.split(r"\s{2,}|[,;]", match.group(1))[0]
            candidate = normalize_number(fragment)
            if 7 <= len(candidate) <= 25 and any(x.isdigit() for x in candidate):
                labeled.append(candidate)
    return bosch, list(dict.fromkeys(labeled))


def analyze_transcripts(ai_text: str, phone_text: str, barcodes: list[str]) -> dict:
    """Conservative extraction; every result must be checked against the photo.

    The model's text is evidence, NOT proof: if phone and AI conflict on a
    similarly formatted Bosch part number, prefill remains empty.
    """
    ai = ai_text[:MAX_AI_OUTPUT_CHARS]
    phone = phone_text[:MAX_OCR_CHARS]
    ai_bosch, ai_labeled = _candidates(ai)
    local_bosch, local_labeled = _candidates(phone)

    barcode_values = [
        normalize_number(str(value)[:160])
        for value in barcodes[:12]
    ]
    barcode_values = [x for x in dict.fromkeys(barcode_values) if 7 <= len(x) <= 40]

    candidates = list(dict.fromkeys(
        [*ai_bosch, *ai_labeled, *local_bosch, *local_labeled,
         *[x for x in barcode_values if len(x) <= 25]]
    ))[:20]
    warnings: list[str] = []
    primary = ""
    ai_primary = ai_bosch if ai_bosch else ai_labeled
    phone_primary = local_bosch if local_bosch else local_labeled

    # Avoid treating barcode-only serial numbers as main ECU part numbers.
    if len(ai_primary) == 1:
        proposed = ai_primary[0]
        if phone_primary and proposed not in phone_primary:
            warnings.append("AI i OCR telefonu odczytały różne numery — wybierz ręcznie.")
        elif len(phone_primary) > 1 and proposed not in phone_primary:
            warnings.append("Na etykiecie występuje kilka możliwych numerów.")
        else:
            primary = proposed
    elif len(ai_primary) > 1:
        warnings.append("AI odczytało kilka numerów produktu — wybierz właściwy.")
    elif len(phone_primary) == 1:
        # No usable AI result: retain the existing local OCR path.
        primary = phone_primary[0]

    # A barcode match can corroborate, never replace, a labeled part number.
    if primary and barcode_values and primary in barcode_values:
        evidence = "barcode_and_ocr"
    else:
        evidence = "ocr_only"
    if ai_bosch and local_bosch and set(ai_bosch).isdisjoint(local_bosch):
        primary = ""
        warnings.append("Różne numery Bosch w dwóch odczytach — wymagana kontrola.")

    def tagged(key: str) -> str:
        ai_match = _TAGS[key].search(ai)
        phone_match = _TAGS[key].search(phone)
        a = ai_match.group(1) if ai_match else ""
        b = phone_match.group(1) if phone_match else ""
        if a and b and normalize_number(a) != normalize_number(b):
            warnings.append(f"Rozbieżne oznaczenie {key} w OCR telefonu i AI.")
            return ""
        return a or b

    model = (_MODEL.search(ai) or _MODEL.search(phone))
    manufacturer = _manufacturer(ai + "\n" + phone, ai_bosch + local_bosch)
    if "[?]" in ai:
        warnings.append("Model oznaczył nieczytelne znaki — porównaj zdjęcie.")

    return {
        "manufacturer": manufacturer,
        "primaryNumber": primary,
        "hardware": tagged("hardware"),
        "software": tagged("software"),
        "model": model.group(0).upper() if model else "",
        "serialNumber": tagged("serialNumber"),
        "candidates": candidates,
        "barcodes": [str(x)[:160] for x in barcodes[:12]],
        "rawText": ai,
        "phoneText": phone,
        "evidence": evidence,
        "warnings": list(dict.fromkeys(warnings)),
        "engine": "server_vision_ocr",
    }


def is_enabled() -> bool:
    return os.environ.get("MAGAZYN_ECU_AI_ENABLED", "0") == "1"


def _image_bytes(photo_base64: str) -> bytes:
    if len(photo_base64) > 4_700_000:
        raise Problem(413, "Zdjęcie jest zbyt duże")
    try:
        raw = base64.b64decode(photo_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise Problem(422, "Niepoprawne dane zdjęcia") from exc
    if not (80 <= len(raw) <= MAX_IMAGE_BYTES):
        raise Problem(413, "Zdjęcie musi mieć maksymalnie 3,5 MB")
    if not (raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")):
        raise Problem(422, "Obsługiwane są tylko zdjęcia JPEG")
    return raw


def _model_text(photo_base64: str) -> str:
    # Never accept arbitrary client-supplied URLs or models. All inference is
    # localhost Gateway /api/chat -> Global RM -> managed Ollama.
    model = os.environ.get("MAGAZYN_ECU_AI_MODEL", "minicpm-ocr:1.0").strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{1,90}", model):
        raise Problem(503, "Niewłaściwa konfiguracja modelu OCR")
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 850},
        "messages": [{
            "role": "user",
            "content": _OCR_PROMPT,
            "images": [photo_base64],
        }],
    }
    req = Request(
        "http://127.0.0.1:11435/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-AI-Source": "magazyn-ecu-ocr"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=110) as response:
            if response.status != 200:
                raise Problem(503, "Model OCR jest chwilowo niedostępny")
            data = response.read(48_000)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        # Never disclose internal hosts, headers, prompts or source images.
        raise Problem(503, "Model AI jest niedostępny; użyj odczytu telefonu") from exc
    try:
        text = json.loads(data)["message"]["content"]
    except (TypeError, ValueError, KeyError) as exc:
        raise Problem(503, "Model OCR nie zwrócił poprawnych danych") from exc
    if not isinstance(text, str) or not text.strip():
        raise Problem(503, "Model OCR nie rozpoznał oznaczeń")
    return text[:MAX_AI_OUTPUT_CHARS]


def recognize(photo_base64: str, local_text: str, barcodes: list[str]) -> dict:
    if not is_enabled():
        raise Problem(503, "AI OCR nie jest jeszcze aktywowane na serwerze")
    # Validate before requesting a GPU slot. Do not keep raw image after request.
    _image_bytes(photo_base64)
    if not _ACTIVE_SCAN.acquire(blocking=False):
        raise Problem(429, "Skaner AI jest zajęty; spróbuj ponownie")
    try:
        transcript = _model_text(photo_base64)
        return analyze_transcripts(transcript, local_text, barcodes)
    finally:
        _ACTIVE_SCAN.release()
