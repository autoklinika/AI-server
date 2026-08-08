# Ventilation Telemetry API v1

**Status:** zatwierdzony kontrakt bazowy do implementacji  
**Projekt:** AI Server / AI Bridge + Workshop Ventilation Controller  
**Wersja kontraktu:** `1`  
**Data:** 08.08.2026

## 1. Cel

Ventilation Telemetry API v1 definiuje kontrakt komunikacyjny pomiędzy sterownikiem wentylacji CM5 a adapterem `ventilation` w AI Bridge.

API służy do niezawodnego przesyłania surowej telemetrii z CM5 do AI Servera. API nie służy do sterowania wentylacją.

Obowiązuje nadrzędna zasada:

> **CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.**

Awaria AI Bridge, centralnej bazy danych, Ollamy, Qwena lub sieci LAN nie może wpływać na zdolność CM5 do bezpiecznego sterowania wentylacją.

## 2. Kierunek komunikacji

Podstawowy przepływ:

```text
czujniki / sterowanie
        ↓
       CM5
        ↓
lokalny zapis pomiaru
        ↓
kolejka synchronizacji
        ↓
HTTP POST
        ↓
AI Bridge
        ↓
walidacja
        ↓
centralna baza danych
        ↓
commit transakcji
        ↓
ACK
        ↓
CM5 oznacza dane jako zsynchronizowane
```

AI Bridge nie kontaktuje się z Qwenem podczas obsługi żądania telemetrycznego.

Ścieżka:

```text
CM5 → AI Bridge → DB → ACK
```

musi być niezależna od:

```text
AI Bridge → Ollama → Qwen
```

## 3. Transport

Transport v1:

```text
HTTP
Content-Type: application/json
```

Endpoint:

```text
POST /api/v1/ventilation/telemetry/batches
```

API jest przeznaczone do pracy w zaufanej sieci lokalnej. Ollama pozostaje dostępna wyłącznie lokalnie na AI Serverze i nie jest częścią tego kontraktu.

## 4. Wersjonowanie

Każda paczka zawiera:

```json
{
  "schema_version": 1
}
```

AI Bridge musi odrzucić wersję schematu, której nie obsługuje.

Zmiana znaczenia istniejącego pola albo usunięcie pola wymaga nowej wersji kontraktu. Dodanie opcjonalnego pola, które nie zmienia znaczenia istniejących danych, może pozostać kompatybilne z v1.

## 5. Identyfikacja CM5

Każdy sterownik posiada stały identyfikator:

```text
source_id
```

Przykład:

```json
"source_id": "workshop-ventilation-cm5-01"
```

`source_id`:

- jest generowany lub konfigurowany raz,
- pozostaje stały po restartach,
- nie zależy od adresu IP,
- nie zależy od hostname,
- identyfikuje sterownik będący źródłem danych.

## 6. Paczka synchronizacyjna

CM5 przesyła dane w paczkach.

Minimalna struktura:

```json
{
  "schema_version": 1,
  "source_id": "workshop-ventilation-cm5-01",
  "batch_id": "01K1ABCDE123456789XYZ12345",
  "created_at": "2026-08-08T13:30:00.000+02:00",
  "samples": []
}
```

### `batch_id`

Każda paczka otrzymuje unikalny identyfikator. Wymagania:

- globalnie unikalny,
- niezmieniany podczas retransmisji,
- ponowne wysłanie tej samej paczki używa tego samego `batch_id`.

Preferowany format: ULID. Dopuszczalny technicznie jest również UUID.

## 7. Pojedynczy rekord synchronizacyjny

Każdy snapshot telemetryczny ma własny identyfikator:

```json
{
  "sample_id": "01K1ABCDE987654321XYZ98765",
  "sequence": 184928,
  "captured_at": "2026-08-08T13:29:55.250+02:00",
  "metrics": {}
}
```

Wymagane pola:

```text
sample_id
sequence
captured_at
metrics
```

`captured_at` oznacza czas wykonania snapshotu autorytatywnego `CoreState` przez CM5. Szczegóły czasu poszczególnych węzłów SEN55 pozostają częścią danych w `metrics`.

## 8. `sample_id`

`sample_id` jednoznacznie identyfikuje konkretny snapshot telemetryczny.

Musi być:

- utworzony na CM5,
- zapisany razem z lokalnym rekordem,
- zachowany podczas retransmisji,
- niezmienny.

Preferowany format: ULID.

Centralna baza musi posiadać ograniczenie unikalności co najmniej dla:

```text
source_id + sample_id
```

Ponowne przesłanie tego samego rekordu nie może utworzyć kolejnej kopii RAW.

## 9. `sequence`

Każdy kolejny snapshot CM5 otrzymuje rosnący licznik `sequence`.

Służy on do:

- wykrywania luk,
- diagnostyki synchronizacji,
- ustalania kolejności rekordów,
- wykrywania brakujących fragmentów transmisji.

Nie może być jedynym identyfikatorem rekordu. Po normalnym restarcie CM5 licznik powinien być kontynuowany. Jeżeli z powodów serwisowych zostanie wyzerowany, unikalność nadal zapewnia `sample_id`.

## 10. Czas

`captured_at` używa formatu ISO 8601 / RFC 3339 ze strefą czasową.

AI Bridge dodatkowo zapisuje własne:

```text
received_at
```

ustawiane przez serwer w chwili odebrania danych.

Nie wolno zastępować `captured_at` przez `received_at`, ponieważ przy synchronizacji zaległych danych oba czasy mogą znacząco się różnić.

## 11. Telemetria `metrics`

`metrics` zawiera snapshot autorytatywnego `CoreState` CM5. Szczegółowy model danych jest zdefiniowany w osobnym dokumencie:

`docs/VENTILATION_TELEMETRY_DATA_MODEL_V1_PL.md`

AI Bridge zapisuje warstwę RAW bez reinterpretowania oryginalnych wartości.

## 12. Pola niedostępne

Jeżeli konkretna wartość jest niedostępna, powinna być reprezentowana zgodnie z autorytatywnym modelem CM5 jako `null` albo pole opcjonalne zgodnie ze schematem.

Nie wolno zastępować braku danych sztucznymi wartościami typu `-1`, `9999` lub `0`, jeśli zero nie jest rzeczywistą wartością.

## 13. Pełny przykład paczki

```json
{
  "schema_version": 1,
  "source_id": "workshop-ventilation-cm5-01",
  "batch_id": "01K1ABCDEF0000000000000001",
  "created_at": "2026-08-08T13:30:00.000+02:00",
  "samples": [
    {
      "sample_id": "01K1ABCDEF0000000000000101",
      "sequence": 184927,
      "captured_at": "2026-08-08T13:29:50.000+02:00",
      "metrics": {
        "mode": "MANUAL",
        "setpoints": {
          "supply_voltage": 6.0,
          "extract_voltage": 5.5
        }
      }
    },
    {
      "sample_id": "01K1ABCDEF0000000000000102",
      "sequence": 184928,
      "captured_at": "2026-08-08T13:29:55.000+02:00",
      "metrics": {
        "mode": "MANUAL",
        "setpoints": {
          "supply_voltage": 6.0,
          "extract_voltage": 5.5
        }
      }
    }
  ]
}
```

Przykład jest skrócony. Pełny `metrics` opisuje dokument modelu danych v1.

## 14. Zapis transakcyjny

AI Bridge wykonuje dla paczki:

```text
walidacja JSON
      ↓
walidacja kontraktu
      ↓
rozpoczęcie transakcji DB
      ↓
zapis batch
      ↓
zapis nowych samples
      ↓
pominięcie znanych duplikatów
      ↓
COMMIT
      ↓
ACK
```

ACK nie może zostać wysłany przed poprawnym `COMMIT`.

## 15. Odpowiedź ACK

Poprawna odpowiedź:

```http
HTTP/1.1 200 OK
```

Przykład:

```json
{
  "schema_version": 1,
  "source_id": "workshop-ventilation-cm5-01",
  "batch_id": "01K1ABCDEF0000000000000001",
  "status": "accepted",
  "received": 2,
  "stored": 2,
  "duplicates": 0,
  "rejected": 0,
  "server_time": "2026-08-08T13:30:01.154+02:00"
}
```

## 16. Ponowne wysłanie paczki

Jeżeli CM5 nie otrzyma ACK, zachowuje dane jako niesynchronizowane i może ponownie wysłać tę samą paczkę z tym samym `batch_id` i tymi samymi `sample_id`.

Przykładowa odpowiedź po retransmisji:

```json
{
  "schema_version": 1,
  "source_id": "workshop-ventilation-cm5-01",
  "batch_id": "01K1ABCDEF0000000000000001",
  "status": "accepted",
  "received": 2,
  "stored": 0,
  "duplicates": 2,
  "rejected": 0,
  "server_time": "2026-08-08T13:31:15.120+02:00"
}
```

Dla CM5 jest to poprawny ACK i rekordy mogą zostać oznaczone lokalnie jako zsynchronizowane.

## 17. Idempotencja

System musi być odporny zarówno na ponowne wysłanie całego batcha, jak i na pojawienie się tego samego sample w innej paczce.

Idempotencja działa na dwóch poziomach:

```text
source_id + batch_id
```

oraz:

```text
source_id + sample_id
```

Centralna baza nie może przechowywać dwóch kopii tego samego rekordu RAW.

## 18. Błędy walidacji

Niepoprawna struktura żądania:

```http
422 Unprocessable Entity
```

Przykład:

```json
{
  "status": "rejected",
  "error": "validation_error",
  "details": [
    {
      "path": "samples[0].captured_at",
      "message": "invalid timestamp"
    }
  ]
}
```

CM5 nie powinien bez końca ponawiać dokładnie tej samej paczki, jeżeli AI Bridge jednoznacznie zwróci trwały błąd jej zawartości. Przypadek taki musi zostać zapisany w diagnostyce CM5.

## 19. Nieobsługiwana wersja

Odpowiedź:

```http
400 Bad Request
```

Przykład:

```json
{
  "status": "rejected",
  "error": "unsupported_schema_version",
  "supported_versions": [1]
}
```

## 20. Tymczasowa awaria AI Bridge

Przykłady: brak bazy danych, brak miejsca na dysku lub błąd zapisu.

AI Bridge zwraca:

```http
503 Service Unavailable
```

CM5 nie oznacza danych jako zsynchronizowane i ponawia próbę później.

## 21. Awaria Ollamy

Awaria Ollamy nie wpływa na endpoint telemetryczny.

Jeżeli baza danych działa poprawnie, stan `Ollama DOWN` nie może powodować `503` dla poprawnego:

```text
POST /api/v1/ventilation/telemetry/batches
```

AI Bridge nadal wykonuje:

```text
odbiór → zapis → ACK
```

Analiza AI jest osobnym procesem.

## 22. Retry po stronie CM5

CM5 nie powinien wykonywać agresywnej pętli ponowień. Punkt startowy polityki retry:

```text
pierwsza próba
↓
5 s
↓
15 s
↓
30 s
↓
60 s
↓
dalsze próby okresowe
```

Po odzyskaniu komunikacji zaległe rekordy są wysyłane od najstarszych do najnowszych. Błędy komunikacyjne nie mogą blokować głównej logiki sterowania CM5.

## 23. Kolejka synchronizacji CM5

Lokalny rekord posiada logiczny stan:

```text
pending
synced
```

Opcjonalnie implementacja może również przechowywać:

```text
last_sync_attempt
sync_attempt_count
```

Status `synced` może zostać ustawiony dopiero po poprawnym ACK od AI Bridge.

30-dniowa retencja lokalnej historii jest niezależna od stanu synchronizacji. Rekord `pending` nie może zostać usunięty tylko dlatego, że przekroczył zwykły termin retencji.

## 24. Wielkość paczki

Rekomendowany punkt startowy:

```text
maksymalnie 500 samples / batch
```

Roboczy limit rozmiaru requestu v1:

```text
1 MiB
```

Parametry mogą zostać później dostrojone bez zmiany semantyki kontraktu.

## 25. Kolejność danych

AI Bridge nie może zakładać, że dane zawsze docierają chronologicznie. Centralna historia korzysta z `captured_at`, a do diagnostyki synchronizacji używa również `sequence` i `received_at`.

## 26. Granica odpowiedzialności API

Ventilation Telemetry API v1 może:

- odbierać telemetrię,
- zapisywać telemetrię,
- potwierdzać synchronizację,
- zgłaszać błędy transportowe i walidacyjne.

Nie może:

- ustawiać prędkości wentylatorów,
- zmieniać algorytmów CM5,
- zmieniać progów bezpieczeństwa,
- wykonywać poleceń sterujących,
- omijać zabezpieczeń CM5.

W v1 nie istnieje endpoint typu:

```text
/command
/control
/set-speed
/set-output
/actuator
```

## 27. Health endpoint

AI Bridge powinien posiadać:

```text
GET /health
```

Podstawowa odpowiedź:

```json
{
  "status": "ok"
}
```

Dodatkowa diagnostyka może raportować osobno stan bazy danych i Ollamy. Niedostępność Ollamy nie oznacza niedostępności funkcji ingestion.

## 28. Bezpieczeństwo Stage 1

API działa wyłącznie w zaufanej sieci LAN.

Stage 1 nie przewiduje:

- publikowania API do Internetu,
- publicznego dostępu do Ollamy,
- cloud gateway,
- zdalnego sterowania przez API.

Mechanizm uwierzytelniania CM5 zostanie określony przed produkcyjnym uruchomieniem komunikacji. Kontrakt transportowy powinien umożliwiać późniejsze dodanie uwierzytelniania bez zmiany struktury telemetrycznej.

## 29. Dane zapisywane przez AI Bridge

Dla każdej paczki AI Bridge zapisuje co najmniej:

```text
batch_id
source_id
schema_version
created_at
received_at
liczba rekordów
wynik przetwarzania
```

Dla każdego sample co najmniej:

```text
source_id
sample_id
sequence
captured_at
received_at
metrics
```

AI Bridge nigdy nie modyfikuje oryginalnych wartości telemetrycznych przy zapisie warstwy RAW.

## 30. RAW vs dane przetworzone

Centralne archiwum logicznie rozdziela:

```text
RAW telemetry
```

od:

```text
derived statistics
```

oraz:

```text
AI analysis results
```

Przepływ:

```text
RAW
 ↓
deterministic preparation
 ↓
statistics
 ↓
Qwen
 ↓
interpretation
```

Qwen nigdy nie zmienia danych RAW.

## 31. Kryteria walidacji kontraktu v1

Kontrakt uznajemy za poprawnie zaimplementowany, gdy przejdą co najmniej następujące scenariusze:

1. Standardowy zapis 100 nowych samples: `stored=100`, `duplicates=0`.
2. Retransmisja tej samej paczki: `stored=0`, `duplicates=100`, bez wzrostu liczby rekordów RAW.
3. Paczka częściowo nakładająca się: 50 starych + 50 nowych → `stored=50`, `duplicates=50`.
4. Brak AI Bridge: CM5 kontynuuje sterowanie i zachowuje dane jako `pending`.
5. Restart AI Bridge: synchronizacja działa dalej bez utraty danych.
6. Ollama wyłączona: telemetria jest nadal odbierana, zapisywana i potwierdzana ACK.
7. Centralna baza wyłączona: AI Bridge nie potwierdza zapisu, CM5 zachowuje dane jako `pending`.
8. Po odzyskaniu komunikacji CM5 synchronizuje zaległe dane z oryginalnym `captured_at`.
9. Luka `sequence` jest wykrywalna diagnostycznie, ale sama w sobie nie jest anomalią wentylacji.
10. Żadna kombinacja retry, restartu lub utraty ACK nie tworzy dwóch rekordów RAW dla tego samego `source_id + sample_id`.

## 32. Decyzja architektoniczna

Ventilation Telemetry API v1 przyjmuje model:

```text
CM5
 │
 │ RAW telemetry
 ▼
AI Bridge
 │
 ├── idempotent storage
 ├── ACK
 │
 └── późniejsza analiza
          │
          ▼
        Qwen
```

Granica systemu pozostaje jednoznaczna:

> **AI Bridge jest konsumentem danych CM5. Nie jest kontrolerem CM5.**

CM5 pozostaje jedynym autonomicznym sterownikiem wentylacji.
