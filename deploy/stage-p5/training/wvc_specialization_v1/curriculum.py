"""Project-owned WVC reasoning curriculum. Frozen WVC baseline is never imported here."""
from __future__ import annotations
import json

SYSTEM = (
    "Jesteś analitykiem technicznym WVC. Odpowiadaj po polsku i zwięźle. "
    "Najpierw oceń ważność danych, potem rozdziel obserwacje od hipotez. "
    "Nie utożsamiaj komendy z wykonaniem, korelacji z przyczyną ani alarmu z konkretnym elementem. "
    "Wskaż jedno najbardziej rozstrzygające następne sprawdzenie, brakujące sygnały i granicę wniosku."
)

CATEGORIES = [
    "validity_gate",
    "command_vs_execution",
    "actuator_feedback",
    "common_vs_local_event",
    "sensor_disagreement",
    "sensor_bus_quality",
    "fault_temporal_sequence",
    "adjacent_window_order",
    "setpoint_pollutant_causality",
    "missing_signal_boundary",
    "alarm_scope_boundary",
    "baseline_absence",
    "index_semantics",
    "evidence_hierarchy",
    "domain_boundary",
    "recovery_not_root_cause",
]

PROFILES = {
    "validity_gate": dict(
        focus="ważność i świeżość danych przed interpretacją wartości",
        hypotheses=["zjawisko jest rzeczywiste", "pozorny trend wynika z jakości danych"],
        check="porównaj measurement_valid, measurement_stale, online i liczniki błędów z chwilą zmiany",
        a="dane są świeże i ważne w chwili zdarzenia — hipoteza realnego zjawiska zyskuje wiarygodność",
        b="ważność lub świeżość pogarsza się razem ze zdarzeniem — najpierw wyjaśnij tor pomiarowy",
        missing="niezależne odniesienie pomiarowe i pełny log jakości danych",
        no="sam odczyt liczbowy nie dowodzi poprawnego pomiaru",
    ),
    "command_vs_execution": dict(
        focus="rozdzielenie sygnału zadanego od faktycznego wykonania",
        hypotheses=["aktor wykonał komendę", "komenda była obecna, ale wykonanie nie nastąpiło lub jest nieznane"],
        check="zestaw setpoint z niezależnym feedbackiem wykonania: RPM, tacho, prąd albo airflow",
        a="feedback zmienia się zgodnie z komendą — wykonanie jest wspierane przez dane",
        b="feedback nie reaguje albo jest niedostępny — z setpointu nie wolno wnioskować o wykonaniu",
        missing="co najmniej jeden niezależny sygnał wykonania",
        no="wysoki setpoint nie oznacza wysokiego przepływu ani poprawnej pracy wentylatora",
    ),
    "actuator_feedback": dict(
        focus="różnica między kanałami wykonawczymi przy podobnej komendzie",
        hypotheses=["różne obciążenie lub mechanika kanału", "błąd feedbacku albo toru wykonawczego"],
        check="porównaj równocześnie komendę, feedback obu kanałów i jeden sygnał energetyczny przy tym samym stanie",
        a="różnica występuje także w niezależnym feedbacku — problem jest po stronie wykonania lub warunków kanału",
        b="niezależny feedback jest zgodny, a różni się tylko jeden odczyt — sprawdź tor pomiarowy",
        missing="prąd, RPM/tacho lub przepływ dla obu kanałów w tej samej chwili",
        no="równa komenda nie dowodzi równego efektu",
    ),
    "common_vs_local_event": dict(
        focus="rozróżnienie wspólnego zdarzenia od lokalnego problemu czujnika",
        hypotheses=["obie lokalizacje widzą wspólne zjawisko", "zmiana jest lokalna albo pomiarowa"],
        check="porównaj synchronizację zmian na obu węzłach i niezależny kontekst procesu lub pomiar referencyjny",
        a="oba ważne węzły zmieniają się zgodnie w czasie — wspólne zdarzenie jest bardziej prawdopodobne",
        b="zmienia się tylko jeden węzeł — sprawdź lokalizację, lokalne źródło i sam czujnik",
        missing="lokalizacja węzłów, kontekst procesu i niezależny punkt odniesienia",
        no="zgodność dwóch czujników nie identyfikuje źródła zanieczyszczenia",
    ),
    "sensor_disagreement": dict(
        focus="bezpieczna interpretacja rozbieżności dwóch SEN55",
        hypotheses=["lokalne zjawisko fizyczne", "różne warunki montażu", "problem jednego czujnika"],
        check="zamień pozycje lub użyj niezależnego pomiaru referencyjnego bez zmiany warunków procesu",
        a="anomalia podąża za lokalizacją — wspiera lokalne zjawisko lub wpływ montażu",
        b="anomalia podąża za czujnikiem — wspiera problem konkretnego toru pomiarowego",
        missing="fizyczne położenie czujników i pomiar referencyjny",
        no="pojedyncza rozbieżność nie jest dowodem uszkodzenia czujnika",
    ),
    "sensor_bus_quality": dict(
        focus="odróżnienie awarii komunikacji od zmiany środowiska",
        hypotheses=["sensor bus traci komunikację lub świeżość", "środowisko zmienia się przy poprawnej telemetrii"],
        check="na wspólnej osi czasu porównaj ready/online/stale/error counters z samymi odczytami",
        a="błędy i stale rosną razem z brakiem danych — najpierw diagnozuj magistralę lub zasilanie węzła",
        b="telemetria pozostaje świeża i bez błędów — komunikacja nie tłumaczy zmiany wartości",
        missing="log komunikacji i zasilanie węzłów podczas zdarzenia",
        no="brak odczytu nie wskazuje automatycznie uszkodzonego sensora",
    ),
    "fault_temporal_sequence": dict(
        focus="kolejność zdarzeń sterownika i jej znaczenie diagnostyczne",
        hypotheses=["utrata gotowości poprzedza FAULT", "FAULT jest skutkiem wcześniejszego problemu wykonawczego lub komunikacyjnego"],
        check="ułóż command, hardware_ready, output_state_known i alarmy według dokładnych timestampów",
        a="utrata gotowości występuje przed FAULT — badaj jej bezpośrednią przyczynę",
        b="FAULT pojawia się przed utratą feedbacku — feedback może być skutkiem trybu ochronnego",
        missing="timestampy o wystarczającej rozdzielczości i stan wyjść w chwili przejścia",
        no="sam końcowy stan FAULT nie ustala kolejności ani przyczyny",
    ),
    "adjacent_window_order": dict(
        focus="wnioskowanie z kolejnych okien bez gubienia kolejności czasowej",
        hypotheses=["zmiana sterowania poprzedza zmianę pomiaru", "pomiar zmienia się wcześniej lub niezależnie"],
        check="zejdź z agregatów okien do timestampów zmian setpointu i pierwszej reakcji sygnałów",
        a="zmiana wykonania poprzedza powtarzalną reakcję — związek czasowy jest wspierany, lecz nadal nie dowodzi przyczyny",
        b="reakcja poprzedza komendę lub nie jest powtarzalna — hipoteza sterowania jako przyczyny słabnie",
        missing="surowa oś czasu oraz feedback wykonania",
        no="średnie z dwóch kwadransów nie dowodzą kierunku przyczynowego",
    ),
    "setpoint_pollutant_causality": dict(
        focus="ostrożne wnioskowanie o związku nastaw z PM/VOC/NOx",
        hypotheses=["zmiana wydajności wentylacji wpłynęła na transport zanieczyszczeń", "zmieniło się samo źródło emisji lub proces"],
        check="powtórz kontrolowaną zmianę setpointu z potwierdzeniem wykonania i oznaczeniem stanu procesu",
        a="potwierdzona zmiana wykonania poprzedza powtarzalną reakcję przy stałym procesie — wspiera wpływ wentylacji",
        b="proces lub emisja zmienia się niezależnie — nie przypisuj efektu samym nastawom",
        missing="feedback wykonania, stan procesu i najlepiej niezależny pomiar przepływu",
        no="korelacja setpointu z pyłem lub indeksem nie jest dowodem przyczyny",
    ),
    "missing_signal_boundary": dict(
        focus="granica wniosku przy braku RPM, tacho, airflow lub prądu",
        hypotheses=["układ wykonawczy działa zgodnie z komendą", "stan wykonania jest inny niż sugeruje komenda"],
        check="dodaj jeden bezpośredni sygnał wykonania najbliższy pytaniu operatora",
        a="feedback potwierdza wykonanie — można oceniać wpływ wentylacji na podstawie realnej reakcji",
        b="feedback przeczy komendzie albo jest niestabilny — najpierw diagnozuj wykonanie",
        missing="bezpośredni pomiar wykonania",
        no="brak feedbacku trzeba nazwać brakiem danych, a nie zastępować założeniem",
    ),
    "alarm_scope_boundary": dict(
        focus="oddzielenie znaczenia alarmu od nieudokumentowanej diagnozy elementu",
        hypotheses=["alarm opisuje problem warstwy komunikacji lub gotowości", "usterka leży dalej w aktorze lub mechanice"],
        check="sprawdź definicję alarmu i równoczesny stan wyjścia oraz feedback aktora",
        a="alarm pokrywa się z utratą komunikacji, lecz aktor ma osobny feedback — lokalizuj warstwę zgodnie z kontraktem alarmu",
        b="komunikacja jest poprawna, a feedback aktora zanika — szukaj poza samą warstwą alarmu",
        missing="semantyka alarmu i niezależny feedback wykonania",
        no="kod alarmu nie dowodzi zacięcia przepustnicy, falownika ani konkretnego elementu",
    ),
    "baseline_absence": dict(
        focus="interpretacja danych bez historycznego baseline i progów referencyjnych",
        hypotheses=["obserwowany trend jest zmianą względem bieżącego okna", "wartość jest typowa dla instalacji"],
        check="zbuduj powtarzalny baseline dla porównywalnego trybu pracy i warunków procesu",
        a="trend powtarza się względem stabilnego baseline — można mówić o odchyleniu od własnego punktu odniesienia",
        b="baseline jest zmienny lub nieporównywalny — pozostaw opis bez etykiety normalne/nienormalne",
        missing="historyczny punkt odniesienia i zaakceptowane progi eksploatacyjne",
        no="bez baseline nie nazywaj wartości bezpieczną, prawidłową, wysoką ani niską",
    ),
    "index_semantics": dict(
        focus="poprawna semantyka VOC Index i NOx Index",
        hypotheses=["indeks zmienił się względem własnej historii", "zmiana wynika z warunków sensora lub środowiska"],
        check="porównaj indeks w czasie z innymi ważnymi sygnałami i własnym baseline sensora",
        a="indeks zmienia się powtarzalnie razem z niezależnymi sygnałami — zdarzenie środowiskowe zyskuje wiarygodność",
        b="zmienia się tylko indeks lub jakość danych — nie przeliczaj go na nieznane stężenie",
        missing="kalibracja/baseline i niezależny sygnał środowiskowy",
        no="VOC Index ani NOx Index nie są w tym kontrakcie bezpośrednim stężeniem gazu",
    ),
    "evidence_hierarchy": dict(
        focus="priorytet dowodów bezpośrednich nad analogią i domysłem",
        hypotheses=["bezpośrednia telemetria wystarcza do zawężenia problemu", "potrzebny jest dodatkowy pomiar rozdzielający"],
        check="wybierz brakujący sygnał, który bezpośrednio odróżnia konkurujące hipotezy",
        a="nowy sygnał rozdziela hipotezy — aktualizuj diagnozę w oparciu o pomiar",
        b="sygnał pozostaje niejednoznaczny — nie zwiększaj pewności tylko przez analogię",
        missing="co najmniej jeden pomiar rozstrzygający w badanej granicy",
        no="analogia z inną instalacją ma niższy priorytet niż telemetria tej instalacji",
    ),
    "domain_boundary": dict(
        focus="utrzymanie domeny WVC bez automatycznego przenoszenia diagnostyki automotive",
        hypotheses=["problem wynika z warstwy WVC opisanej w danych", "potrzebna jest diagnostyka elektryczna konkretnego aktora"],
        check="najpierw potwierdź z kontraktu WVC, że dany interfejs lub element rzeczywiście istnieje i jest związany z objawem",
        a="kontrakt i telemetria wskazują konkretną warstwę wykonawczą — dopiero wtedy schodź do elektroniki",
        b="brak takiego dowodu — pozostań przy sygnałach WVC i nie importuj topologii z ECU",
        missing="udokumentowana topologia wykonawcza danej instalacji",
        no="CAN, ECU, MOSFET czy automotive nie są domyślnym wyjaśnieniem problemu wentylacji",
    ),
    "recovery_not_root_cause": dict(
        focus="odróżnienie odzyskania działania od ustalenia przyczyny",
        hypotheses=["restart usuwa stan przejściowy", "restart maskuje problem komunikacji, zasilania lub wykonania"],
        check="zachowaj log i sygnały bezpośrednio przed restartem oraz porównaj je z pierwszym poprawnym stanem po odzysku",
        a="ten sam sygnał degraduje się przed każdym restartem — zawęża to przyczynę",
        b="brak powtarzalnego prekursora — restart pozostaje tylko obserwacją o odzyskaniu działania",
        missing="pre-fault telemetry i dokładny czas restartu",
        no="to, że restart pomaga, nie identyfikuje root cause",
    ),
}

VARIANTS = [
    ("snapshot", "pojedyncze stabilne okno bez zewnętrznego punktu odniesienia"),
    ("transition", "zmiana trybu lub nastawy w środku obserwowanego okresu"),
    ("peer", "dwa równoległe węzły lub kanały dostępne do porównania"),
    ("degraded", "część telemetrii ma pogorszoną jakość lub świeżość"),
    ("fault", "w oknie występuje alarm lub przejście do FAULT"),
    ("recovery", "po krótkim problemie system wraca do działania"),
]

def context_for(category: str, variant: int) -> dict:
    mode, _ = VARIANTS[variant - 1]
    if category in {"command_vs_execution","actuator_feedback","missing_signal_boundary"}:
        return {
            "mode": "MANUAL",
            "setpoints_v": {"supply": 7.1 if variant % 2 else 4.3, "extract": 6.8 if variant % 3 else 4.1},
            "hardware_ready": True,
            "output_state_known": variant not in {2,5},
            "tacho": None if variant in {1,2,6} else {"supply_rpm": 1180, "extract_rpm": 840, "valid": True},
            "airflow": None,
            "current_feedback": None if variant != 3 else {"supply_a": 0.74, "extract_a": 0.51},
            "variant": mode,
        }
    if category in {"common_vs_local_event","sensor_disagreement","validity_gate","sensor_bus_quality","index_semantics"}:
        node2_change = category == "common_vs_local_event" or variant in {4,6}
        degraded = category == "sensor_bus_quality" or variant == 4
        return {
            "nodes": {
                "1": {"online": not degraded, "valid": not degraded, "stale": degraded,
                      "pm2_5": 47.0, "voc_index": 221.0, "nox_index": 18.0,
                      "communication_errors": 7 if degraded else 0},
                "2": {"online": True, "valid": True, "stale": False,
                      "pm2_5": 45.0 if node2_change else 5.4,
                      "voc_index": 214.0 if node2_change else 91.0,
                      "nox_index": 17.0 if node2_change else 3.0,
                      "communication_errors": 0},
            },
            "independent_reference": None,
            "physical_placement_known": False,
            "variant": mode,
        }
    if category in {"fault_temporal_sequence","recovery_not_root_cause","alarm_scope_boundary"}:
        return {
            "events": [
                {"t": "10:00:00", "mode": "MANUAL", "hardware_ready": True, "output_state_known": True, "alarm": None},
                {"t": "10:00:12", "mode": "MANUAL", "hardware_ready": False if variant in {4,5,6} else True,
                 "output_state_known": False if variant in {4,5,6} else True,
                 "alarm": "AERO_BUS_UNAVAILABLE" if category == "alarm_scope_boundary" else ("DAC_COMMUNICATION_LOST" if variant in {4,5,6} else None)},
                {"t": "10:00:24", "mode": "FAULT" if variant in {5,6} else "MANUAL",
                 "hardware_ready": variant != 5, "output_state_known": variant != 5,
                 "alarm": "HARDWARE_NOT_READY" if variant == 5 else None},
                {"t": "10:00:38", "mode": "STOP" if variant in {5,6} else "MANUAL",
                 "hardware_ready": True, "output_state_known": True, "alarm": None},
            ],
            "rpm": None,
            "airflow": None,
            "variant": mode,
        }
    if category in {"adjacent_window_order","setpoint_pollutant_causality"}:
        return {
            "windows": [
                {"period": "A", "setpoint_v": 7.4, "pm2_5": 11.0, "voc_index": 74.0, "feedback_execution": None},
                {"period": "B", "setpoint_v": 4.6, "pm2_5": 62.0 if variant % 2 else 8.0,
                 "voc_index": 51.0 if variant % 2 else 126.0, "feedback_execution": None},
            ],
            "process_state": "unknown",
            "airflow": None,
            "timestamps_inside_window": False,
            "variant": mode,
        }
    return {
        "controller": {"mode": "MANUAL" if variant not in {5} else "FAULT",
                       "hardware_ready": variant != 5, "output_state_known": variant not in {2,5}},
        "sensor_bus": {"ready": variant != 4, "worker_alive": variant != 4,
                       "communication_errors": 5 if variant == 4 else 0},
        "measurement_capabilities": {"present": ["pm2_5","pm10","voc_index","nox_index","temperature"],
                                     "missing": ["airflow","co2","fan_rpm"]},
        "historical_baseline_available": False,
        "active_alarm": "AERO_BUS_UNAVAILABLE" if variant == 5 else None,
        "variant": mode,
    }

def render(profile: dict, variant: int) -> str:
    mode, variant_note = VARIANTS[variant - 1]
    hs = profile["hypotheses"]
    return "\n".join([
        "OBSERWACJA: Najpierw obowiązuje " + profile["focus"] + ". " + variant_note + ".",
        "HIPOTEZY: " + " / ".join(hs),
        "NIE WYNIKA: " + profile["no"] + ".",
        "NAJLEPSZE NASTĘPNE SPRAWDZENIE: " + profile["check"] + ".",
        "JEŚLI A: " + profile["a"] + ".",
        "JEŚLI B: " + profile["b"] + ".",
        "BRAKI/PEWNOŚĆ: " + profile["missing"] + "; pewność zwiększaj dopiero po rozstrzygającym pomiarze.",
    ])

def new_records() -> list[dict]:
    rows = []
    for category in CATEGORIES:
        profile = PROFILES[category]
        for variant in range(1, 7):
            ctx = context_for(category, variant)
            _, variant_note = VARIANTS[variant - 1]
            user = (
                f"Zadanie WVC: {profile['focus']}. Warunek: {variant_note}. "
                "Oceń dane bez dopowiadania brakujących sygnałów. Telemetria JSON: "
                + json.dumps(ctx, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            spec = {
                "focus": profile["focus"],
                "hypotheses": profile["hypotheses"],
                "check": profile["check"],
                "branch_a": profile["a"],
                "branch_b": profile["b"],
                "missing": profile["missing"],
                "non_conclusion": profile["no"],
                "variant": variant,
            }
            rows.append({
                "record_id": f"P513-WVC-{category}-{variant}",
                "system": SYSTEM,
                "user": user,
                "assistant": render(profile, variant),
                "metadata": {
                    "category": category,
                    "variant": variant,
                    "split": "train",
                    "training_eligible": True,
                    "language": "pl",
                    "source_kind": "project_owned_contract_grounded_synthetic",
                    "p513_origin": "new",
                },
                "spec": spec,
            })
    assert len(rows) == 96
    return rows
