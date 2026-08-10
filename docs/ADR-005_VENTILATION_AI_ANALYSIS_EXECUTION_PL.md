# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Stage 2 – funkcjonalny i produkcyjny oneshot PASS; timer wyłączony  
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

## Okna i data-quality gate

Analiza wykorzystuje zamknięte, wyrównane okna 15-minutowe. Przy capture co około 5 s pełne okno ma około 180 próbek.

Domyślny gate:

```text
120 próbek
```

Poniżej gate Qwen nie jest wywoływany i zapisywany jest `insufficient_data`.

## Python i compact packet

Python wykonuje wyłącznie deterministyczne przygotowanie matematyczne. Pełny `input_summary` pozostaje w PostgreSQL jako materiał audytowy.

Do Qwena trafia compact packet zawierający PM, VOC, NOx, temperaturę, wilgotność, stan sterownika, SENSOR BUS i diagnostykę. Brak pomiarów CO2, RPM/tacho i airflow jest jawnie zaznaczony.

Python nie definiuje progów anomalii i nie klasyfikuje jakości powietrza.

## Aktywny profil – `ventilation-v10-baseline-safe`

Kontrakt:

```text
schema_version = 2
status
analysis_pl
operator_recommendation_pl
data_quality_pl
```

Statusy:

```text
no_anomaly_detected
attention
anomaly
insufficient_data
```

`no_anomaly_detected` oznacza wyłącznie brak jednoznacznej anomalii w danym oknie. Nie oznacza normalności historycznej, bezpieczeństwa ani zgodności z normą.

Wszystkie trzy pola tekstowe są obowiązkowe i mają być po polsku.

## Ochrona baseline-safe

Prompt zabrania modelowi deklarowania, że wartości są `w normie`, `typowe`, `bezpieczne` lub `nie przekraczają progów`, jeżeli baseline/norma/próg nie został przekazany.

Jest to instrukcja promptu, nie semantyczny validator Python.

## Walidacja funkcjonalna i idempotencja

Historyczne okno 179 próbek zostało przeanalizowane i zapisane jako:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
prompt_version=ventilation-v10-baseline-safe
schema_version=2
status=no_anomaly_detected
```

Ponowne uruchomienie zwróciło ten sam `analysis_id`, `reused_existing=true` i nie uruchomiło nowego requestu do Ollamy.

**Idempotencja: PASS.**

## Deployment produkcyjny i systemd oneshot

Kod Stage 2 został wdrożony do `/opt/ai-bridge` jako `ai-bridge 0.2.0`.

`ai-bridge.service` działa jako `active (running)`, a health check potwierdził:

```text
status=ok
version=0.2.0
database=ok
control_commands_supported=false
```

`ai-bridge-analysis.service` (`Type=oneshot`) wykonał rzeczywistą analizę:

```text
analysis_id=5cf9d21e-e2d2-4b0c-920e-c4a67aef135a
window=2026-08-10T15:15:00Z..15:30:00Z
sample_count=180
prompt_version=ventilation-v10-baseline-safe
status=no_anomaly_detected
```

Systemd zakończył przebieg:

```text
Result=success
ExecMainStatus=0
ActiveState=inactive
SubState=dead
```

Czas ścienny wyniósł około 90 s.

**Produkcja + oneshot: PASS.**

## Znane ograniczenia semantyczne

Produkcja potwierdziła stabilność pipeline'u, ale nie pełną wiarygodność semantyczną raportu Qwena. Model potrafi nadal:

- wymyślić arbitralne progi liczbowe,
- przywołać WHO/UE bez przekazanego kontekstu,
- dodać meta-oferty dotyczące wykresów lub integracji,
- zasugerować działania operatorskie niewynikające bezpośrednio z okna,
- nierówno opisać oba SEN55.

W produkcyjnym przebiegu pojawiły się m.in. arbitralne progi `PM >25 µg/m³` i wilgotność `<40%`.

Dlatego wynik jest **advisory/experimental**, nie zweryfikowaną diagnozą ani instrukcją operatorską.

`operator_recommendation_pl` nie może być wejściem do automatycznej logiki CM5.

## Zamrożenie interpretacji

Nie tworzymy v11/v12 w Stage 2. Do rozbudowy wrócimy po zebraniu historycznego baseline'u warsztatu.

## Timer

Timer jest technicznie przygotowany, ale pozostaje **wyłączony**. Powód nie jest techniczny: oneshot działa poprawnie. Chodzi o to, aby nie generować cyklicznie raportów dla operatora przed wprowadzeniem jawnego oznaczenia advisory/experimental i read-only kanału do CM5.

## Następny etap – read-only AI Server -> CM5

Docelowy kierunek:

```text
ventilation_analysis_runs
    ↓
read-only latest-analysis endpoint
    ↓
CM5 advisory client
    ↓
cache/status/GUI operatora
```

Zasady:

- CM5 nie czeka na AI w logice sterowania,
- brak AI nie wpływa na wentylację,
- raport może być wyświetlany lub logowany,
- raport musi być oznaczony jako advisory/experimental,
- raport nie może automatycznie zmieniać trybu ani setpointów,
- nie powstaje żaden endpoint sterujący AI -> CM5.

## Wniosek

Stage 2 osiągnął funkcjonalny PASS, idempotencję PASS oraz produkcyjny systemd oneshot PASS. Profil `ventilation-v10-baseline-safe` jest zamrożonym fundamentem. Timer pozostaje wyłączony, a kolejnym etapem jest bezpieczne read-only dostarczenie raportu do CM5.