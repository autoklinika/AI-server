from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)


def test_v12_2_freezes_adverse_trend_gate() -> None:
    assert PROMPT_VERSION == "ventilation-v12.2-adverse-trend-gate"
    assert ANALYSIS_THINK is False
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "potencjalnie niekorzystną albo mieszaną zmianę" in normalized
    assert "PM, VOC Index i NOx Index są stabilne albo ogólnie maleją" in normalized
    assert "environmental_attention=false" in normalized
    assert "selected_fact_ids=[]" in normalized
    assert "spadek PM przy równoczesnym wyraźnym wzroście VOC Index" in normalized
    assert "łagodna zmiana temperatury lub wilgotności" in normalized
