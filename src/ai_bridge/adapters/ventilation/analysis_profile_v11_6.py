from __future__ import annotations

import json
from typing import Any

from ai_bridge.adapters.ventilation.analysis_profile import (
    ANALYSIS_THINK,
    SYSTEM_PROMPT as V11_5_SYSTEM_PROMPT,
    build_compact_analysis_packet,
)


PROMPT_VERSION = "ventilation-v11.6-grounding-hardening"

SYSTEM_PROMPT = V11_5_SYSTEM_PROMPT.replace(
    "profil v11.5 świadomie wyłącza je",
    "profil v11.6 świadomie wyłącza je",
) + """

Dodatkowe reguły v11.6 wynikające z walidacji na rzeczywistych oknach:
- każda wartość liczbowa opisana w odpowiedzi musi pochodzić z bieżącego pakietu
  danych. Nie używaj liczb z wcześniejszych analiz, wcześniejszych okien ani z
  pamięci modelu. Przed zwróceniem odpowiedzi sprawdź każdą parę „z X do Y” z
  aktualnymi polami `first` i `last` tego samego kanału i tego samego węzła,
- nie przenoś wartości między oknami ani między węzłami. Jeżeli np. bieżący
  `voc_index` węzła 1 ma `first=32` i `last=79`, nie wolno opisać go jako
  `80 -> 32`, nawet jeśli taka para występowała w innym oknie,
- nie używaj słów „korelacja”, „skorelowane”, „zależność”, „wpływ”, „reakcja na”,
  „spowodował”, „skutkował” ani równoważnych twierdzeń o relacji między setpointami
  a pomiarami, jeżeli pakiet nie zawiera jawnie policzonej miary korelacji lub
  innego dowodu zależności. Równoczesne zmiany opisuj wyłącznie jako „równocześnie”,
  „w tym samym oknie” albo „zbieżność czasowa nie potwierdza przyczynowości”,
- `window.start` i `window.end` definiują nominalny czas okna. Pole
  `capture_span_seconds` opisuje jedynie odstęp między pierwszą a ostatnią
  zarejestrowaną próbką i nie może być używane do zmiany nazwy 15-minutowego okna
  na 14-minutowe ani do innego zaokrąglania czasu analizy,
- jeżeli `measurement_capabilities.excluded_from_current_analysis_packet` zawiera
  `fan_rpm` lub `tacho`, nie pisz „brak danych o RPM/TACHO” ani nie twierdź, że
  system nie posiada tych danych. Poprawne sformułowanie, jeśli jest potrzebne,
  brzmi: „TACHO/RPM są wyłączone z bieżącego pakietu analitycznego”,
- kod alarmu jest dowodem istnienia alarmu i może uzasadniać status `anomaly`, ale
  sam tekst kodu nie jest opisem przyczyny. Nie rozwijaj nieudokumentowanych skrótów
  ani nie przypisuj alarmu do innego subsystemu. W szczególności
  `AERO_BUS_UNAVAILABLE` nie może być nazywany awarią SENSOR BUS ani magistrali
  czujników, jeśli bieżące pola SENSOR BUS tego nie potwierdzają,
- przy aktywnym alarmie możesz zalecić diagnostykę tego konkretnego alarmu zgodnie
  z dokumentacją/procedurą systemu, ale nie wymyślaj jego przyczyny ani konkretnej
  naprawy, jeżeli nie wynika ona z danych,
- `expected_operating_state_known=false` jest tylko ograniczeniem kontekstu. Samo
  to pole nie jest podstawą do zalecenia „zweryfikuj, czy setpoint był zamierzony”,
  „sprawdź zamiar operatora” ani podobnej czynności,
- sama różnica trendów między węzłami bez potwierdzonej awarii nie jest podstawą do
  zalecenia szukania przyczyny lub lokalnego źródła. Możesz opisać różnicę i
  zaznaczyć, że jej przyczyna nie jest znana,
- jeśli status `attention` wynika wyłącznie z trendu środowiskowego i dane nie
  wskazują konkretnej czynności diagnostycznej, `operator_recommendation_pl` ma
  napisać, że na podstawie tego okna nie ma dodatkowych zaleceń, ewentualnie
  ograniczyć się do obserwacji kolejnych okien.
"""


def build_ventilation_prompt(summary: dict[str, Any]) -> list[dict[str, str]]:
    packet = build_compact_analysis_packet(summary)
    user = (
        "Przeanalizuj poniższy pakiet danych. "
        f"Wersja profilu: {PROMPT_VERSION}\n\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
