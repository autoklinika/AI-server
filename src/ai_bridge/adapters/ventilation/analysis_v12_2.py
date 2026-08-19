from __future__ import annotations

"""Ventilation analysis v12.2: adverse-trend environmental gate.

v12.1 successfully grounded technical status, data quality and rendering, but the
real clean-reference window showed one remaining semantic issue: Qwen treated a
coherent decrease of PM/VOC as attention merely because the trend was clear.

v12.2 changes only the environmental interpretation contract. Python policy,
final status hierarchy, recommendations and deterministic rendering stay exactly
as in v12.1.
"""

import json

from ai_bridge.adapters.ventilation import analysis_v12_1 as base


PROMPT_VERSION = "ventilation-v12.2-adverse-trend-gate"
ANALYSIS_THINK = False
EnvironmentalDecisionV122 = base.EnvironmentalDecisionV121

SYSTEM_PROMPT = """Jesteś lokalnym analitykiem danych środowiskowych wentylacji warsztatu.

Dostajesz fakty środowiskowe i kontekst sterowania z jednego zamkniętego
15-minutowego okna. Alarmy techniczne, SENSOR BUS, brakujące próbki, końcowy status
i rekomendacje rozstrzyga deterministycznie Python poza modelem.

Zwróć wyłącznie JSON zgodny ze schematem z dwoma elementami decyzji:
- `environmental_attention`,
- `selected_fact_ids`.

Reguły decyzji:
- `environmental_attention=true` tylko wtedy, gdy pomiary środowiskowe pokazują
  potencjalnie niekorzystną albo mieszaną zmianę zasługującą na obserwację,
- wyraźny wzrost PM1.0/PM2.5/PM4.0/PM10.0, VOC Index lub NOx Index może uzasadniać
  `true`,
- jeżeli PM, VOC Index i NOx Index są stabilne albo ogólnie maleją i żaden z tych
  kanałów wyraźnie nie rośnie, ustaw `environmental_attention=false` nawet wtedy,
  gdy sam spadek jest duży,
- łagodna zmiana temperatury lub wilgotności sama w sobie, bez historycznego
  baseline'u i bez jawnego progu w danych, nie uzasadnia `true`,
- wzorzec mieszany, np. spadek PM przy równoczesnym wyraźnym wzroście VOC Index
  lub NOx Index, może uzasadniać `true`,
- jeżeli `environmental_attention=false`, zwróć `selected_fact_ids=[]`,
- jeżeli `true`, wybierz maksymalnie 6 identyfikatorów dokładnie obecnych w
  `facts`, które najlepiej uzasadniają uwagę,
- setpoint 0-10 V jest wyłącznie zadanym sygnałem sterującym; nie jest przepływem
  ani zmierzoną wydajnością wentylacji,
- nie wnioskuj o przyczynowości, źródle emisji ani wpływie setpointów na pomiary,
- VOC Index jest indeksem czujnika, nie bezpośrednim pomiarem emisji,
- `slope_per_minute` jest współczynnikiem regresji liniowej całego okna,
- nie przenoś wartości między kanałami, węzłami ani oknami.
"""

build_environment_fact_catalog = base.build_environment_fact_catalog
build_environment_packet_from_compact = base.build_environment_packet_from_compact
validate_environmental_decision = base.validate_environmental_decision
resolve_final_decision = base.resolve_final_decision
render_result = base.render_result


def build_environment_prompt_from_compact(packet: dict) -> list[dict[str, str]]:
    model_packet = build_environment_packet_from_compact(packet)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Wersja profilu: {PROMPT_VERSION}\n\n"
                + json.dumps(
                    model_packet,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        },
    ]
