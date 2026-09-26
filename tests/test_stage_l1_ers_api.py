from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from ai_bridge.api.app import create_app
from ai_bridge.domains.ers.adapter import ERSAdapter
from ai_bridge.domains.ers.storage.models import ErsCaseCounterModel
from ai_bridge.settings import Settings
from ai_bridge.storage.base import Base


def setup_client(tmp_path):
    application = create_app(
        Settings(database_url="sqlite+pysqlite:///" + str(tmp_path / "ers-api.sqlite")),
        domains=(ERSAdapter(),),
    )
    client = TestClient(application)
    client.__enter__()
    Base.metadata.create_all(application.state.database.engine)
    with application.state.database.session() as session:
        session.add(ErsCaseCounterModel(counter_name="case", next_value=1))
    return application, client


def close_client(client):
    client.__exit__(None, None, None)


def create_case(client, *, legacy=None):
    payload = {
        "schema_version": 1,
        "title": "Scania EMS S6 clone",
        "actor_id": "operator",
        "metadata": {"source": "workshop"},
    }
    if legacy is not None:
        payload["legacy_case_code"] = legacy
    return client.post("/api/v1/ecu-repair/cases", json=payload)


def test_ers_is_default_production_domain_and_can_be_explicitly_omitted():
    default = create_app(Settings(database_url="sqlite+pysqlite://"))
    assert "/api/v1/ecu-repair/cases" in default.openapi()["paths"]

    without_domains = create_app(
        Settings(database_url="sqlite+pysqlite://"),
        domains=(),
    )
    assert "/api/v1/ecu-repair/cases" not in without_domains.openapi()["paths"]


def test_case_create_get_patch_etag_and_stale_conflict(tmp_path):
    _app, client = setup_client(tmp_path)
    try:
        created = create_case(client, legacy="CASE-0002-SCANIA")
        assert created.status_code == 201, created.text
        case = created.json()["case"]
        case_id = case["id"]
        assert case["case_code"] == "CASE-000001"
        assert case["row_version"] == 1
        assert created.headers["etag"] == 'W/"1"'

        fetched = client.get(f"/api/v1/ecu-repair/cases/{case_id}")
        assert fetched.status_code == 200
        assert fetched.headers["etag"] == 'W/"1"'
        assert fetched.json()["events"][0]["event_type"] == "created"

        missing_precondition = client.patch(
            f"/api/v1/ecu-repair/cases/{case_id}",
            json={"actor_id": "operator", "work_state": "diagnosing"},
        )
        assert missing_precondition.status_code == 428

        patched = client.patch(
            f"/api/v1/ecu-repair/cases/{case_id}",
            headers={"If-Match": 'W/"1"', "X-Correlation-Id": "corr-1"},
            json={
                "actor_id": "operator",
                "title": "Scania EMS S6 clone — bench",
                "work_state": "diagnosing",
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.headers["etag"] == 'W/"2"'
        assert patched.json()["case"]["row_version"] == 2

        stale = client.patch(
            f"/api/v1/ecu-repair/cases/{case_id}",
            headers={"If-Match": 'W/"1"'},
            json={"actor_id": "operator", "work_state": "verifying"},
        )
        assert stale.status_code == 409
        assert stale.json()["error"] == "case_version_conflict"
    finally:
        close_client(client)


def test_case_list_is_bounded_and_newest_first(tmp_path):
    _app, client = setup_client(tmp_path)
    try:
        first = create_case(client, legacy="CASE-LIST-1").json()["case"]
        second = create_case(client, legacy="CASE-LIST-2").json()["case"]

        updated = client.patch(
            f"/api/v1/ecu-repair/cases/{first['id']}",
            headers={"If-Match": 'W/"1"'},
            json={"actor_id": "operator", "work_state": "diagnosing"},
        )
        assert updated.status_code == 200, updated.text

        response = client.get("/api/v1/ecu-repair/cases")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["schema_version"] == 1
        assert payload["count"] == 2
        assert payload["limit"] == 100
        assert [item["id"] for item in payload["cases"]] == [first["id"], second["id"]]
        assert payload["cases"][0]["work_state"] == "diagnosing"
    finally:
        close_client(client)


def test_lifecycle_requires_valid_transition_and_explicit_reopen(tmp_path):
    _app, client = setup_client(tmp_path)
    try:
        case_id = create_case(client).json()["case"]["id"]

        invalid = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/events",
            headers={"If-Match": 'W/"1"'},
            json={"actor_id": "operator", "to_status": "closed"},
        )
        assert invalid.status_code == 409
        assert invalid.json()["error"] == "invalid_case_transition"

        version = 1
        for target in ("open", "resolved", "closed", "open"):
            response = client.post(
                f"/api/v1/ecu-repair/cases/{case_id}/events",
                headers={"If-Match": f'W/"{version}"'},
                json={"actor_id": "operator", "to_status": target},
            )
            assert response.status_code == 200, response.text
            version += 1
            assert response.headers["etag"] == f'W/"{version}"'

        detail = client.get(f"/api/v1/ecu-repair/cases/{case_id}").json()
        assert detail["case"]["status"] == "open"
        assert detail["case"]["resolved_at"] is None
        assert detail["case"]["closed_at"] is None
        assert detail["events"][-1]["event_type"] == "reopened"
        assert [event["event_seq"] for event in detail["events"]] == [1, 2, 3, 4, 5]
    finally:
        close_client(client)


def test_intake_end_to_end_is_versioned_and_readable(tmp_path):
    _app, client = setup_client(tmp_path)
    try:
        created = create_case(client)
        case_id = created.json()["case"]["id"]
        version = 1

        asset = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/assets",
            headers={"If-Match": f'W/"{version}"'},
            json={
                "actor_id": "operator",
                "asset_kind": "vehicle",
                "role": "subject",
                "manufacturer": "Scania",
                "model": "R-series",
                "vin": "YS2TEST",
                "engine_identity": {"engine": "DC1210"},
            },
        )
        assert asset.status_code == 201, asset.text
        version += 1
        assert asset.headers["etag"] == f'W/"{version}"'

        ecu = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/ecus",
            headers={"If-Match": f'W/"{version}"'},
            json={
                "actor_id": "operator",
                "role": "original",
                "manufacturer": "Scania",
                "family": "EMS S6",
                "hardware_number": "1726100",
                "serial_number": "ORI",
                "mcu_marking": "MPC555LF8MZP40",
                "software_number": "1796080",
            },
        )
        assert ecu.status_code == 201, ecu.text
        ecu_id = ecu.json()["entity_id"]
        version += 1

        symptom = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/symptoms",
            headers={"If-Match": f'W/"{version}"'},
            json={
                "actor_id": "operator",
                "description": "Donor ECU must be cloned from original",
                "operating_context": {"location": "bench"},
            },
        )
        assert symptom.status_code == 201
        version += 1

        dtc = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/dtcs",
            headers={"If-Match": f'W/"{version}"'},
            json={
                "actor_id": "operator",
                "protocol": "J1939",
                "ecu_id": ecu_id,
                "spn": 107,
                "fmi": 3,
                "occurrence_count": 34,
                "status": "historical",
            },
        )
        assert dtc.status_code == 201, dtc.text
        version += 1

        measurement = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/measurements",
            headers={"If-Match": f'W/"{version}"'},
            json={
                "actor_id": "operator",
                "measurement_type": "supply_voltage",
                "ecu_id": ecu_id,
                "channel": "KL30",
                "value_numeric": 24.3,
                "unit": "V",
                "method": "DMM",
            },
        )
        assert measurement.status_code == 201, measurement.text
        version += 1

        step = client.post(
            f"/api/v1/ecu-repair/cases/{case_id}/diagnostic-steps",
            headers={"If-Match": f'W/"{version}"'},
            json={
                "actor_id": "operator",
                "step_type": "measurement",
                "observation": "ECU powers up on bench",
                "test": "Read identification",
                "result": "Communication OK",
                "next_step": "Compare binaries",
            },
        )
        assert step.status_code == 201, step.text
        version += 1
        assert step.json()["extra_ids"]["step_seq"] == 1

        detail_response = client.get(f"/api/v1/ecu-repair/cases/{case_id}")
        assert detail_response.headers["etag"] == f'W/"{version}"'
        detail = detail_response.json()
        assert detail["case"]["row_version"] == version
        assert len(detail["assets"]) == 1
        assert len(detail["asset_revisions"]) == 1
        assert detail["asset_revisions"][0]["manufacturer"] == "Scania"
        assert len(detail["ecus"]) == 1
        assert detail["ecu_identity_observations"][0]["hardware_number"] == "1726100"
        assert detail["ecu_software_observations"][0]["software_number"] == "1796080"
        assert len(detail["symptoms"]) == 1
        assert detail["dtcs"][0]["spn"] == 107
        assert detail["measurements"][0]["value_numeric"] == 24.3
        assert detail["diagnostic_steps"][0]["step_seq"] == 1
        assert [e["event_type"] for e in detail["events"]][-6:] == [
            "asset_added",
            "ecu_added",
            "symptom_added",
            "dtc_added",
            "measurement_added",
            "diagnostic_step_added",
        ]
    finally:
        close_client(client)


def test_cross_case_ecu_reference_fails_without_advancing_version(tmp_path):
    _app, client = setup_client(tmp_path)
    try:
        first = create_case(client).json()["case"]
        second = create_case(client).json()["case"]

        ecu = client.post(
            f"/api/v1/ecu-repair/cases/{first['id']}/ecus",
            headers={"If-Match": 'W/"1"'},
            json={"actor_id": "operator", "role": "original", "family": "EMS S6"},
        )
        assert ecu.status_code == 201
        ecu_id = ecu.json()["entity_id"]

        bad = client.post(
            f"/api/v1/ecu-repair/cases/{second['id']}/measurements",
            headers={"If-Match": 'W/"1"'},
            json={
                "actor_id": "operator",
                "measurement_type": "voltage",
                "ecu_id": ecu_id,
                "value_numeric": 24.0,
                "unit": "V",
            },
        )
        assert bad.status_code == 400

        second_after = client.get(
            f"/api/v1/ecu-repair/cases/{second['id']}"
        ).json()
        assert second_after["case"]["row_version"] == 1
        assert len(second_after["events"]) == 1
        assert second_after["measurements"] == []
    finally:
        close_client(client)


def test_duplicate_legacy_case_code_is_conflict(tmp_path):
    _app, client = setup_client(tmp_path)
    try:
        assert create_case(client, legacy="CASE-LEGACY").status_code == 201
        duplicate = create_case(client, legacy="CASE-LEGACY")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"] == "ers_integrity_conflict"
    finally:
        close_client(client)



def test_ers_adapter_does_not_override_global_sqlalchemy_error_handler():
    application = create_app(
        Settings(database_url="sqlite+pysqlite://"),
        domains=(ERSAdapter(),),
    )
    assert IntegrityError not in application.exception_handlers
