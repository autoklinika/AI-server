# ADR-005 – Wykonywanie analiz wentylacji przez Qwen

**Status:** Stage 2 – profil bazowy zamrożony; domknięcie techniczne w toku  
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

Pełny `input_summary` zachowuje m.in.:

- count / missing,
- mean / min / max / stddev,
- first / last / delta,
- slope_per_minute,
- stan sterownika i setpointy,
- alarmy,
- SENSOR BUS,
- oba węzły SEN55,
- liczniki diagnostyczne.

Python nie definiuje progów anomalii i nie klasyfikuje jakości powietrza.

Do Qwena trafia mniejszy `compact analysis packet`, który usuwa redundancję, ale nie interpretuje danych. Packet zachowuje PM, VOC, NOx, temperaturę, wilgotność, stan systemu, SENSOR BUS i diagnostykę. Jawnie rozróżnia pomiary dostępne od niedostępnych (`co2`, `fan_rpm`, `airflow`).

## Aktywny profil – `ventilation-v10-baseline-safe`

Eksperymenty v1-v9 wykazały, że:

- `think=true` poprawia zauważanie trendów,
- compact packet poprawia poprawność odczytania danych,
- rozbudowany formularz odpowiedzi nie wnosi obecnie wartości,
- minimalny schema v2 jest właściwą bazą do dalszej rozbudowy,
- przy braku historycznego baseline'u Qwen nie może używać pojęć sugerujących istnienie znanych norm lub progów.

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

Profil `ventilation-v10-baseline-safe` jawnie zabrania modelowi używania określeń:

- `w normie`,
- `typowe`,
- `bezpieczne`,
- `nie przekracza progów`,

jeżeli odpowiedni baseline, norma lub próg nie został przekazany w danych.

Brak historycznego baseline'u oznacza, że Qwen może opisywać wartości, kierunek zmian i zależności w oknie, ale nie może klasyfikować ich względem normalnej pracy warsztatu.

Ta zasada pozostaje częścią promptu. Python nie wykonuje semantycznej klasyfikacji odpowiedzi.

## Rzeczywista walidacja v10

Dla historycznego okna:

```text
2026-08-10T12:00:00Z..12:15:00Z
179 próbek
```

uzyskano:

```text
analysis_id=2dbf4563-e18b-47db-a3d8-18cb6f8f79e7
prompt_version=ventilation-v10-baseline-safe
schema_version=2
status=no_anomaly_detected
HTTP 200 OK
reused_existing=false
```

Profil v10 spełnił cel ochrony baseline/progów: odpowiedź nie deklarowała, że pomiary są `w normie`, `typowe`, `bezpieczne` ani że `nie przekraczają progów`.

Jednocześnie pozostają świadomie akceptowane ograniczenia bieżącej jakości generacji:

- model może nie opisać obu SEN55 równie dokładnie,
- może dodać niepotrzebny meta-tekst o dalszej integracji,
- może wygenerować zbyt swobodną rekomendację operatorską, np. kalibrację lub interpretację źródła VOC bez wystarczającej podstawy,
- raport nie powinien być traktowany jako instrukcja sterowania ani jako zweryfikowana diagnoza.

Nie rozwijamy teraz kolejnych wersji promptu tylko po to, aby usuwać te niedoskonałości. Bieżący wynik jest **bazą eksperymentalno-doradczą**, przygotowaną do późniejszego ulepszenia po zebraniu rzeczywistego baseline'u warsztatu.

## Structured output

Ollama:

```text
POST http://127.0.0.1:11434/api/chat
model=qwen3.6:35b
stream=false
think=true
temperature=0
format=<compact JSON Schema>
```

Pydantic sprawdza wyłącznie strukturę i typy.

## Idempotencja

Jednoznaczność analizy:

```text
source_id
+ window_start
+ window_end
+ model
+ prompt_version
```

Zmiana `prompt_version` pozwala ponownie przeanalizować to samo historyczne okno bez kasowania wcześniejszych wyników.

Dla `ventilation-v10-baseline-safe` pozostaje do wykonania końcowy realny test ponownego uruchomienia tego samego okna. Oczekiwany wynik: ten sam `analysis_id`, `reused_existing=true` i brak nowego wywołania Ollamy.

## PostgreSQL

Wynik jest przechowywany jako JSON w `ventilation_analysis_runs`, a `status` jako zwykłe pole tekstowe. Schema v2 nie wymaga dodatkowej migracji bazy.

Pełny `input_summary` nadal pozostaje zapisany jako materiał audytowy.

## Decyzja o zamrożeniu interpretacji Stage 2

Rozwój promptu i kontraktu odpowiedzi zostaje zamrożony na `ventilation-v10-baseline-safe`.

Nie planujemy v11/v12 w bieżącym Stage 2.

Do rozbudowy interpretacji wrócimy dopiero po zebraniu rzeczywistej historii warsztatu, kiedy będzie można zaprojektować:

- historyczny baseline,
- porównania między oknami i dniami,
- progi lub reguły oparte na rzeczywistych danych,
- bardziej rozbudowane raporty i klasyfikacje.

## Następny etap – odczyt wyniku przez CM5

Po domknięciu technicznym Stage 2 planowany jest **wyłącznie read-only kanał AI Server -> CM5**.

Docelowy kierunek:

```text
AI Server / ventilation_analysis_runs
        ↓
read-only HTTP endpoint latest analysis
        ↓
CM5 advisory client
        ↓
lokalny cache / GUI / status dla operatora
```

Zasady tego kanału:

- CM5 pobiera wynik asynchronicznie i nie czeka na niego w logice sterowania,
- brak odpowiedzi AI nie powoduje zmiany pracy wentylacji,
- wynik AI może być wyświetlany, logowany lub udostępniany operatorowi,
- wynik AI musi być oznaczony jako doradczy/eksperymentalny na tym etapie,
- wynik AI nie może automatycznie zmieniać trybu, setpointów ani żadnego elementu sterowania,
- nie będzie endpointu AI -> CM5 wykonującego komendy sterujące.

Szczegółowy kontrakt read-only endpointu i klienta CM5 zostanie zaprojektowany w kolejnym etapie.

## Ograniczenia bieżącego Stage 2

- brak automatycznego sterowania przez AI,
- brak endpointu sterującego,
- brak fine-tuningu,
- brak pełnego historycznego baseline'u warsztatu,
- timer analizy nadal niewłączony do końcowego testu idempotencji i deploymentu,
- odczyt wyniku przez CM5 jeszcze niezaimplementowany.

## Wniosek

Stage 2 kończymy na prostej bazie: Python liczy i przygotowuje dane, Qwen tworzy krótki raport po polsku, a wynik trafia do PostgreSQL. Profil `ventilation-v10-baseline-safe` jest zamrożonym fundamentem do późniejszego rozwoju. Kolejny etap dotyczy już dostarczenia raportu do CM5 w kanale read-only.