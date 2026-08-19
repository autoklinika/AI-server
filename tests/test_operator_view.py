from ai_bridge.adapters.ventilation.analysis_v12 import (
    VentilationDecisionV12,
    build_fact_catalog,
)
from ai_bridge.analysis.operator_view import (
    render_insufficient_operator_view,
    render_operator_view,
)


def packet():
    return {
        "window": {"sample_count": 179},
        "analysis_context": {
            "historical_baseline_available": False,
            "expected_operating_state_known": False,
        },
        "controller": {
            "latest_mode": "MANUAL",
            "mode_counts": {"MANUAL": 179},
            "setpoints": {},
            "active_alarm_sample_count": 0,
            "active_alarm_codes": [],
        },
        "sensor_bus": {
            "ready_ratio": 1.0,
            "worker_alive_ratio": 1.0,
            "worker_restarts_max": 0,
            "latest_error": None,
            "nodes": {
                "1": {
                    "online_ratio": 1.0,
                    "measurement_valid_ratio": 1.0,
                    "measurement_stale_ratio": 0.0,
                    "consecutive_failures_max": 0,
                    "diagnostic_counter_deltas": {},
                    "readings": {
                        "voc_index": {
                            "count": 179,
                            "missing": 0,
                            "first": 84,
                            "last": 166,
                            "delta": 82,
                            "slope_per_minute": 2.204,
                        },
                        "pm2_5_ug_m3": {
                            "count": 179,
                            "missing": 0,
                            "first": 6.2,
                            "last": 6.6,
                            "delta": 0.4,
                            "slope_per_minute": 0.143,
                        },
                    },
                },
                "2": {
                    "online_ratio": 1.0,
                    "measurement_valid_ratio": 1.0,
                    "measurement_stale_ratio": 0.0,
                    "consecutive_failures_max": 0,
                    "diagnostic_counter_deltas": {},
                    "readings": {
                        "voc_index": {
                            "count": 179,
                            "missing": 0,
                            "first": 35,
                            "last": 37,
                            "delta": 2,
                            "slope_per_minute": 0.1874,
                        }
                    },
                },
            },
        },
    }


def test_attention_operator_view_is_short_and_human_readable():
    compact = packet()
    decision = VentilationDecisionV12(
        status="attention",
        reason_codes=["environmental_change"],
        selected_fact_ids=[
            "node:1:reading:voc_index",
            "node:1:reading:pm2_5_ug_m3",
            "node:2:reading:voc_index",
        ],
        recommendation_code="observe_next_windows",
    )

    view = render_operator_view(compact, decision, build_fact_catalog(compact))

    assert view.status_label_pl == "WYMAGA UWAGI"
    assert view.headline_pl == "Wzrost VOC Index — strefa 1"
    assert "VOC Index — strefa 1: wzrósł z 84 do 166." in view.summary_pl
    assert "VOC Index — strefa 2: wzrósł z 35 do 37." in view.summary_pl
    assert "historycznego punktu odniesienia" in view.summary_pl
    assert "slope_per_minute" not in view.summary_pl
    assert "missing=" not in view.summary_pl
    assert view.data_quality_short_pl == "Dane kompletne · 179 próbek"
    assert "baseline" not in view.data_quality_short_pl.lower()


def test_no_anomaly_operator_view_does_not_invent_measurement_claims():
    compact = packet()
    decision = VentilationDecisionV12(
        status="no_anomaly_detected",
        reason_codes=["no_significant_issue"],
        selected_fact_ids=[],
        recommendation_code="none",
    )

    view = render_operator_view(compact, decision, build_fact_catalog(compact))

    assert view.status_label_pl == "BRAK ANOMALII"
    assert view.headline_pl == "Brak zmian wymagających uwagi"
    assert "nie wykryto zmian wymagających uwagi" in view.summary_pl
    assert "historycznego punktu odniesienia" in view.summary_pl
    assert view.data_quality_short_pl == "Dane kompletne · 179 próbek"
    assert view.recommendation_pl == "Brak dodatkowych zaleceń dla tego okna."


def test_alarm_operator_view_translates_known_cm5_alarm_for_operator():
    compact = packet()
    compact["controller"]["active_alarm_sample_count"] = 5
    compact["controller"]["active_alarm_codes"] = ["SENSOR_BUS_UNAVAILABLE"]
    decision = VentilationDecisionV12(
        status="anomaly",
        reason_codes=["technical_alarm"],
        selected_fact_ids=["alarm:SENSOR_BUS_UNAVAILABLE"],
        recommendation_code="diagnose_active_alarm",
    )

    view = render_operator_view(compact, decision, build_fact_catalog(compact))

    assert view.status_label_pl == "ANOMALIA"
    assert view.headline_pl == "Aktywny alarm systemu"
    assert view.summary_pl.startswith("Magistrala czujników jest niedostępna.")
    assert "SENSOR_BUS_UNAVAILABLE" not in view.summary_pl
    assert view.data_quality_short_pl == "Dane kompletne · 179 próbek"
    assert "Sprawdź aktywne alarmy CM5" in view.recommendation_pl


def test_alarm_operator_view_hides_unknown_technical_code_from_main_copy():
    compact = packet()
    compact["controller"]["active_alarm_sample_count"] = 1
    compact["controller"]["active_alarm_codes"] = ["SOME_FUTURE_TECHNICAL_CODE"]
    decision = VentilationDecisionV12(
        status="anomaly",
        reason_codes=["technical_alarm"],
        selected_fact_ids=["alarm:SOME_FUTURE_TECHNICAL_CODE"],
        recommendation_code="diagnose_active_alarm",
    )

    view = render_operator_view(compact, decision, build_fact_catalog(compact))

    assert view.summary_pl.startswith("CM5 zgłasza dodatkowy alarm techniczny.")
    assert "SOME_FUTURE_TECHNICAL_CODE" not in view.summary_pl
    assert view.data_quality_short_pl == "Dane kompletne · 179 próbek"


def test_data_quality_short_reports_missing_samples_without_mixing_alarm_state():
    compact = packet()
    compact["sensor_bus"]["nodes"]["1"]["readings"]["voc_index"]["missing"] = 4
    decision = VentilationDecisionV12(
        status="attention",
        reason_codes=["environmental_change"],
        selected_fact_ids=["node:1:reading:voc_index"],
        recommendation_code="observe_next_windows",
    )

    view = render_operator_view(compact, decision, build_fact_catalog(compact))

    assert view.data_quality_short_pl == (
        "Występują braki danych · 179 próbek · 4 brakujących odczytów"
    )


def test_insufficient_operator_view_is_deterministic():
    view = render_insufficient_operator_view(sample_count=20, min_samples=120)

    assert view.status_label_pl == "NIEWYSTARCZAJĄCE DANE"
    assert "20 próbek" in view.summary_pl
    assert "120" in view.summary_pl
    assert view.data_quality_short_pl == "Niepełne okno · 20 próbek"
