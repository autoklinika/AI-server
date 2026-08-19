from __future__ import annotations

import json
from typing import Any

from ai_bridge.adapters.ventilation.analysis_profile_v11_6 import (
    ANALYSIS_THINK,
    SYSTEM_PROMPT as V11_6_SYSTEM_PROMPT,
    build_compact_analysis_packet,
)


PROMPT_VERSION = "ventilation-v11.7-semantic-grounding"

SYSTEM_PROMPT = V11_6_SYSTEM_PROMPT.replace(
    "profil v11.6 świadomie wyłącza je",
    "profil v11.7 świadomie wyłącza je",
) + """

Dodatkowe reguły v11.7 wynikające z drugiej walidacji na rzeczywistych oknach:
- zachowuj tożsamość kanałów setpointów. `supply_voltage` i `extract_voltage` są
  oddzielnymi polami i nie wolno zamieniać ich wartości miejscami. Przed opisaniem
  zmiany każdego setpointu sprawdź osobno jego `first`, `last` i `delta`,
- zmiana `supply_voltage` lub `extract_voltage` jest wyłącznie zmianą zadanego
  sygnału sterującego 0-10 V. Nie nazywaj jej „spadkiem wentylacji”, „wzrostem
  wentylacji”, zmianą przepływu, wydajności ani rzeczywistej pracy wentylatora,
  jeżeli takie wielkości nie są obecne w bieżącym pakiecie,
- po stwierdzeniu zbieżności czasowej nie twórz alternatywnych historii
  przyczynowych. Bez dodatkowych danych nie pisz, że jedno zjawisko mogło być
  skutkiem drugiego, że oba mogły wynikać z innej czynności, że system „zareagował”
  ani że zachodzi „proces oczyszczania”. Poprawne zakończenie brzmi: zbieżność
  czasowa nie potwierdza przyczynowości,
- zmiana `voc_index` opisuje zmianę indeksu VOC raportowanego przez czujnik. Nie
  oznacza bezpośrednio wzrostu ani spadku emisji lotnych związków organicznych i
  nie wolno takiej emisji wnioskować z samego VOC Index,
- `slope_per_minute` jest współczynnikiem nachylenia liniowej regresji wszystkich
  dostępnych punktów danego kanału w obrębie okna. Nie jest „końcowym”,
  „ostatecznym” ani chwilowym nachyleniem i nie wolno pisać, że nachylenie „spadło
  do” tej wartości. Jeżeli znak `delta` i znak `slope_per_minute` są różne,
  oznacza to, że przebieg nie jest dobrze opisany prostą zmianą monotoniczną;
  możesz podać osobno zmianę endpointów `first -> last` oraz znak regresyjnego
  trendu, ale nie wymyślaj kształtu przebiegu pomiędzy nimi,
- `active_alarm_sample_count` oznacza liczbę próbek okna, w których występował co
  najmniej jeden aktywny alarm. Gdy `active_alarm_codes` zawiera kilka kodów, nie
  przypisuj tej liczby żadnemu pojedynczemu kodowi, bo pakiet nie zawiera częstości
  występowania każdego kodu osobno.
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
