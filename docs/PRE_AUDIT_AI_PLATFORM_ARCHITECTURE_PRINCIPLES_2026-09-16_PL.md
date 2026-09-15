# Pre-audit: założenia architektoniczne uniwersalnej platformy AI

**Status:** DRAFT / PRE-AUDIT — materiał do weryfikacji po audycie Serwera AI  
**Data:** 2026-09-16  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź robocza:** `docs/pre-audit-ai-platform-principles-20260916`  

> Ten dokument zapisuje ustalenia projektowe przed audytem istniejącego Serwera AI. Nie jest jeszcze docelowym ADR-em i nie zmienia obecnie zatwierdzonych decyzji. Po audycie należy porównać te założenia ze stanem rzeczywistym, istniejącymi ADR-ami i wdrożonym runtime, a następnie przygotować docelowe decyzje architektoniczne.

## 1. Cel nadrzędny

Serwer AI ma być rozwijany jako **uniwersalna, wielodomenowa platforma AI**, a nie jako system zbudowany pod jedno konkretne zadanie lub jedną aplikację.

Platforma ma obsługiwać wiele niezależnych domen i klientów, między innymi:

- `EcuRepairService` — przyszły system wspierający naprawę i diagnostykę ECU,
- WVC / Workshop Ventilation Controller,
- CRT / CAN Research Tool,
- przyszłe systemy i usługi, których dziś jeszcze nie znamy.

Logika domenowa musi być oddzielona od wspólnych usług platformowych.

## 2. Najważniejsza zasada: wymienialność komponentów

Żaden kluczowy komponent zewnętrzny nie może stać się nierozłączną częścią architektury.

Przykłady obecnych technologii należy traktować jako **implementacje wymienne**, a nie jako kontrakt systemu:

- Hermes — aktualna warstwa agentowa / sesyjna,
- Ollama — aktualny runtime / backend inferencji,
- Qwen — aktualny główny model LLM,
- Qdrant / pgvector — możliwe backendy wyszukiwania wektorowego,
- wybrany model embeddingowy,
- reranker,
- system kolejkowania,
- magazyn obiektowy,
- baza danych,
- framework agentowy.

Dziś dobrym rozwiązaniem może być Hermes + Ollama + Qwen, ale system ma pozwolić zastąpić każdy z tych elementów bez przebudowy całej platformy.

### 2.1. Integracja przez kontrakty, nie przez produkty

Rdzeń systemu powinien znać własne, stabilne interfejsy, np.:

- `LLMProvider`
- `AgentProvider`
- `EmbeddingProvider`
- `KnowledgeBackend`
- `RerankerProvider`
- `StorageBackend`
- `TelemetryBackend`
- `ToolProvider`

Przykład:

```text
LLMProvider
├── OllamaAdapter
├── vLLMAdapter
├── OpenAICompatibleAdapter
└── FutureProviderAdapter
```

Analogicznie:

```text
AgentProvider
├── HermesAdapter
├── CustomAgentAdapter
├── FutureAgentAdapter
└── ...
```

oraz:

```text
KnowledgeBackend
├── PgVectorBackend
├── QdrantBackend
├── HybridSearchBackend
└── ...
```

Aplikacje domenowe nie powinny wywoływać bezpośrednio API Ollamy, Qdranta czy Hermesa, jeżeli można tego uniknąć.

## 3. Stabilne kontrakty danych

Wymienialność technologii wymaga stabilnych formatów wejścia i wyjścia.

Przykład zunifikowanego wyniku wyszukiwania wiedzy:

```json
{
  "text": "...",
  "source": "...",
  "score": 0.92,
  "metadata": {}
}
```

Przykład zunifikowanej odpowiedzi LLM:

```json
{
  "content": "...",
  "tool_calls": [],
  "usage": {}
}
```

Kontrakty platformowe mają być projektowane niezależnie od konkretnego providera.

## 4. Platforma wielodomenowa

Docelowy układ logiczny powinien przypominać:

```text
                  AI PLATFORM
                       │
        ┌──────────────┼──────────────┐
        │              │              │
 EcuRepairService     WVC            CRT
        │              │              │
        └──────────────┼──────────────┘
                       ↓
                 AI Core / API
                       │
        ┌──────────────┼──────────────────┐
        │              │                  │
   LLM Service    Agent Service    Knowledge Service
        │              │                  │
        ├──────────────┼──────────────────┤
        │              │                  │
    Tool Registry   Job Queue        Data Access
        │              │                  │
        └──────────────┼──────────────────┘
                       ↓
                  Infrastructure
```

Każda domena zachowuje własną logikę, dane i ograniczenia bezpieczeństwa, korzystając jednocześnie ze wspólnej infrastruktury AI.

## 5. EcuRepairService jako domena, nie fundament platformy

Nazwa robocza przyszłego systemu wspomagającego naprawę ECU: **`EcuRepairService`**.

`EcuRepairService` ma być jednym z klientów/domen platformy, a nie powodem istnienia ani centralnym rdzeniem Serwera AI.

Przewidywany zakres domeny ECU obejmuje m.in.:

- bazę przypadków napraw,
- producenta / pojazd / maszynę / typ ECU,
- numery części, HW, SW,
- procesor / MCU,
- EEPROM / Flash,
- DTC,
- objawy,
- pomiary,
- diagnozę,
- uszkodzone elementy,
- wykonaną naprawę,
- wynik naprawy,
- zdjęcia PCB,
- punkty pomiarowe,
- dokumentację techniczną,
- datasheety,
- schematy i pinouty,
- pliki BIN / dump before / dump after,
- checksumy i metadane plików,
- analizę i porównywanie binarek,
- CAN / UDS / J1939,
- historię całej naprawy.

Przykładowa struktura sprawy:

```text
CASE-000184
├── producent
├── moduł
├── part_number
├── HW
├── SW
├── MCU
├── EEPROM
├── FLASH
├── komunikacja
├── objawy
├── DTC
├── pomiary
├── diagnoza
├── uszkodzone_elementy
├── wykonana_naprawa
├── wynik
├── zdjęcia
├── dump_before
└── dump_after
```

Długoterminowo system ECU powinien wspierać wyszukiwanie podobnych przypadków i wykorzystywać zweryfikowaną historię własnych napraw jako główne źródło wiedzy warsztatowej.

## 6. Warstwa wiedzy: RAG nie może być osobnym monolitem

RAG należy traktować jako **usługę wiedzy / `knowledge-service`**, a nie jako aplikację związaną na stałe z jednym modelem lub jednym agentem.

Przewidywane źródła i mechanizmy:

- vector search,
- keyword/full-text search (np. BM25),
- hybrid search,
- reranking,
- SQL,
- API narzędziowe,
- pliki i object storage,
- w przyszłości knowledge graph.

Zasada doboru źródła:

```text
dokumentacja / notatki / PDF    → RAG / hybrid search
ustrukturyzowane przypadki       → SQL
telemetria i pomiary             → SQL / time-series / API
aktualny stan urządzenia         → API / tools
binarki                          → dedykowany binary analyzer + metadata
relacje pomiędzy obiektami       → knowledge graph (jeżeli będzie potrzebny)
```

Nie należy wrzucać wszystkiego do vector DB tylko dlatego, że system posiada RAG.

## 7. Separacja wiedzy pomiędzy domenami

Dane wiedzy nie mogą tworzyć jednego niekontrolowanego zbioru wszystkich projektów.

Przewidywany podział logiczny:

```text
knowledge/
├── ecu-repair/
├── wvc/
├── crt/
├── pv-home/
├── ai-server/
└── shared/
```

Każde zapytanie powinno posiadać jawny zakres / namespace. Wiedza wspólna może trafiać do `shared`, ale wyszukiwanie między domenami ma być kontrolowane.

Celem jest uniknięcie sytuacji, w której np. pytanie o RS-485 w WVC zostanie zasilone przypadkową dokumentacją z ECU.

## 8. Agent nie powinien wykonywać pracy, którą może wykonać deterministyczny kod

LLM ma być używany tam, gdzie potrzebna jest interpretacja, synteza, planowanie lub rozumowanie.

Nie należy angażować dużego modelu do prostych operacji, które mogą być wykonane przez:

- router regułowy,
- SQL,
- indeks pełnotekstowy,
- parser,
- walidator,
- kod aplikacyjny.

Przykładowy prosty routing:

```text
part number / DTC / HW / SW → SQL + keyword search
pytanie opisowe             → RAG / hybrid search
telemetria                   → SQL / telemetry API
plik BIN                     → binary analyzer
procedura naprawy            → RAG
```

Agentic RAG ma być używany dla złożonych przypadków, w których potrzebne są kolejne kroki i kilka źródeł danych.

## 9. Wydajność i budżet opóźnienia

Dla zwykłego zapytania celem projektowym jest:

**narzut infrastruktury przed wywołaniem głównego LLM < 1 s** w typowym przypadku lokalnym.

Do narzutu zaliczają się m.in.:

- routing,
- embedding,
- vector search,
- full-text search,
- reranking,
- SQL,
- składanie kontekstu.

Dla złożonego trybu diagnostycznego dopuszczalne jest większe opóźnienie, jeżeli system celowo wykonuje wieloetapową analizę, np.:

```text
historia przypadków
+ dokumentacja
+ pomiary
+ log CAN
+ datasheet
+ analiza LLM
```

Należy unikać architektury, w której duży LLM musi być uruchamiany osobno przy każdym prostym kroku pośrednim.

## 10. Centralna kolejka i zarządzanie zasobami

Wspólna platforma musi posiadać centralny mechanizm admission control / scheduler / Resource Manager.

Klienci mogą jednocześnie generować zadania z wielu domen, np.:

```text
EcuRepairService → analiza diagnostyczna
WVC              → analiza stanu / alarm
CRT              → interpretacja logu CAN
Hermes           → interaktywna rozmowa
RAG              → indeksowanie w tle
```

Scheduler powinien obsługiwać:

- priorytety,
- kolejkę,
- limity współbieżności,
- routing do zasobów,
- diagnostykę stanu,
- w przyszłości wiele node'ów obliczeniowych.

Istniejący `ai-gateway` i ADR-005 są ważnym punktem odniesienia i należy je uwzględnić w audycie oraz ewentualnej ewolucji do szerszego Resource Managera.

## 11. Niezależność od sprzętu

Aktualny host Minisforum jest **bieżącą implementacją infrastruktury**, a nie założeniem architektonicznym.

Platforma ma umożliwiać przejście:

```text
single-node Minisforum
        ↓
większy pojedynczy serwer
        ↓
wiele node'ów CPU/GPU
        ↓
klaster / scheduler zasobów
```

bez przebudowy aplikacji domenowych.

Klient powinien prosić o zdolność, np.:

```text
capability = reasoning
capability = embeddings
capability = vision
capability = image-generation
```

zamiast wskazywać konkretną fizyczną maszynę lub konkretny runtime.

## 12. Model registry / capability routing — kierunek rozwojowy

W przyszłości przydatna może być centralna rejestracja modeli i możliwości:

```text
model-registry
├── reasoning-main
│   ├── provider: ...
│   ├── node: ...
│   └── capabilities: reasoning, tools
│
├── embedding-main
│   ├── provider: ...
│   └── capabilities: embeddings
│
└── vision-main
    ├── provider: ...
    └── capabilities: vision
```

Aplikacje nie powinny być powiązane z nazwą modelu typu `qwen-*`. Powinny żądać wymaganej klasy usługi / capability, a platforma wybiera backend.

## 13. Rozdział STATELESS / STATEFUL

Migracja sprzętu i skalowanie będą łatwiejsze, jeżeli od początku rozdzielimy kod od danych.

### Stateless — możliwe do łatwego przeniesienia/odtworzenia

- API,
- router,
- adaptery providerów,
- knowledge service,
- agent service,
- EcuRepairService application layer,
- WVC AI connector,
- CRT AI connector,
- narzędzia aplikacyjne.

### Stateful — wymagają ochrony, backupu i kontrolowanej migracji

- PostgreSQL,
- baza przypadków ECU,
- dokumentacja,
- zdjęcia,
- binarki,
- vector index,
- knowledge graph,
- historia napraw,
- telemetria,
- konfiguracje wymagające trwałości,
- dane użytkowe i audytowe.

Zmiana hosta obliczeniowego nie może oznaczać ręcznego odtwarzania całego stanu systemu.

## 14. Konteneryzacja i deployment

Kontenery mogą być przydatną warstwą izolacji i przenośności, ale wybór technologii deploymentu nie jest jeszcze zatwierdzony.

Kierunek ewolucji może wyglądać następująco:

```text
single host
→ Docker Compose / Podman Compose
→ multi-node
→ ewentualny orchestrator, jeśli skala go uzasadni
```

Nie należy wprowadzać Kubernetesa lub innej złożonej warstwy tylko dlatego, że może być potrzebna w przyszłości.

## 15. Kandydaci technologiczni — nie są jeszcze decyzją

Poniższe elementy są obecnie jedynie kandydatami do oceny po audycie:

- PostgreSQL jako główna baza relacyjna,
- pgvector **lub** osobny Qdrant,
- full-text/BM25 dla symboli technicznych, numerów części, DTC i oznaczeń układów,
- dedykowany reranker,
- object storage / NAS / MinIO dla zdjęć, PDF, logów i binarek,
- FastAPI lub równoważna warstwa API,
- centralny queue / Resource Manager,
- konteneryzacja usług.

Decyzja `PostgreSQL + pgvector` vs `PostgreSQL + Qdrant` ma być podjęta dopiero po audycie i analizie wymagań.

## 16. Audyt jest warunkiem rozpoczęcia większej przebudowy

Przed wdrażaniem nowej architektury należy wykonać pełny **AI Server Architecture & Runtime Audit**.

Audyt powinien objąć dwa obrazy systemu:

1. GitHub — jak system powinien wyglądać według kodu i dokumentacji,
2. działający Serwer AI — jak system faktycznie wygląda i działa.

Minimalny zakres runtime audit:

- OS / kernel,
- CPU / RAM / dyski / mounty,
- systemd services i timers,
- cron,
- procesy,
- otwarte porty,
- kontenery,
- Python venv i pakiety,
- modele Ollamy i ich lokalizacje,
- `/opt`, `/srv`, repozytoria robocze i konfiguracje w `/etc`,
- Git branch / commit / modified / untracked,
- duże i stare dane,
- logi,
- zmienne środowiskowe — tylko nazwy, bez ujawniania sekretów.

Pierwszy przebieg audytu ma być **read-only**.

Nie należy usuwać ani migrować elementów przed sporządzeniem mapy stanu rzeczywistego.

## 17. Klasyfikacja po audycie

Każdy istotny element obecnego Serwera AI powinien po audycie zostać sklasyfikowany jako:

- `KEEP`
- `MIGRATE`
- `DEPRECATE`
- `DELETE`

Dopiero po tej klasyfikacji podejmujemy działania porządkowe.

## 18. GitHub jako docelowy source of truth

Po uporządkowaniu platformy GitHub ma być docelowym źródłem prawdy dla:

- architektury,
- kodu,
- deploymentu,
- definicji usług,
- procedur operacyjnych,
- decyzji architektonicznych,
- zmian infrastrukturalnych.

Należy dążyć do sytuacji, w której na działającym serwerze nie występują nieudokumentowane „magiczne” usługi lub konfiguracje utworzone ręcznie bez odpowiednika w repo.

## 19. Dokumentowanie decyzji

Istotne decyzje należy zapisywać w repo w formie ADR lub równoważnego dokumentu.

Ten dokument jest świadomie `PRE_AUDIT` i nie powinien być od razu traktowany jako finalny ADR.

Po audycie należy:

1. porównać ustalenia z istniejącymi ADR-ami,
2. wykryć konflikty i duplikaty,
3. zatwierdzić docelowe kontrakty między usługami,
4. przygotować finalną architekturę platformy,
5. rozbić ją na małe, odwracalne etapy migracji,
6. dopiero wtedy scalać odpowiednie decyzje do `main`.

## 20. Relacja z istniejącymi decyzjami

Niniejsze ustalenia rozwijają kierunek zapisany wcześniej m.in. w:

- `ADR-003_AI_BRIDGE_PLATFORM_ARCHITECTURE_PL.md` — wspólna platforma i adaptery domenowe,
- `ADR-005_AI_GATEWAY_SCHEDULER_PL.md` — centralny gateway i scheduler priorytetowy.

Po audycie trzeba rozstrzygnąć, czy obecne pojęcie `AI Bridge` pozostaje nazwą centralnego rdzenia/platformy, czy stanie się jedną z usług wewnątrz szerszej `AI Platform`.

## 21. Zasady nadrzędne — skrót

1. **Platforma jest wielodomenowa.** `EcuRepairService`, WVC, CRT i przyszłe aplikacje są klientami wspólnej infrastruktury.
2. **Każdy istotny komponent jest wymienialny.** Hermes, Ollama, Qwen i inne produkty są implementacjami za adapterami.
3. **Sprzęt jest wymienialny.** Minisforum jest aktualnym hostem, nie częścią kontraktu architektury.
4. **Dane są ważniejsze niż compute.** Modele i serwery można wymienić; wiedza, historia i dane muszą być trwałe.
5. **Logika domenowa jest oddzielona od rdzenia platformy.**
6. **RAG jest usługą wiedzy, nie centrum całej architektury.**
7. **Nie wszystko trafia do RAG.** SQL, API, pliki, binary analyzers i w przyszłości graph mają własne role.
8. **LLM nie wykonuje pracy deterministycznej bez potrzeby.**
9. **Zwykłe zapytania mają pozostać szybkie; wieloetapowa diagnostyka może być wolniejsza.**
10. **Centralny scheduler kontroluje dostęp do wspólnych zasobów AI.**
11. **Najpierw audyt read-only, potem decyzje migracyjne.**
12. **GitHub ma być docelowym source of truth.**

---

## Następny krok

Nie wdrażać na podstawie tego dokumentu nowych usług przed audytem.

Następnym większym etapem powinien być:

**AI Server Architecture & Runtime Audit v1**

Po nim ten dokument należy zaktualizować i przekształcić w docelowy zestaw ADR-ów oraz plan migracji platformy.
