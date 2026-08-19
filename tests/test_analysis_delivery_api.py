from __future__ import annotations

from datetime import datetime, timezone


def _save_analysis(
    client,
    *,
    analysis_id: str,
    source_id: str = "workshop-ventilation-cm5-01",
    window_start: datetime,
    window_end: datetime,
    analysis_text: str,
    operator_view: dict | None = None,
) -> None:
    result = {
        "schema_version": 2,
        "status": "no_anomaly_detected",
        "analysis_pl": analysis_text,
        "operator_recommendation_pl": "Raport doradczy; obserwować kolejne okna.",
        "data_quality_pl": "Kompletne okno testowe.",
    }
    if operator_view is not None:
        result["operator_view"] = operator_view

    client.app.state.ventilation_analysis_repository.save_analysis(
        analysis_id=analysis_id,
        source_id=source_id,
        window_start=window_start,
        window_end=window_end,
        model="qwen3.6:35b",
        prompt_version="ventilation-v10-baseline-safe",
        sample_count=180,
        input_summary={"audit_only": True},
        result=result,
        raw_response="internal raw response must not be delivered",
        prompt_eval_count=100,
        eval_count=20,
        total_duration_ns=123,
    )


def test_latest_analysis_returns_404_when_source_has_no_result(client) -> None:
    response = client.get(
        "/api/v1/ventilation/analysis/latest",
        params={"source_id": "workshop-ventilation-cm5-01"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "analysis_not_found"


def test_latest_analysis_returns_newest_stored_result_with_safety_flags(client) -> None:
    first_start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    first_end = datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc)
    second_start = datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc)
    second_end = datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)

    _save_analysis(
        client,
        analysis_id="00000000-0000-0000-0000-000000000001",
        window_start=first_start,
        window_end=first_end,
        analysis_text="Starsza analiza.",
    )
    _save_analysis(
        client,
        analysis_id="00000000-0000-0000-0000-000000000002",
        window_start=second_start,
        window_end=second_end,
        analysis_text="Najnowsza analiza.",
        operator_view={
            "schema_version": 1,
            "status_label_pl": "BRAK ANOMALII",
            "headline_pl": "Brak istotnych zmian",
            "summary_pl": "W bieżącym oknie nie wykryto zmian wymagających uwagi operatora.",
            "recommendation_pl": "Brak dodatkowych zaleceń dla tego okna.",
            "data_quality_short_pl": "Dane kompletne · 180 próbek",
        },
    )

    response = client.get(
        "/api/v1/ventilation/analysis/latest",
        params={"source_id": "workshop-ventilation-cm5-01"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["delivery_schema_version"] == 1
    assert payload["analysis_id"] == "00000000-0000-0000-0000-000000000002"
    assert payload["source_id"] == "workshop-ventilation-cm5-01"
    assert payload["window_start"] == "2026-08-10T12:15:00Z"
    assert payload["window_end"] == "2026-08-10T12:30:00Z"
    assert payload["sample_count"] == 180
    assert payload["model"] == "qwen3.6:35b"
    assert payload["prompt_version"] == "ventilation-v10-baseline-safe"
    assert payload["advisory_only"] is True
    assert payload["experimental"] is True
    assert payload["control_actions_supported"] is False
    assert payload["result"]["schema_version"] == 2
    assert payload["result"]["analysis_pl"] == "Najnowsza analiza."
    assert payload["result"]["operator_view"] == {
        "schema_version": 1,
        "status_label_pl": "BRAK ANOMALII",
        "headline_pl": "Brak istotnych zmian",
        "summary_pl": "W bieżącym oknie nie wykryto zmian wymagających uwagi operatora.",
        "recommendation_pl": "Brak dodatkowych zaleceń dla tego okna.",
        "data_quality_short_pl": "Dane kompletne · 180 próbek",
    }

    # Delivery intentionally excludes audit/raw/model-runtime internals.
    assert "input_summary" not in payload
    assert "raw_response" not in payload
    assert "prompt_eval_count" not in payload
    assert "eval_count" not in payload
    assert "total_duration_ns" not in payload


def test_latest_analysis_is_get_only_and_no_control_route_is_added(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    latest = paths["/api/v1/ventilation/analysis/latest"]
    assert set(latest) == {"get"}

    forbidden = ("control", "command", "set-speed", "actuator")
    assert all(not any(word in path.lower() for word in forbidden) for path in paths)
