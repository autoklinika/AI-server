"""DEV: show explicit distributor variants when family MPN has no exact match.

Read-only, same-origin authenticated API. No fuzzy auto-fill. Never substitutes
a different complete MPN without explicit operator selection.
"""
import re


def _related(mpn: str, candidate: str) -> bool:
    """Related part numbers are suggestions to SELECT, never exact matches."""
    q=mpn.strip().casefold()
    p=candidate.strip().casefold()
    if not q or not p.startswith(q) or p==q:
        return False
    tail=p[len(q):]
    # Standard manufacturer variant separators; also support short suffixes
    # such as TJA1050TD. Longer unrelated prefixes are not accepted.
    return tail[0] in "/,-" or bool(re.fullmatch(r"[a-z0-9]{1,2}",tail))


def find_variants(engine, mpn: str) -> dict:
    if not isinstance(mpn,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./,_-]{3,39}",mpn):
        raise ValueError("Nieprawidłowy numer MPN")
    rows, statuses, seen = [], {}, set()
    for provider in ("tme","mouser"):
        # Reuse existing normalized, ranked supplier endpoint; credentials remain
        # private to server, the requested part number is untrusted input.
        reply=engine.search_one(provider,mpn)
        statuses[provider]=reply["status"]
        if reply["status"]!="ok":
            continue
        count=0
        for part in reply.get("results",[]):
            number=part.get("mpn","").strip()
            if not _related(mpn,number):
                continue
            key=(provider,number.casefold())
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "supplier":provider,
                "mpn":number[:120],
                "manufacturer":str(part.get("manufacturer") or "")[:150],
                "description":str(part.get("description") or "")[:160],
                "supplier_sku":str(part.get("supplier_sku") or "")[:100],
            })
            count+=1
            if count>=9:
                break
    return {
        "status":"variants_available" if rows else "not_found",
        "query":mpn,
        "variants":rows[:18],
        "statuses":statuses,
        "manual_selection_required":True,
        "notice":"Podano bazowe oznaczenie elementu. Wybierz pełny numer wariantu przed uzupełnieniem pól.",
    }
