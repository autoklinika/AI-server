"""Source-backed manufacturer fallback when TME/Mouser have no exact MPN.

Only a conservative fixed registry of independently verified manufacturer pages.
A *different* input MPN is NEVER treated as equivalent to a reference MPN.
No API keys, GPU use, inventory writes, file caching or untrusted URL fetching.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re

from .part_datasheets import _fetch
from .store import Problem


# Approved manufacturer pages, expanded only when their page evidence has
# actually been validated. NOT a fuzzy manufacturer-part-number search engine.
REFERENCES = (
    {
        "mpn": "LM2309",
        "manufacturer": "Leiditech",
        "type": "Tranzystor MOSFET",
        "category": "Tranzystory i MOSFET-y",
        "package": "SOT-23",
        "source_url": (
            "https://en.leiditech.com/blogs-detail/"
            "replacement-of-the-corresponding-brand-material-number-of-"
            "leiditech-field-effect-transistor"
        ),
        "evidence_pattern": r"(?i)\bmosfet\s+LM2309\s+SOT-23\b",
        "source_name": "Leiditech — oficjalna lista MOSFET",
    },
)


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data)


def _content(url):
    # _fetch enforces HTTPS domain allowlist, blocks redirects, bounds data.
    html=_fetch(url,max_bytes=230_000,accept="text/html")
    parser=_PlainText()
    parser.feed(html.decode("utf-8","replace"))
    return " ".join(" ".join(parser.parts).split())


def _relation(marking: str, candidate: str) -> str:
    request=marking.casefold()
    reference=candidate.casefold()
    if request==reference:
        return "exact"
    # One unsupported trailing alphanumeric is an *unverified* candidate,
    # not an ordering suffix, known marking, or a proof of common identity.
    if len(request)==len(reference)+1 and request.startswith(reference) and request[-1].isalnum():
        return "possible_suffix"
    return ""


def lookup_manufacturer_references(mpn: str) -> dict:
    if not isinstance(mpn,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./,_-]{3,59}",mpn):
        raise ValueError("Nieprawidłowe oznaczenie elementu")
    results=[]
    for reference in REFERENCES:
        relation=_relation(mpn,reference["mpn"])
        if not relation:
            continue
        try:
            text=_content(reference["source_url"])
        except (Problem,UnicodeError,ValueError):
            continue
        match=re.search(reference["evidence_pattern"],text)
        if not match:
            continue
        exact=relation=="exact"
        phrase=match.group(0)
        suggestions=[]
        for field,value in (
            ("manufacturer",reference["manufacturer"]),
            ("category",reference["category"]),
            ("package",reference["package"]),
        ):
            suggestions.append({
                "field":field,"value":value,
                "confidence":"document" if exact else "verify_variant",
                "evidence":phrase,
                "source":"manufacturer_page",
            })
        results.append({
            "reference_mpn":reference["mpn"],
            "requested_mpn":mpn,
            "exact_mpn":exact,
            "relation":relation,
            "source_kind":"manufacturer_reference",
            "source_name":reference["source_name"],
            "manufacturer":reference["manufacturer"],
            "source_url":reference["source_url"],
            "source_evidence":phrase,
            "suggestions":suggestions,
            "documents":[],
            "warnings":([] if exact else [
                "Oznaczenie "+mpn+" nie zostało potwierdzone przez producenta. "
                "Znaleziono tylko "+reference["mpn"]+
                ". Litera/sufiks może wskazywać odmienny element, wariant lub oznaczenie obudowy.",
                "Nie przenoś parametrów elektrycznych bez identyfikacji obudowy, logo i dokumentacji."
            ]),
            "manual_approval_required":True,
            "family_datasheet":not exact,
        })
    return {
        "status":"verified_reference" if any(x["exact_mpn"] for x in results)
            else "possible_reference" if results else "not_found",
        "query":mpn,
        "candidates":results,
        "manual_approval_required":True,
        "notice":("Dane oparte na stronie producenta, nie na TME/Mouser. "
                  "Różne numery MPN nigdy nie są automatycznie utożsamiane."),
    }
