from ai_bridge.adapters.ventilation.analysis_profile_v11_6 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)


def test_v11_6_profile_freezes_real_window_grounding_rules() -> None:
    assert PROMPT_VERSION == "ventilation-v11.6-grounding-hardening"
    assert ANALYSIS_THINK is False
    assert "każda wartość liczbowa opisana w odpowiedzi musi pochodzić z bieżącego pakietu" in SYSTEM_PROMPT
    assert "nie przenoś wartości między oknami ani między węzłami" in SYSTEM_PROMPT
    assert "nie używaj słów „korelacja”" in SYSTEM_PROMPT
    assert "capture_span_seconds" in SYSTEM_PROMPT
    assert "nie może być używane do zmiany nazwy 15-minutowego okna" in SYSTEM_PROMPT
    assert "TACHO/RPM są wyłączone z bieżącego pakietu analitycznego" in SYSTEM_PROMPT
    assert "AERO_BUS_UNAVAILABLE" in SYSTEM_PROMPT
    assert "nie może być nazywany awarią SENSOR BUS" in SYSTEM_PROMPT
    assert "nie jest podstawą do zalecenia „zweryfikuj, czy setpoint był zamierzony”" in SYSTEM_PROMPT
    assert "sama różnica trendów między węzłami" in SYSTEM_PROMPT
    assert "profil v11.6 świadomie wyłącza je" in SYSTEM_PROMPT
