from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_environment_prompt_from_compact,
    strip_alert_context,
)


def test_v12_2_freezes_adverse_trend_gate_and_alert_boundary() -> None:
    assert PROMPT_VERSION == "ventilation-v12.2.1-no-alert-context"
    assert ANALYSIS_THINK is False
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "potencjalnie niekorzystną albo mieszaną zmianę" in normalized
    assert "PM, VOC Index i NOx Index są stabilne albo ogólnie maleją" in normalized
    assert "environmental_attention=false" in normalized
    assert "selected_fact_ids=[]" in normalized
    assert "spadek PM przy równoczesnym wyraźnym wzroście VOC Index" in normalized
    assert "łagodna zmiana temperatury lub wilgotności" in normalized
    assert "Alerty operatora są obsługiwane przez osobną zakładkę HMI" in normalized
    assert "Nie rekonstruuj, nie zgaduj ani nie raportuj kodów" in normalized


def test_alert_state_is_removed_before_advisory_resolution_and_model_input() -> None:
    packet = {
        "window": {"sample_count": 180},
        "analysis_context": {},
        "controller": {
            "latest_mode": "STOP",
            "active_alarm_sample_count": 180,
            "active_alarm_codes": ["SENSOR_NODE_UNAVAILABLE", "AERO_BUS_UNAVAILABLE"],
        },
        "sensor_bus": {"nodes": {}},
    }

    clean = strip_alert_context(packet)
    assert clean["controller"]["latest_mode"] == "STOP"
    assert "active_alarm_sample_count" not in clean["controller"]
    assert "active_alarm_codes" not in clean["controller"]
    # The audit/source packet is not mutated.
    assert packet["controller"]["active_alarm_sample_count"] == 180
    assert packet["controller"]["active_alarm_codes"] == [
        "SENSOR_NODE_UNAVAILABLE",
        "AERO_BUS_UNAVAILABLE",
    ]

    messages = build_environment_prompt_from_compact(packet)
    user = messages[1]["content"]
    assert "active_alarm_sample_count" not in user
    assert "active_alarm_codes" not in user
    assert "SENSOR_NODE_UNAVAILABLE" not in user
    assert "AERO_BUS_UNAVAILABLE" not in user
