# AI Bridge – Ventilation AI Analysis Stage 2

**Data:** 10.08.2026  
**Status:** IMPLEMENTED – `ventilation-v9-simple-report` oczekuje na końcową walidację  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź:** `agent/ventilation-ai-analysis-stage2`

## 1. Cel

Dodać prostą i bezpieczną warstwę interpretacji danych wentylacji przez lokalny model `qwen3.6:35b`, pozostawiając pełne sterowanie i safety po stronie CM5.

```text
PostgreSQL RAW
    ↓
Python – pełne statystyki matematyczne
    ↓
pełny input_summary – audit/history
    ↓
compact analysis packet
    ↓
Ollama / qwen3.6:35b / think=true
    ↓
minimalny raport JSON
    ↓
Pydantic – walidacja struktury
    ↓
ventilation_analysis_runs
```

AI nie znajduje się na ścieżce sterowania ani ACK CM5.

## 2. Granica bezpieczeństwa

```text
CM5 = sterowanie + safety
Python = matematyka + infrastruktura
Qwen = interpretacja + rekomendacje
```

Awaria AI Servera lub Qwena nie wpływa na wentylację.

## 3. Okna i data-quality gate

Analiza działa na zamkniętych oknach 15-minutowych. Przy capture co około 5 s pełne okno ma około 180 próbek.

Minimalny gate:

```text
120 próbek
```

Poniżej tego progu Qwen nie jest wywoływany; zapisywany jest wynik `insufficient_data`.

## 4. Przygotowanie danych

Python oblicza pełne statystyki, m.in.:

- count / missing,
- mean / min / max / stddev,
- first / last / delta,
- slope_per_minute,
- tryb i setpointy,
- alarmy,
- stan SENSOR BUS,
- oba SEN55,
- liczniki diagnostyczne.

Pełny `input_summary` jest zachowywany w PostgreSQL.

Do Qwena trafia compact packet zawierający tylko dane potrzebne do bieżącej interpretacji. Nie ma w nim progów ani klasyfikacji wykonywanej przez Python.

## 5. Historia eksperymentów v1-v8

Wersje były walidowane na tym samym oknie:

```text
2026-08-10T12:00:00Z..12:15:00Z
179 próbek
```

Najważniejsze wnioski:

- v1/v2 – model zbyt płytko odczytywał pełny materiał i pomijał PM/VOC,
- v3/v4 – provenance i rozbudowane walidatory okazały się zbyt skomplikowane,
- v5 – prosty output przy `think=false` nadal był za płytki,
- v6 – `think=true` poprawił analizę trendów, ale pełny input nadal powodował błędy,
- v7 – compact packet wyraźnie poprawił poprawność odczytania danych: Qwen zauważył wzrost VOC, spadek PM, stabilną temperaturę/wilgotność i płaski NOx,
- v8 – dodatkowe instrukcje raportowania nie rozwiązały problemu pustych list i języka.

### Rzeczywisty wynik v8

```text
analysis_id=4f3cf63d-6f01-4f21-9eb1-30449f8b38b8
prompt_version=ventilation-v8-reporting
sample_count=179
HTTP 200 OK
status=normal
```

Model prawidłowo zauważył wzrost VOC, spadek PM i stabilność temperatury/wilgotności, ale:

- odpowiedział po angielsku,
- pozostawił `observations=[]`,
- pozostawił `anomalies=[]`, `recommendations=[]` i `data_quality_notes=[]`,
- zwrócił `confidence=0.98`.

Wniosek: compact packet i `think=true` są właściwe. Problemem był sam wielopolowy kontrakt odpowiedzi.

## 6. Aktywny kontrakt – schema v2

Profil:

```text
ventilation-v9-simple-report
```

Wynik:

```text
schema_version = 2
status
analysis_pl
operator_recommendation_pl
data_quality_pl
```

Status:

```text
no_anomaly_detected
attention
anomaly
insufficient_data
```

Wszystkie trzy pola tekstowe są obowiązkowe i mają być napisane po polsku.

Usunięto:

- `summary`,
- `confidence`,
- `observations[]`,
- `anomalies[]`,
- `recommendations[]`,
- `data_quality_notes[]`.

Powód: pola zwiększały złożoność kontraktu, ale model często zostawiał listy puste i przenosił całą analizę do `summary`. `confidence` regularnie osiągało 0.98–1.0 mimo braku baseline'u.

Nowy kontrakt jest celowo mały i przygotowany do późniejszej rozbudowy.

## 7. Zasady promptu v9

Qwen ma:

- analizować stan sterownika, SENSOR BUS i oba SEN55,
- zwracać uwagę na PM, VOC, NOx, temperaturę i wilgotność,
- używać tylko danych z packetu,
- wszystkie pola tekstowe pisać po polsku,
- nie traktować STOP + setpoint 0 V jako awarii bez dodatkowych przesłanek,
- pamiętać, że setpointy 0–10 V nie są pomiarem RPM ani przepływu,
- nie wymyślać CO2/RPM/airflow,
- uwzględniać brak historycznego baseline'u,
- nie dodawać meta-ofert ani komentarzy niezwiązanych z analizą.

## 8. PostgreSQL

Tabela `ventilation_analysis_runs` już obsługuje nowy kontrakt:

- `status` to pole tekstowe,
- `result` to JSON,
- `input_summary` to JSON.

**Nie jest potrzebna nowa migracja Alembic.**

Idempotencja pozostaje:

```text
(source_id, window_start, window_end, model, prompt_version)
```

Dzięki `prompt_version=ventilation-v9-simple-report` to samo okno może zostać przeanalizowane ponownie bez usuwania wcześniejszych wyników.

## 9. Następny etap – wynik AI dla CM5

Po zakończeniu Stage 2 pozostaje przygotowanie kanału read-only z AI Servera do CM5.

Planowany kierunek:

```text
ventilation_analysis_runs
    ↓
AI Bridge read-only endpoint – latest analysis
    ↓
CM5 advisory client
    ↓
cache/status/GUI operatora
```

Najważniejsze zasady:

- CM5 nigdy nie czeka na AI w logice sterowania,
- brak połączenia z AI Serverem nie wpływa na wentylację,
- pobrany raport może być wyświetlany lub logowany,
- raport nie jest wejściem do automatycznej logiki setpointów,
- nie tworzymy żadnego endpointu pozwalającego AI sterować CM5.

Szczegółowy endpoint i klient CM5 będą osobnym etapem po ustabilizowaniu raportu v9.

## 10. Co pozostaje do walidacji Stage 2

Na AI Serverze:

1. `compileall`,
2. pełny `pytest`,
3. realny przebieg tego samego okna 179 próbek,
4. potwierdzenie `prompt_version=ventilation-v9-simple-report`,
5. sprawdzenie, czy wszystkie trzy pola tekstowe są po polsku i zawierają sensowną analizę,
6. test idempotencji v9,
7. dopiero potem test deploymentu/systemd timer.

Timer nadal pozostaje niewłączony.

## 11. Status

Stage 2 pozostaje Draft. Nie oznaczać PR jako Ready i nie wykonywać merge przed ręcznym PASS `ventilation-v9-simple-report` na rzeczywistym Serwerze AI.
