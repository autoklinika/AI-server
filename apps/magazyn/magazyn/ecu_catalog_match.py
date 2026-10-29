"""Read-only, exact-identifier cross-reference against the existing Magazyn DB.

No write operations, external services, or schema migrations.
One supplier/OEM number may belong to multiple ECU hardware/software variants.
A number match is never proof that the physical unit has identical HW/SW.
"""
from __future__ import annotations

import re

from .store import normalize

MAX_QUERY_NUMBERS = 25
MAX_MATCHES = 12
_CODE = re.compile(r"^[A-Z0-9]{7,35}$")
_ROLE_PRIORITY = {"candidate": 1, "oem": 2, "main": 3}
_ROLE_POINTS = {"candidate": 18, "oem": 45, "main": 70}


def _key(value: object) -> str:
    raw = str(value or "")[:160]
    code = normalize(raw)
    if not _CODE.fullmatch(code) or not any(ch.isdigit() for ch in code):
        return ""
    return code


def _short(value: object, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _normalized(value: object) -> str:
    return normalize(_short(value))


def _inputs(scan: dict) -> dict[str, dict]:
    collected: dict[str, dict] = {}
    excluded = {
        _key(scan.get("serial_number")),
        _key(scan.get("hw")),
        _key(scan.get("sw")),
    }
    excluded.discard("")

    def include(value: object, role: str) -> None:
        if len(collected) >= MAX_QUERY_NUMBERS and _key(value) not in collected:
            return
        code = _key(value)
        if not code or code in excluded:
            return
        old = collected.get(code)
        if old is None or _ROLE_PRIORITY[role] > _ROLE_PRIORITY[old["role"]]:
            collected[code] = {"number": _short(value, 80),
                               "normalized": code, "role": role}

    include(scan.get("primary_number"), "main")
    for raw in scan.get("oem_numbers", [])[:12]:
        include(raw, "oem")
    for raw in scan.get("candidate_numbers", [])[:25]:
        include(raw, "candidate")
    return collected


def match_existing_ecu(store, scan: dict) -> dict:
    """Return catalog comparisons with explicit conflict and evidence markers.

    Never infer a vehicle brand or copy HW/SW from the catalog when missing on
    the photographed controller. The UI may show catalog values only as proposed
    reviewable fields, with the original scan always taking precedence.
    """
    source = _inputs(scan)
    if not source:
        return {
            "status": "no_identifiers",
            "matches": [], "recommended_id": None,
            "message": "Brak dostatecznie pewnych numerów do porównania z bazą.",
        }

    identifiers = tuple(source)
    placeholders = ",".join("?" for _ in identifiers)
    with store.connect() as con:
        raw = con.execute(
            "SELECT n.item_id,n.number AS stored_number,n.normalized,n.number_type,"
            "i.designation,i.brand,i.manufacturer,i.category,i.model,"
            "i.primary_number,i.hw,i.sw "
            "FROM item_numbers n JOIN items i ON i.id=n.item_id "
            "WHERE i.kind='ecu' AND n.normalized IN ("+placeholders+") "
            "ORDER BY n.item_id DESC,n.number_type ASC", identifiers,
        ).fetchall()

        grouped = {}
        for row in raw:
            item_id = row["item_id"]
            if item_id not in grouped:
                grouped[item_id] = {"item": row, "hits": []}
            role = source[row["normalized"]]
            grouped[item_id]["hits"].append({
                "scanned_number": role["number"],
                "stored_number": row["stored_number"],
                "scan_role": role["role"],
                "stored_type": row["number_type"],
                "normalized": row["normalized"],
            })

        results = []
        for item_id, candidate in grouped.items():
            item = candidate["item"]
            brands = [row[0] for row in con.execute(
                "SELECT brand FROM item_brands WHERE item_id=? ORDER BY brand",
                (item_id,),
            )]
            conflicts = []
            matched_attributes = []

            def compare(field: str, wanted: str, existing: str) -> None:
                if not wanted or not existing:
                    return
                if _normalized(wanted) == _normalized(existing):
                    matched_attributes.append(field)
                else:
                    conflicts.append(field)

            compare("manufacturer", scan.get("manufacturer"), item["manufacturer"])
            compare("model", scan.get("model"), item["model"])
            compare("hw", scan.get("hw"), item["hw"])
            compare("sw", scan.get("sw"), item["sw"])
            vehicle_brand = _short(scan.get("vehicle_brand"))
            if vehicle_brand:
                current_brands = [*brands, item["brand"]]
                current_brands = [str(value) for value in current_brands if value]
                if current_brands and _normalized(vehicle_brand) not in {
                    _normalized(value) for value in current_brands
                }:
                    conflicts.append("brand")
                elif current_brands:
                    matched_attributes.append("brand")

            best_role = max(
                (h["scan_role"] for h in candidate["hits"]),
                key=lambda r: _ROLE_PRIORITY[r],
            )
            explicit = any(h["scan_role"] in ("main", "oem")
                           for h in candidate["hits"])
            strong_hw = bool(_normalized(scan.get("hw")) and
                             _normalized(item["hw"]) and
                             _normalized(scan.get("hw")) == _normalized(item["hw"]))
            strong_sw = bool(_normalized(scan.get("sw")) and
                             _normalized(item["sw"]) and
                             _normalized(scan.get("sw")) == _normalized(item["sw"]))
            if conflicts:
                variant_status = "conflict"
            elif explicit and strong_hw and strong_sw:
                variant_status = "same_variant_candidate"
            else:
                variant_status = "verify_variant"

            points = (
                _ROLE_POINTS[best_role] +
                10 * (len({h["normalized"] for h in candidate["hits"]}) - 1) +
                6 * len(matched_attributes) -
                15 * len(conflicts)
            )
            qty = con.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM balances WHERE item_id=?",
                (item_id,),
            ).fetchone()[0]
            results.append({
                "id": int(item_id),
                "designation": _short(item["designation"], 200),
                "brand": _short(item["brand"]),
                "brands": [_short(b) for b in brands],
                "manufacturer": _short(item["manufacturer"]),
                "category": _short(item["category"]),
                "model": _short(item["model"]),
                "primary_number": _short(item["primary_number"]),
                "hw": _short(item["hw"]),
                "sw": _short(item["sw"]),
                "quantity": int(qty),
                "matched_numbers": [
                    {k: h[k] for k in
                     ("scanned_number", "stored_number", "scan_role", "stored_type")}
                    for h in candidate["hits"]
                ],
                "match_count": len({h["normalized"] for h in candidate["hits"]}),
                "variant_status": variant_status,
                "conflicts": conflicts,
                "matched_attributes": matched_attributes,
                "score": points,
            })

    # This is an exact identifier lookup only. No unsourced near-miss digits.
    results.sort(
        key=lambda row: (
            row["variant_status"] == "same_variant_candidate",
            row["variant_status"] != "conflict",
            row["score"],
            row["match_count"],
            row["id"],
        ),
        reverse=True,
    )
    truncated = len(results) > MAX_MATCHES
    visible = results[:MAX_MATCHES]
    confirmed = [
        row for row in results if row["variant_status"] == "same_variant_candidate"
    ]
    recommended = confirmed[0]["id"] if len(confirmed) == 1 and not truncated else None
    if not visible:
        label = "Brak pozycji o dokładnie zgodnym numerze."
        status = "not_found"
    elif recommended:
        label = "Znaleziono wariant z tym samym numerem, HW i SW — potwierdź zgodność."
        status = "matched_variant"
    elif len(visible) == 1 and visible[0]["variant_status"] == "conflict":
        label = "Numer występuje w bazie, ale różni się wariantem lub opisem."
        status = "variant_conflict"
    else:
        label = "Znaleziono numery w bazie — porównaj warianty i wybierz pozycję."
        status = "review_needed"

    return {
        "status": status,
        "matches": visible,
        "recommended_id": recommended,
        "truncated": truncated,
        "message": label,
    }
