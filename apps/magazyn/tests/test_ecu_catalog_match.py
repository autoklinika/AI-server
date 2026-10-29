"""Isolated, read-only matching against real Magazyn schema (no production DB)."""
import pytest
from fastapi.testclient import TestClient

from magazyn.server import create_app


@pytest.fixture
def warehouse(tmp_path):
    app = create_app(str(tmp_path / "catalog-match.sqlite3"), secure_cookie=False)
    store = app.state.store
    store.create_user("matcher", "secure-warehouse-test-password-123", "user")
    with TestClient(app) as client:
        auth = client.post("/api/auth/login", json={
            "username": "matcher", "password": "secure-warehouse-test-password-123"
        })
        assert auth.status_code == 200
        headers = {"X-CSRF-Token": auth.json()["csrf"]}

        def item(primary, hw, sw, kind="ecu", model="EDC17C46"):
            data = {
                "kind": kind, "brand": "DAF",
                "brands": ["VW", "DAF"] if kind == "ecu" else [],
                "designation": "Bosch EDC17C46",
                "manufacturer": "Bosch", "category": "ECU silnika",
                "model": model, "primary_number": primary,
                "hw": hw, "sw": sw,
                "numbers": [{"number": "03L 906 022 GC", "number_type": "OEM"}],
            }
            created = client.post("/api/items", json=data, headers=headers)
            assert created.status_code == 201, created.text
            return created.json()["id"]

        first = item("0 281 016 738", "H1", "S3")
        second = item("0 281 016 738", "H2", "S4")
        # A different product category with the same identifier must never
        # contaminate ECU identification.
        item("0 281 016 738", "", "", kind="part")
        yield client, headers, first, second


def _scan(**updates):
    data = {
        "primary_number": "0281016738", "oem_numbers": ["03L906022GC"],
        "candidate_numbers": ["0 281 016 738", "03L-906-022-GC"],
        "serial_number": "987654321",
        "manufacturer": "Bosch", "vehicle_brand": "DAF",
        "model": "EDC17C46", "hw": "H1", "sw": "S3",
    }
    data.update(updates)
    return data


def test_exact_main_and_oem_cross_reference_distinguishes_hardware(warehouse):
    client, headers, first, second = warehouse
    response = client.post("/api/ecu-label/catalog-match",
                           json=_scan(), headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "matched_variant"
    assert result["recommended_id"] == first
    assert {x["id"] for x in result["matches"]} == {first, second}
    exact = next(x for x in result["matches"] if x["id"] == first)
    different = next(x for x in result["matches"] if x["id"] == second)
    assert exact["match_count"] == 2
    assert exact["variant_status"] == "same_variant_candidate"
    assert exact["hw"] == "H1" and exact["sw"] == "S3"
    assert {x["scan_role"] for x in exact["matched_numbers"]} == {"main", "oem"}
    assert different["variant_status"] == "conflict"
    assert set(different["conflicts"]) == {"hw", "sw"}
    assert exact["category"] == "ECU silnika"
    assert "notes" not in exact


def test_without_scanned_hw_sw_never_claims_same_variant(warehouse):
    client, headers, _first, _second = warehouse
    result = client.post("/api/ecu-label/catalog-match",
                         json=_scan(hw="", sw=""), headers=headers).json()
    assert result["status"] == "review_needed"
    assert result["recommended_id"] is None
    assert all(row["variant_status"] == "verify_variant"
               for row in result["matches"])


def test_conflicting_hw_sw_never_suggests_same_variant(warehouse):
    client, headers, _first, _second = warehouse
    result = client.post("/api/ecu-label/catalog-match",
                         json=_scan(hw="H9", sw="S9"), headers=headers).json()
    assert result["recommended_id"] is None
    assert all(row["variant_status"] == "conflict" for row in result["matches"])


def test_catalog_lookup_by_oem_alias_even_when_no_main_number(warehouse):
    client, headers, first, second = warehouse
    result = client.post("/api/ecu-label/catalog-match",
                         json=_scan(primary_number="", candidate_numbers=[]),
                         headers=headers).json()
    assert {x["id"] for x in result["matches"]} == {first, second}
    assert result["recommended_id"] == first
    assert all(any(v["scan_role"] == "oem" for v in x["matched_numbers"])
               for x in result["matches"])


def test_unlabelled_number_cannot_autoconfirm_variant(warehouse):
    client, headers, _first, _second = warehouse
    result = client.post("/api/ecu-label/catalog-match",
                         json=_scan(primary_number="", oem_numbers=[],
                                    candidate_numbers=["0281016738"]),
                         headers=headers).json()
    assert result["recommended_id"] is None
    assert result["status"] == "review_needed"


def test_serial_and_hardware_never_used_as_catalog_identifiers(warehouse):
    client, headers, _first, _second = warehouse
    result = client.post("/api/ecu-label/catalog-match",
                         json=_scan(primary_number="", oem_numbers=[],
                                    candidate_numbers=["987654321", "H1", "S3"]),
                         headers=headers).json()
    assert result["status"] == "no_identifiers"
    assert result["matches"] == []


def test_no_fuzzy_guess_for_one_digit_difference(warehouse):
    client, headers, _first, _second = warehouse
    result = client.post("/api/ecu-label/catalog-match",
                         json=_scan(primary_number="0281016739",
                                    oem_numbers=[],candidate_numbers=[]),
                         headers=headers).json()
    assert result["status"] == "not_found"
    assert result["recommended_id"] is None


def test_match_is_readonly_and_requires_authenticated_csrf(warehouse):
    client, headers, _first, _second = warehouse
    client.post("/api/auth/logout", json={}, headers=headers)
    assert client.post("/api/ecu-label/catalog-match",
                       json=_scan()).status_code == 401
    auth = client.post("/api/auth/login", json={
        "username": "matcher", "password": "secure-warehouse-test-password-123"
    })
    assert auth.status_code == 200
    csrf = {"X-CSRF-Token": auth.json()["csrf"]}
    assert client.post("/api/ecu-label/catalog-match", json=_scan()).status_code == 403
    before = client.get("/api/items", params={"kind": "ecu"}).json()
    history = client.get("/api/history").json()
    result = client.post("/api/ecu-label/catalog-match", json=_scan(),
                         headers=csrf)
    assert result.status_code == 200
    assert client.get("/api/items", params={"kind": "ecu"}).json() == before
    assert client.get("/api/history").json() == history


def test_reject_unbounded_input(warehouse):
    client, headers, *_ = warehouse
    invalid = _scan(candidate_numbers=["x" * 50] * 26)
    response = client.post("/api/ecu-label/catalog-match",
                           json=invalid, headers=headers)
    assert response.status_code == 422
