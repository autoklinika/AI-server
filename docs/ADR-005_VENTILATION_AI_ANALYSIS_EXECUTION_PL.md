# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Stage 2 – profil bazowy zamrożony; produkcyjny oneshot PASS  
**Data:** 10.08.2026

## Nadrzędna zasada

> CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.

Awaria AI Servera, Ollamy, Qwena lub kanału odbioru rekomendacji nie może wpływać na logikę sterowania ani bezpieczeństwo CM5.

## Aktywny tor

```text
CM5 telemetry
   ↓
AI Bridge ingest
   ↓
PostgreSQL RAW
   ↓
pełna matematyczna agregacja Python
   ↓
pełny input_summary (audit/history)
   ↓
compact analysis packet
   ↓
Ollama / qwen3.6:35b / think=true
   ↓
minimalny raport JSON schema v2
   ↓
Pydantic – walidacja struktury
   ↓
ventilation_analysis_runs
```

Qwen nie jest wywoływany w ścieżce ingest/ACK.

## Okna i jakość danych

Analiza korzysta z zamkniętych, wyrównanych okien 15-minutowych. Przy capture co około 5 s pełne okno ma około 180 próbek.

Domyślny data-quality gate:

```text
120 próbek
```

Przy mniejszej liczbie próbek Qwen nie jest wywoływany i zapisywany jest `insufficient_data`.

## Python – tylko matematyka i przygotowanie danych

Pełny `input_summary` zachowuje m.in. count/missing, mean/min/max/stddev, first/last/delta, slope_per_minute, stan sterownika, setpointy, alarmy, SENSOR BUS, oba SEN55 i liczniki diagnostyczne.

Python nie definiuje progów anomalii i nie klasyfikuje jakości powietrza.

Do Qwena trafia mniejszy `compact analysis packet`, który usuwa redundancję, ale nie interpretuje danych. Packet zachowuje PM, VOC, NOx, temperaturę, wilgotność, stan systemu, SENSOR BUS i diagnostykę oraz jawnie rozróżnia pomiary niedostępne (`co2`, `fan_rpm`, `airflow`).

## Aktywny profil – `ventilation-v10-baseline-safe`

Aktywny kontrakt:

```text
schema_version = 2
status
analysis_pl
operator_recommendation_pl
data_quality_pl
```

Dozwolone statusy:

```text
no_anomaly_detected
attention
anomaly
insufficient_data
```

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w danym 15-minutowym oknie na podstawie dostępnych danych. Nie oznacza, że wartości są normalne, typowe, bezpieczne lub mieszczą się w progach.

Wszystkie trzy pola tekstowe są obowiązkowe i mają być napisane po polsku.

## Ochrona przed nieistniejącym baseline'em i progami

Profil jawnie zabrania modelowi używania określeń `w normie`, `typowe`, `bezpieczne`, `nie przekracza progów`, jeżeli odpowiedni baseline, norma lub próg nie został przekazany w danych.

Brak historycznego baseline'u oznacza, że Qwen może opisywać wartości, kierunek zmian i zależności w oknie, ale nie może klasyfikować ich względem normalnej pracy warsztatu.

Python nie wykonuje semantycznej klasyfikacji odpowiedzi.

## Walidacja funkcjonalna i idempotencja

Dla historycznego okna 179 próbek uzyskano:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
prompt_version=ventilation-v10-baseline-safe
schema_version=2
status=no_anomaly_detected
reused_existing=false
```

Ponowne uruchomienie tego samego okna zwróciło ten sam `analysis_id`, `reused_existing=true` i nie wykonało nowego wywołania Ollamy.

**Idempotencja: PASS.**

## Produkcyjny deployment i oneshot

Kod Stage 2 działa z `/opt/ai-bridge` jako `ai-bridge 0.2.0`.

`ai-bridge.service` po aktualizacji działa jako `active (running)`, a `/health` zwraca:

```text
status=ok
version=0.2.0
database=ok
control_commands_supported=false
```

Produkcję zwalidowano przez `ai-bridge-analysis.service` (`Type=oneshot`). Wynik:

```text
Result=success
ExecMainStatus=0
ActiveState=inactive
SubState=dead
```

Rzeczywista analiza produkcyjna:

```text
analysis_id=5cf9d21e-e2d2-4b0c-920e-c4a67aef135a
window=2026-08-10T15:15:00Z..15:30:00Z
sample_count=180
prompt_version=ventilation-v10-baseline-safe
status=no_anomaly_detected
```

Czas ścienny wyniósł około 90 s. Wynik został zapisany do PostgreSQL.

**Produkcja + systemd oneshot: PASS.**

## Znane ograniczenia semantyczne

Produkcyjny przebieg potwierdził, że techniczny pipeline jest stabilny, ale końcowy tekst Qwena może nadal zawierać treści nieuzasadnione materiałem wejściowym. W szczególności model potrafi:

- wymyślać progi liczbowe,
- sugerować normy WHO/UE mimo braku takiego kontekstu,
- proponować działania operatorskie niezwiązane bezpośrednio z danym oknem,
- dodawać meta-oferty dotyczące integracji, wykresów lub dalszej analizy,
- nierówno opisywać oba SEN55.

Dlatego `ventilation-v10-baseline-safe` jest **eksperymentalno-doradczym fundamentem**, a nie zweryfikowaną diagnozą ani instrukcją operatorską.

`operator_recommendation_pl` nie może być wejściem do automatycznej logiki CM5.

## Decyzja o zamrożeniu interpretacji Stage 2

Nie planujemy v11/v12 w bieżącym Stage 2.

Do rozbudowy interpretacji wrócimy dopiero po zebraniu rzeczywistej historii warsztatu, kiedy będzie można zaprojektować historyczny baseline, porównania między oknami i dniami, progi/reguły oparte na rzeczywistych danych oraz bardziej rozbudowane raporty.

## Następny etap – odczyt wyniku przez CM5

Po domknięciu technicznym Stage 2 planowany jest wyłącznie read-only kanał AI Server -> CM5:

```text
AI Server / ventilation_analysis_runs
        ↓
read-only HTTP endpoint latest analysis
        ↓
CM5 advisory client
        ↓
lokalny cache / GUI / status dla operatora
```

Zasady:

- CM5 pobiera wynik asynchronicznie i nie czeka na niego w logice sterowania,
- brak odpowiedzi AI nie powoduje zmiany pracy wentylacji,
- wynik AI może być wyświetlany lub logowany,
- wynik AI musi być oznaczony jako doradczy/eksperymentalny,
- wynik AI nie może automatycznie zmieniać trybu, setpointów ani żadnego elementu sterowania,
- nie będzie endpointu AI -> CM5 wykonującego komendy sterujące.

## Timer

Timer analizy jest przygotowany, ale pozostaje celowo niewłączony. Produkcyjny oneshot jest PASS; przed automatyzacją należy zdecydować, jak eksperymentalny raport będzie eksponowany operatorowi i CM5.

## Wniosek

Stage 2 osiągnął funkcjonalny PASS, idempotencję PASS oraz produkcyjny systemd oneshot PASS. Profil `ventilation-v10-baseline-safe` pozostaje zamrożonym fundamentem. Kolejny etap dotyczy dostarczenia raportu do CM5 w kanale read-only.