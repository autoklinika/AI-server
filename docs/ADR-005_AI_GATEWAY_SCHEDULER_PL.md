# ADR-005 – Centralny AI Gateway i scheduler priorytetowy

**Status:** implementacja etapowa  
**Wersja platformy:** AI Bridge 0.4.0

## Kontekst

Serwer AI obsługuje już więcej niż jednego klienta modelu: automatyczną analizę
wentylacji oraz Hermesa używanego m.in. przez Telegram. Wraz z kolejnymi klientami
(RAG, robot, generowanie obrazów i zadania tła) bezpośredni dostęp wielu procesów do
Ollamy nie daje jednego miejsca do kontrolowania kolejności i obciążenia inferencji.

Dwa wymagania są nadrzędne:

1. zadania infrastrukturalne, przede wszystkim analiza wentylacji, muszą mieć wyższy
   priorytet niż interaktywne i tła;
2. Hermes pozostaje warstwą agentową i sesyjną, a zarządzanie dostępem do modelu nie
   może być zaszyte w logice Telegrama.

## Decyzja

Wprowadzamy lokalny proces `ai-gateway` pomiędzy klientami a Ollamą.

```text
Telegram / przyszły robot
          |
        Hermes
          |  OpenAI-compatible API
          v
    +-------------+
    | AI Gateway  |----> Ollama ----> Qwen
    | + scheduler |
    +-------------+
          ^
          |
Wentylacja / AI Bridge analysis
```

Ollama pozostaje backendem inferencji. Gateway nie interpretuje promptów i nie
uruchamia dodatkowego modelu; wykonuje wyłącznie admission control, kolejkę,
priorytety, routing HTTP i diagnostykę.

## Interfejsy

Gateway udostępnia lokalnie:

- `POST /api/chat`
- `POST /api/generate`
- `POST /api/embed`
- `POST /api/embeddings`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /api/tags`
- `GET /v1/models`
- `GET /health`
- `GET /status`

Nagłówki sterujące:

- `X-AI-Priority` – liczba całkowita; mniejsza wartość oznacza wyższy priorytet;
- `X-AI-Source` – krótka nazwa źródła zadania do diagnostyki.

Hermes korzystający z endpointu OpenAI otrzymuje domyślnie klasę `interactive`,
więc nie wymaga własnego nagłówka do pierwszego wdrożenia.

## Klasy priorytetów v1

| Klasa | Wartość | Przykład |
|---|---:|---|
| ventilation | 10 | automatyczna analiza CM5 |
| interactive | 50 | Hermes / Telegram |
| normal | 100 | RAG, zwykła analiza |
| background | 200 | zadania tła |

Zostawiamy odstępy między klasami, aby później dodawać poziomy bez migracji
istniejących klientów.

## Zasady schedulera v1

- kolejka jest priorytetowa;
- dla tego samego priorytetu obowiązuje FIFO;
- `max_concurrency=1` jest bezpiecznym ustawieniem początkowym;
- request strumieniowy zajmuje slot aż do zamknięcia strumienia;
- oczekujący request o wyższym priorytecie zostaje uruchomiony przed niższym;
- **v1 nie przerywa requestu, który już rozpoczął inferencję**.

Brak preempcji jest świadomą decyzją pierwszego etapu. Przerywanie aktywnej
odpowiedzi Hermesa wymaga osobnej polityki `preemptible`, żeby nie psuć rozmów
użytkowników.

## Granica z generowaniem obrazów

Ta wersja schedulera kontroluje ruch do Ollamy. Nie gwarantuje jeszcze, że lokalny
generator obrazów używający GPU poza gatewayem zostanie zatrzymany lub niedopuszczony
przed analizą wentylacji. Docelowy Resource Manager musi objąć również backend obrazu
albo wymagać od niego wspólnego mechanizmu admission control.

To jest kolejny etap po walidacji ruchu `Hermes + wentylacja + Ollama`.

## Bezpieczeństwo

`ai-gateway` domyślnie nasłuchuje tylko na `127.0.0.1:11435`. Obecne procesy
Hermesa i analizy wentylacji działają na tym samym Serwerze AI, więc nie ma potrzeby
wystawiania endpointu schedulera do LAN.

Ollama nadal może zostać ograniczona do localhost. Docelowo klienci aplikacyjni nie
powinni omijać gatewaya.

## Bezpieczny rollout

1. Zainstalować kod 0.4.0 bez zmiany istniejącej trasy analizy.
2. Uruchomić `ai-gateway.service` obok działającej Ollamy.
3. Sprawdzić `GET http://127.0.0.1:11435/health` i `/status`.
4. Wykonać kontrolny request przez `/api/chat`.
5. Ustawić `AI_BRIDGE_ANALYSIS_USE_GATEWAY=true` i zwalidować pełne okno wentylacji.
6. Dopiero po tej walidacji ustawić bazowy endpoint Hermesa na
   `http://127.0.0.1:11435/v1`.
7. Przetestować dwóch użytkowników Telegrama równocześnie i potwierdzić osobne
   sesje po stronie Hermesa.

## Obserwowalność

Każda odpowiedź inferencyjna dostaje nagłówki:

- `X-AI-Gateway-Job-Id`
- `X-AI-Gateway-Priority`
- `X-AI-Gateway-Wait-Ms`

`/status` pokazuje aktywne i oczekujące zadania bez treści promptów. Gateway nie
zapisuje promptów ani odpowiedzi do własnej bazy.
