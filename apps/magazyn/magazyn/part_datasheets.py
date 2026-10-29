"""DEV: controlled datasheet discovery, PDF extraction and supported form proposals.

No DB writes, no arbitrary URL proxying, no new GPU service. The optional
structured extractor uses the existing AI Gateway (which owns the global RM).
Search providers: official TI product datasheet convention; optional Mouser
authorized API; direct LCSC item code (the public storefront endpoint is
unofficial and therefore opt-in). Uploaded PDFs work without any API key.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import os
import re
import secrets
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .store import Problem

MAX_DOCUMENT = 8 * 1024 * 1024
MAX_RESPONSE = 300_000
MAX_SEARCH = 6
PART_RE = re.compile(r"^[A-Z0-9][A-Z0-9./_-]{3,59}$")
PDF_HOSTS = frozenset({
    "ti.com", "infineon.com", "microchip.com", "st.com",
    "onsemi.com", "vishay.com", "nxp.com", "analog.com", "renesas.com",
    "rohm.com", "nexperia.com", "diodes.com", "toshiba.semicon-storage.com",
    "allegromicro.com", "monolithicpower.com", "lcsc.com", "mouser.com",
    "digikey.com",
})
SPECS = frozenset({
    "designation", "primary_number", "manufacturer", "category", "package",
    "spec_voltage", "spec_current", "spec_power", "spec_resistance",
    "spec_capacitance", "spec_tolerance", "spec_pin_count",
    "spec_temperature", "spec_interface", "parameters",
})
LLM_PROMPT = """Jesteś analitykiem kart katalogowych elektroniki. Przepisz WYŁĄCZNIE
parametry prawidłowego komponentu ze wskazanej dokumentacji, a nie ze swojej
pamięci. Zwróć tylko JSON:
{"fields":[{"field":"spec_voltage","value":"55 V","evidence":"V DSS = 55 V"},...],
 "warnings":[]}
Dozwolone pola:
designation,primary_number,manufacturer,category,package,spec_voltage,
spec_current,spec_power,spec_resistance,spec_capacitance,spec_tolerance,
spec_pin_count,spec_temperature,spec_interface,parameters.
Każda wartość techniczna MUSI mieć krótki DOSŁOWNY cytat evidence z podanego
tekstu dokumentu; w innym przypadku pominąć pole. Jeśli dokument dotyczy
kilku wariantów (np. LM358 i LM358B), nie przepisuj parametrów różnych
wersji jako wartości jednego wariantu. Nie wypełniaj pól na podstawie tabel
Absolute Maximum Ratings bez jednoznacznej kwalifikacji. Nie zgaduj obudowy.
Brak danych oznacza pominięcie pola. Bez Markdown i wyjaśnień.
"""


def code(value: str) -> str:
    s = str(value or "").strip().upper()
    if not PART_RE.fullmatch(s) or not any(ch.isdigit() for ch in s):
        raise Problem(422, "Wpisz pełne oznaczenie elementu, np. LM358 lub IRF3205")
    return s


def normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _allowed_url(url: str) -> str:
    try:
        part = urlsplit(url)
        host = (part.hostname or "").lower().rstrip(".")
        if (part.scheme != "https" or not host or part.username is not None
                or part.password is not None or part.port not in (None, 443)
                or part.fragment or len(url) > 1200):
            raise ValueError("Unsafe URL")
        if not any(host == domain or host.endswith("." + domain)
                   for domain in PDF_HOSTS):
            raise ValueError("Untrusted domain")
        return url
    except ValueError as exc:
        raise Problem(422, "Nieobsługiwane źródło dokumentacji") from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code_, msg, headers, newurl):
        raise Problem(422, "Źródło przekierowało na inny adres; dokument wymaga ręcznej kontroli")


def _fetch(url: str, *, max_bytes: int, accept: str = "application/pdf") -> bytes:
    _allowed_url(url)
    opener = build_opener(_NoRedirect)
    request = Request(url, headers={
        "User-Agent": "MagazynV1-DatasheetFetcher/1.0",
        "Accept": accept,
    })
    try:
        with opener.open(request, timeout=12) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise Problem(413, "Dokument przekracza 8 MB")
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise Problem(413, "Dokument przekracza 8 MB")
            return data
    except Problem:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise Problem(503, "Nie udało się pobrać dokumentacji producenta") from exc


def _pdf_bytes(base64_string: str) -> bytes:
    if len(base64_string) > 11_184_812:
        raise Problem(413, "Dokument PDF przekracza 8 MB")
    try:
        payload = base64.b64decode(base64_string, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise Problem(422, "Niepoprawny plik PDF") from exc
    if not (100 < len(payload) <= MAX_DOCUMENT
            and payload.startswith(b"%PDF-")
            and b"%%EOF" in payload[-2048:]):
        raise Problem(422, "Wymagana prawidłowa karta katalogowa PDF do 8 MB")
    return payload


def _pdf_text(data: bytes) -> list[str]:
    # Poppler operates on stdin; the file is never written to disk by this code.
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "6", "-layout", "-", "-"],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=12, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise Problem(503, "Nie udało się przeanalizować PDF") from exc
    if result.returncode or not result.stdout:
        raise Problem(422, "PDF nie zawiera czytelnego tekstu; potrzebna ręczna analiza")
    text = result.stdout[:120_000].decode("utf-8", errors="replace")
    pages = [s for s in text.split("\f") if s.strip()]
    if not pages:
        raise Problem(422, "PDF nie zawiera tekstu")
    return pages[:6]


def _evidence_page(evidence: str, pages: list[str]) -> int | None:
    needle = " ".join(evidence.casefold().split())
    if len(needle) < 4 or len(needle) > 260:
        return None
    for i, page in enumerate(pages, 1):
        if needle in " ".join(page.casefold().split()):
            return i
    return None


def _has_exact_mpn(part_no: str, pages: list[str]) -> tuple[bool, bool]:
    first = "\n".join(pages[:3]).upper()
    pat = re.compile(r"(?<![A-Z0-9])" + re.escape(part_no) + r"(?![A-Z0-9])")
    exact = bool(pat.search(first))
    # Suffix derivatives like LM358B are distinguishable variants.
    derivatives = re.findall(
        r"(?<![A-Z0-9])" + re.escape(part_no) + r"[A-Z0-9]{1,6}(?![A-Z0-9])",
        first,
    )
    return exact, bool(derivatives)


def _suggest(field: str, value: str, evidence: str, pages: list[str],
             *, family: bool = False) -> dict | None:
    if field not in SPECS or not value.strip():
        return None
    page = _evidence_page(evidence, pages)
    if page is None:
        return None
    return {
        "field": field,
        "value": value[:160 if field.startswith("spec_") else 200],
        "evidence": evidence[:220],
        "page": page,
        "confidence": "verify_variant" if family else "document",
    }


def _rules(part_no: str, maker: str, pages: list[str], family: bool) -> list[dict]:
    text = pages[0]
    result = []

    def add(field: str, value: str, evidence: str):
        row = _suggest(field, value, evidence, pages, family=family)
        if row is not None and not any(x["field"] == field for x in result):
            result.append(row)

    descriptions = [
        (r"(?i)(power\s+MOSFET|HEXFET)", "Tranzystory i MOSFET-y", "N-MOSFET"),
        (r"(?i)(operational\s+amplifiers?|op\s+amps?)", "Układy scalone", "Wzmacniacz operacyjny"),
        (r"(?i)(serial\s+EEPROM|electrically\s+erasable\s+programmable)", "Mikrokontrolery i pamięci", "EEPROM"),
        (r"(?i)(Schottky\s+barrier|rectifier\s+diode)", "Diody", "Dioda"),
    ]
    for regex,category,kind in descriptions:
        m = re.search(regex, text)
        if m:
            add("category",category,m.group(0))
            add("spec_interface",kind,m.group(0))
            break

    # Never infer exact supply/power ratings from an unspecified family
    # datasheet (LM358 versus LM358B have different recommended supplies).
    if not family:
        for field, pattern, unit, label in [
            ("spec_voltage", r"(?i)\bV\s*(?:DSS|DS)\s*=\s*(\d+(?:[.,]\d+)?)\s*V\b", "V", ""),
            ("spec_current", r"(?i)\bI\s*D\s*=\s*(\d+(?:[.,]\d+)?)\s*A\b", "A", ""),
            ("spec_resistance", r"(?i)\bRDS\s*\(?on\)?\s*=\s*(\d+(?:[.,]\d+)?)\s*m[\u03a9\u2126]", "mΩ", ""),
        ]:
            found = re.search(pattern,text)
            if found:
                add(field,found.group(1).replace(",",".")+" "+unit,found.group(0))

    if maker:
        # Manufacturer identity is verified by the source's official domain
        # and separate exact part number check, not hallucinated from a PDF.
        result.append({"field":"manufacturer","value":maker[:160],
                       "evidence":"Zweryfikowany dostawca źródła",
                       "page":0,"confidence":"source"})
    result.append({"field":"primary_number","value":part_no,
                   "evidence":"Oznaczenie potwierdzone w dokumencie",
                   "page":0,"confidence":"source"})
    return result


def _llm_extract(part_no: str, pages: list[str], family: bool) -> list[dict]:
    if os.environ.get("MAGAZYN_DATASHEET_AI_ENABLED", "0") != "1":
        return []
    transcript = "\n\n".join(
        "[Page "+str(i)+"]\n"+page[:3600]
        for i,page in enumerate(pages[:5], 1)
    )[:15_000]
    body = {
        "model": os.environ.get("MAGAZYN_DATASHEET_AI_MODEL", "qwen3.8:27b"),
        "stream": False, "think": False, "format": "json", "keep_alive": 0,
        "options":{"temperature":0,"num_ctx":8192,"num_predict":950},
        "messages":[{"role":"user","content":LLM_PROMPT +
                      "\nPART NUMBER: "+part_no+"\n"+transcript}],
    }
    request = Request(
        "http://127.0.0.1:11435/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","X-AI-Source":"magazyn-datasheet-dev"},
        method="POST",
    )
    try:
        with build_opener().open(request,timeout=65) as res:
            data = json.load(io.BytesIO(res.read(MAX_RESPONSE)))
        raw = data.get("message",{}).get("content","")
        parsed = json.loads(raw)
        values = parsed.get("fields",[])
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError):
        return []
    if not isinstance(values,list):
        return []
    result = []
    for row in values[:25]:
        if not isinstance(row,dict):
            continue
        field = row.get("field")
        value = row.get("value")
        evidence = row.get("evidence")
        if (not isinstance(field,str) or field not in SPECS
                or not isinstance(value,str) or not isinstance(evidence,str)):
            continue
        # Without verbatim evidence in the PDF the AI output is discarded.
        item=_suggest(field,value,evidence,pages,family=family)
        if item is not None and len(item["value"]) <= 160:
            result.append(item)
    return result


def inspect_pdf(binary: bytes, part_no: str, *, manufacturer: str = "",
                source_url: str = "", source_name: str = "Plik użytkownika") -> dict:
    part_no=code(part_no)
    if len(binary)>MAX_DOCUMENT or not binary.startswith(b"%PDF-"):
        raise Problem(422,"Wymagany PDF nie większy niż 8 MB")
    pages=_pdf_text(binary)
    exact,family=_has_exact_mpn(part_no,pages)
    if not exact:
        raise Problem(422,
            "Nie potwierdzono dokładnego oznaczenia elementu w dokumencie. "
            "Wybierz właściwy wariant lub użyj innej karty.")
    result=_rules(part_no,manufacturer,pages,family)
    supplemental=_llm_extract(part_no,pages,family)
    for row in supplemental:
        if row["field"] in ("manufacturer","primary_number"):
            continue
        if not any(x["field"]==row["field"] for x in result):
            result.append(row)
    warnings=[]
    if family:
        warnings.append("Dokument obejmuje także inne warianty. Parametry elektryczne wymagają sprawdzenia wersji.")
    if not supplemental and os.environ.get("MAGAZYN_DATASHEET_AI_ENABLED","0")=="1":
        warnings.append("Analiza AI chwilowo niedostępna; zastosowano odczyt podstawowy.")
    # PDF is only attached on explicit user confirmation and normal Add part.
    return {
        "part_number":part_no,
        "source_name":source_name,
        "source_url":source_url,
        "family_datasheet":family,
        "pages_checked":len(pages),
        "suggestions":result,
        "warnings":warnings,
        "pdf_base64":base64.b64encode(binary).decode("ascii"),
        "filename":re.sub(r"[^A-Z0-9._-]","_",part_no)+"-datasheet.pdf",
    }


class DatasheetFinder:
    def __init__(self):
        self._tokens={}
        self._lock=threading.Lock()

    def _register(self,user_id:int,part_no:str,url:str,manufacturer:str,source_name:str) -> dict:
        _allowed_url(url)
        token=secrets.token_urlsafe(24)
        with self._lock:
            now=time.monotonic()
            self._tokens={k:v for k,v in self._tokens.items() if v["expires"]>now}
            if len(self._tokens)>=200:
                self._tokens.clear()
            self._tokens[token] = {
                "user":user_id,"part":part_no,"url":url,"manufacturer":manufacturer,
                "source_name":source_name,"expires":now+600,
            }
        return {
            "token":token,"part_number":part_no,
            "source":source_name,"manufacturer":manufacturer,
            "domain":urlsplit(url).hostname,
            "requires_confirmation":True,
        }

    def discover(self,user_id:int,marking:str,manufacturer:str="") -> dict:
        part_no=code(marking)
        maker=str(manufacturer or "").strip()[:100]
        matches=[]
        # Texas Instruments supplies public canonical datasheets at this path.
        ti = ("TEXAS INSTRUMENTS","TEXAS","TI")
        prefixes=("LM","TLV","TPS","SN74","INA","OPA","CSD","UCC","BQ","DRV")
        if (maker.upper() in ti or
                (not maker and part_no.startswith(prefixes))):
            url="https://www.ti.com/lit/ds/symlink/"+quote(part_no.lower())+".pdf"
            matches.append(self._register(user_id,part_no,url,
                                          "Texas Instruments","Texas Instruments"))
        # Mouser official Search API requires a user's opt-in API key.
        api_key=os.environ.get("MAGAZYN_MOUSER_API_KEY","")
        if api_key:
            matches.extend(self._mouser(user_id,part_no,api_key))
        # Public LCSC product detail is not an officially supported API. Keep
        # this optional and easy to disable if distributor changes its terms.
        if (os.environ.get("MAGAZYN_DATASHEET_LCSC_EXPERIMENTAL","0")=="1"
                and re.fullmatch(r"C[0-9]{5,10}",part_no)):
            candidate=self._lcsc(user_id,part_no)
            if candidate: matches.append(candidate)
        return {
            "marking":part_no,
            "candidates":matches[:MAX_SEARCH],
            "message":"Wybierz producenta i zweryfikuj wariant przed pobraniem."
                      if matches else
                      "Brak zweryfikowanego źródła online. Możesz dołączyć PDF ręcznie.",
        }

    def _mouser(self,user_id:int,part_no:str,api_key:str) -> list[dict]:
        # The API endpoint is fixed. The API key is never returned or logged.
        request = Request(
            "https://api.mouser.com/api/v1/search/partnumber?apiKey="+quote(api_key),
            data=json.dumps({"SearchByPartRequest":{
                "mouserPartNumber":part_no,"partSearchOptions":"Exact"}}).encode(),
            headers={"Content-Type":"application/json"},
            method="POST",
        )
        try:
            with build_opener(_NoRedirect).open(request,timeout=9) as response:
                data=json.loads(response.read(MAX_RESPONSE))
        except (HTTPError,URLError,OSError,TimeoutError,ValueError):
            return []
        results=[]
        for row in data.get("SearchResults",{}).get("Parts",[])[:8]:
            if not isinstance(row,dict):
                continue
            mpn=str(row.get("ManufacturerPartNumber") or "").strip()
            if normalized(mpn)!=normalized(part_no):
                continue
            pdf_url=str(row.get("DataSheetUrl") or "")
            try:
                _allowed_url(pdf_url)
            except Problem:
                continue
            results.append(self._register(
                user_id,part_no,pdf_url,
                str(row.get("Manufacturer") or "")[:100],
                "Mouser — karta producenta",
            ))
        return results[:MAX_SEARCH]

    def _lcsc(self,user_id:int,part_no:str) -> dict | None:
        url="https://wmsc.lcsc.com/ftps/wm/product/detail?productCode="+quote(part_no)
        try:
            data=json.loads(_fetch(url,max_bytes=MAX_RESPONSE,accept="application/json"))
            row=data.get("result") or {}
            if str(row.get("productCode","")).upper()!=part_no:
                return None
            pdf_url=str(row.get("pdfUrl") or "")
            _allowed_url(pdf_url)
            return self._register(
                user_id,str(row.get("productModel") or part_no).upper(),
                pdf_url,str(row.get("brandNameEn") or "")[:100],
                "LCSC — karta katalogowa",
            )
        except (ValueError,Problem,TypeError):
            return None

    def analyze_token(self,user_id:int,token:str) -> dict:
        with self._lock:
            info=self._tokens.get(token)
            if not info or info["user"]!=user_id or info["expires"]<=time.monotonic():
                raise Problem(404,"Wynik wyszukiwania wygasł. Wyszukaj ponownie.")
            info=info.copy()
        data=_fetch(info["url"],max_bytes=MAX_DOCUMENT)
        _pdf_bytes(base64.b64encode(data).decode("ascii"))
        return inspect_pdf(
            data,info["part"],
            manufacturer=info["manufacturer"],
            source_url=info["url"],
            source_name=info["source_name"],
        )

    def analyze_upload(self,part_no:str,pdf_base64:str) -> dict:
        return inspect_pdf(_pdf_bytes(pdf_base64),part_no)
