# ADR-003 – AI Bridge jako wspólna platforma pośrednicząca

**Status:** Zatwierdzone  
**Data:** 07.08.2026

## Kontekst

W projekcie Serwera AI potrzebna jest aplikacja pośrednicząca pomiędzy systemami źródłowymi, magazynem danych oraz lokalnym modelem AI uruchamianym przez Ollamę.

Pierwszym obsługiwanym systemem jest Workshop Ventilation Controller oparty o CM5. W przyszłości ta sama infrastruktura AI może zostać wykorzystana także przez inne projekty, między innymi CRT.

## Decyzja

Aplikacja pośrednicząca będzie nosiła nazwę **AI Bridge**.

AI Bridge zostanie zaprojektowany jako **wspólna, ogólna platforma**, a nie jako program napisany wyłącznie dla wentylacji.

Jednocześnie logika specyficzna dla poszczególnych systemów będzie odseparowana w osobnych adapterach domenowych.

## Zasada architektoniczna

Wspólny rdzeń AI Bridge odpowiada za elementy infrastrukturalne, które mogą być współdzielone przez wiele projektów:

- komunikację z Ollamą i lokalnymi modelami AI,
- kolejkę i harmonogram zadań analitycznych,
- obsługę pamięci i historii analiz,
- budowanie oraz zarządzanie promptami,
- walidację odpowiedzi modeli,
- zapis wyników analiz,
- logowanie i diagnostykę,
- udostępnianie API,
- wspólne mechanizmy konfiguracji i obsługi błędów.

Logika domenowa nie może być umieszczana bezpośrednio w rdzeniu.

## Adaptery domenowe

Każdy obsługiwany system otrzymuje własny adapter.

Planowane adaptery:

### ventilation

Adapter wentylacji będzie znał między innymi:

- strukturę danych wysyłanych przez CM5,
- dane z SEN55,
- informacje o pracy wentylatorów,
- kontekst instalacji wentylacyjnej,
- baseline normalnej pracy warsztatu,
- zasady przygotowania danych do analizy wentylacji,
- Knowledge Base projektu wentylacji.

### crt

W przyszłości może powstać osobny adapter CRT odpowiedzialny za interpretację danych właściwych dla tego systemu, na przykład:

- ramek CAN,
- danych UDS i J1939,
- sesji diagnostycznych,
- logów testów,
- danych pomiarowych,
- kontekstu diagnostycznego CRT.

Adapter CRT będzie korzystał ze wspólnego rdzenia AI Bridge, ale jego logika domenowa będzie całkowicie oddzielona od logiki wentylacji.

## Proponowana struktura projektu

```text
ai_bridge/
├── core/
├── ollama/
├── storage/
├── api/
└── adapters/
    ├── ventilation/
    └── crt/
```

Struktura jest kierunkowa i może zostać doprecyzowana podczas projektowania aplikacji.

## Zakres pierwszej implementacji

Na pierwszym etapie implementowany jest wyłącznie adapter:

`ventilation`

Adapter CRT jest jedynie przewidziany w architekturze. Nie implementujemy go na obecnym etapie.

## Uzasadnienie

Takie podejście pozwala:

- uniknąć duplikowania infrastruktury AI,
- utrzymać jeden mechanizm komunikacji z Ollamą,
- współdzielić mechanizmy logowania, historii, API i walidacji,
- rozwijać kolejne integracje bez przebudowy rdzenia,
- zachować ścisłe oddzielenie logiki domenowej poszczególnych projektów,
- ograniczyć ryzyko, że zmiany wymagane przez CRT wpłyną na działanie wentylacji.

## Ważne ograniczenie

Wspólny AI Bridge nie oznacza wspólnej logiki sterowania.

AI Bridge pozostaje warstwą analityczną i integracyjną.

W projekcie wentylacji nadal obowiązuje nadrzędna zasada:

**CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.**

Analogicznie przyszłe integracje muszą zachować granice odpowiedzialności właściwe dla swoich systemów.

## Wniosek

Tworzymy jeden wspólny **AI Bridge** z modułowym rdzeniem i osobnymi adapterami domenowymi.

Pierwszym adapterem jest `ventilation`.

W przyszłości CRT może zostać dołączony poprzez osobny adapter `crt`, bez tworzenia drugiego niezależnego bridge'a i bez mieszania logiki obu projektów.
