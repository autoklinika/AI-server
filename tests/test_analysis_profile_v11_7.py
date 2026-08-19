from ai_bridge.adapters.ventilation.analysis_profile_v11_7 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)


def test_v11_7_profile_freezes_second_real_window_grounding_rules() -> None:
    normalized_prompt = " ".join(SYSTEM_PROMPT.split())

    assert PROMPT_VERSION == "ventilation-v11.7-semantic-grounding"
    assert ANALYSIS_THINK is False
    assert "zachowuj tożsamość kanałów setpointów" in SYSTEM_PROMPT
    assert "nie wolno zamieniać ich wartości miejscami" in SYSTEM_PROMPT
    assert "Nie nazywaj jej „spadkiem wentylacji”" in SYSTEM_PROMPT
    assert "nie twórz alternatywnych historii" in SYSTEM_PROMPT
    assert "system „zareagował”" in SYSTEM_PROMPT
    assert "proces oczyszczania" in SYSTEM_PROMPT
    assert "nie wolno takiej emisji wnioskować z samego VOC Index" in SYSTEM_PROMPT
    assert "współczynnikiem nachylenia liniowej regresji" in SYSTEM_PROMPT
    assert "Nie jest „końcowym”" in SYSTEM_PROMPT
    assert "active_alarm_sample_count" in SYSTEM_PROMPT
    assert "nie przypisuj tej liczby żadnemu pojedynczemu kodowi" in normalized_prompt
    assert "profil v11.7 świadomie wyłącza je" in SYSTEM_PROMPT
