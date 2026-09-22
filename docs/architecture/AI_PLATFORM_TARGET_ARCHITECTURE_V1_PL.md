# AI Platform — Target Architecture v1

**Status:** ACTIVE / TARGET ARCHITECTURE v1 — obowiązujący desired state w `main`  
**Data bazowa:** 2026-09-19  
**Ostatnia aktualizacja:** 2026-09-22 (D.6 preparation do walidacji supervisora; brak nowej walidacji runtime)
**Repozytorium:** `autoklinika/AI-server`  
**Branch:** `main`; zmiany Stage D rozwijane przez kontrolowane feature branche  
**Podstawa:** PRE_AUDIT principles + AI Server Architecture & Runtime Audit v1.2

> Ten dokument zastępuje rolę dokumentu `PRE_AUDIT_AI_PLATFORM_ARCHITECTURE_PRINCIPLES_2026-09-16_PL.md`.  
> Nie opisuje jednego produktu ani jednego modelu. Definiuje docelową architekturę wspólnej platformy AI dla obecnych i przyszłych projektów.

---

## 1. Cel

Serwer AI rozwijamy jako **uniwersalną, wielodomenową AI Platform**, która może obsługiwać m.in.:

- `EcuRepairService`,
- WVC / Workshop Ventilation Controller,
- CRT / CAN Research Tool,
- `PV_home`,
- Telegram / Discord / roboty i przyszłe interfejsy,
- przyszłe domeny, których dziś jeszcze nie znamy.

Platforma zapewnia wspólne usługi AI, wiedzy, kolejkowania, modeli, storage, observability i bezpieczeństwa.

**Logika domenowa pozostaje poza rdzeniem platformy.**

---

## 2. Zasady nadrzędne

### 2.1. Integrujemy przez kontrakty, nie przez produkty

Hermes, Ollama, Qwen, ComfyUI, pgvector, Qdrant i inne narzędzia są implementacjami wymiennymi.

Aplikacja domenowa nie może wymagać konkretnego produktu, jeśli może wymagać stabilnej capability.

Przykład:

```text
NIE:
EcuRepairService -> Ollama -> qwen3.6:35b

TAK:
EcuRepairService -> Platform API
                 -> capability: reasoning
                 -> Model Registry
                 -> LLMProvider
                 -> OllamaAdapter -> Qwen
```

### 2.2. Dane są trwalsze niż compute

Modele, runtime i host można wymieniać. Dane użytkowe, historia, przypadki napraw, telemetria, dokumentacja i konfiguracja trwała muszą być migrowalne i backupowane.

### 2.3. GitHub jest source of truth dla kodu i desired state

Produkcja nie może zależeć od:

- nieudokumentowanych ręcznych patchy,
- dirty checkoutów,
- starych feature branchy,
- katalogów `stageXX`,
- konfiguracji znanej tylko z historii terminala.

Każdy release musi mieć jednoznaczny identyfikator commit/build.

### 2.4. Backend AI nie jest publicznym API

Klienci rozmawiają z Platform API.

Ollama, ComfyUI, embedding workers, rerankery i inne backendy powinny działać na localhost lub prywatnej sieci usług i nie być bezpośrednim interfejsem dla domen.

### 2.5. LLM nie wykonuje pracy deterministycznej bez potrzeby

SQL, parser, walidator, reguły, exact search i binary analyzer mają pierwszeństwo, kiedy rozwiązują problem bez generatywnego modelu.

### 2.6. Cleanup jest częścią Definition of Done

Globalna zasada dla wszystkich projektów:

```text
test
 -> wynik pozytywny
 -> cleanup zbędnych artefaktów
 -> kontrola git/runtime
 -> dokumentacja/commit
 -> DONE
```

Materiały diagnostyczne po nieudanym teście można zachować do czasu rozwiązania problemu; później również podlegają cleanupowi.

---

## 3. Docelowy model logiczny

```text
                         KLIENCI
        ┌──────────────────┼───────────────────┐
        │                  │                   │
 AI Control Center   Telegram/Discord    Systemy domenowe
                                            WVC / CRT /
                                      EcuRepairService / ...
        │                  │                   │
        └──────────────────┼───────────────────┘
                           v
                    +--------------+
                    | Platform API |
                    +--------------+
                           |
        ┌──────────────────┼──────────────────────┐
        v                  v                      v
 +-------------+    +---------------+      +-------------+
 | AI / Agent  |    | Knowledge     |      | Domain APIs |
 | Service     |    | Service       |      | / Adapters  |
 +-------------+    +---------------+      +-------------+
        |                  |                      |
        └──────────────┬───┴──────────────┬───────┘
                       v                  v
             +----------------+   +----------------+
             | Resource       |   | Data Access    |
             | Manager        |   | Layer          |
             +----------------+   +----------------+
                       |                  |
             +---------+---------+        |
             | Model / Worker    |        |
             | Registry          |        |
             +---------+---------+        |
                       |                  |
       ┌───────────────┼───────────────┐  |
       v               v               v  v
   LLMProvider    Embedding/       Media/      Storage
   adapters       Reranker         Vision       backends
       |               |               |          |
    Ollama/...      local/...       Comfy/...   PostgreSQL
                                               Object store
                                               Vector index
                                               Telemetry
```

---

## 4. Nazewnictwo i odpowiedzialności

### 4.1. AI Platform

To nazwa całego systemu.

### 4.2. AI Bridge

Nazwa `AI Bridge` **przestaje oznaczać całą platformę**.

Obecny AI Bridge pozostaje tymczasowo istniejącą usługą, głównie dla WVC/telemetrii, i będzie stopniowo rozdzielany na:

- Platform API / Data Access,
- adapter domenowy WVC,
- wspólne usługi platformowe.

Nie robimy jednorazowego rename całego kodu przed migracją.

### 4.3. AI Gateway

Obecny `ai-gateway` jest fundamentem przyszłego **Resource Managera**.

Nie wyrzucamy go. Ewoluuje z proxy Ollama + scheduler do warstwy admission/resource scheduling dla wszystkich kosztownych workloadów.

---

## 5. Platform API

### 5.1. Zasada

Platform API jest stabilną granicą pomiędzy klientami a implementacją.

Przykładowe namespace'y:

```text
/api/v1/ai/...
/api/v1/jobs/...
/api/v1/knowledge/...
/api/v1/models/...
/api/v1/systems/...
/api/v1/storage/...
/api/v1/health/...
```

Nie jest to jeszcze pełna lista endpointów, ale jest zatwierdzonym podziałem odpowiedzialności.

### 5.2. Wymagania kontraktowe

Każdy request platformowy powinien w miarę potrzeby przenosić:

- `request_id`,
- `domain`,
- `actor/user`,
- `capability`,
- `priority_class`,
- `context_ref`,
- opcjonalne `deadline/timeout`.

Platforma powinna zwracać:

- wynik lub identyfikator joba,
- stan kolejki,
- identyfikator providera/modelu użytego wewnętrznie,
- correlation ID,
- metryki czasowe bez ujawniania wewnętrznych sekretów.

---

## 6. Provider layer

Docelowe porty:

```text
LLMProvider
AgentProvider
EmbeddingProvider
RerankerProvider
VisionProvider
MediaGenerationProvider
KnowledgeBackend
StorageBackend
TelemetryBackend
ToolProvider
```

Implementacje:

```text
LLMProvider
├── OllamaAdapter
├── OpenAICompatibleAdapter
├── vLLMAdapter
└── FutureAdapter

AgentProvider
├── HermesAdapter
├── NativeAgentAdapter
└── FutureAdapter

MediaGenerationProvider
├── ComfyUIAdapter
└── FutureAdapter
```

Kod domenowy nie importuje klas providera konkretnego produktu.

---

## 7. Model & Capability Registry

Aplikacje żądają capability, nie nazwy modelu.

Przykład:

```yaml
capabilities:
  reasoning:
    provider: ollama-local
    model: qwen3.6:35b-hermes64k-gpu
    node: ai-node-01

  embeddings:
    provider: embedding-local
    model: TBD
    node: ai-node-01

  image-generation:
    provider: comfyui-local
    workflow: flux2-klein
    node: ai-node-01
```

Registry przechowuje m.in.:

- provider,
- model/workflow,
- node,
- capabilities,
- context/window,
- health,
- readiness,
- resource class,
- optional fallback.

Model registry **nie musi na początku być osobną bazą/usługą**. Może być kontrolowaną konfiguracją Platform Core, ale kontrakt ma pozwalać na późniejsze wydzielenie.

---

## 8. Resource Manager

### 8.1. Zakres

Resource Manager kontroluje nie tylko Ollamę, ale docelowo:

- LLM inference,
- embeddings,
- reranking,
- vision,
- image generation,
- video generation,
- inne workloady CPU/GPU/RAM.

### 8.2. Scheduler

Scheduler wspiera:

- priority classes,
- FIFO w obrębie klasy,
- concurrency limits,
- leases,
- queue status,
- admission control,
- per-capability/node routing,
- timeout/TTL,
- graceful failure,
- przyszłe multi-node.

Obecny `ai-gateway` i Resource Lease Registry są bazą implementacyjną.

### 8.3. Priorytety

Nie kodujemy nazw domen w schedulerze jako architektonicznego kontraktu.

Docelowe klasy semantyczne:

```text
infrastructure   = 10
interactive-high = 25
interactive      = 50
normal           = 100
background       = 200
maintenance      = 300
```

Domena mapuje własny request na klasę. W D.1 `infrastructure` jest kanoniczną
najwyższą klasą; historyczne `critical` jest wyłącznie aliasem tej klasy (10).
Niższa liczba oznacza wyższy priorytet. Scheduler zachowuje FIFO dla równego
efektywnego priorytetu, również przy mieszaniu klas i legacy liczb, bez preemption.

D.1 przyjmuje opcjonalne pole JSON `priority_class` na istniejących scheduled
endpointach Gateway i przy tworzeniu external lease. Nie dodaje nagłówka HTTP.
Jawny `X-AI-Priority` zachowuje dokładną wartość i ma pierwszeństwo przed klasą;
legacy lease `priority` ma analogiczne pierwszeństwo. Brak obu pól zachowuje
konfigurowalne defaulty istniejących endpointów. Szczegóły walidacji i granicy
providerów: [Component Contracts, §7.1](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#71-semantic-priority-contract--stage-d1).

D.1 nie wdraża JobState (D.2), descriptors/routingu (D.3), unified admission
(D.4), migracji klientów (D.5) ani walidacji produkcyjnej Stage D (D.6).

WVC może nadal mapować cykliczną analizę na wysoki priorytet, ale Resource Manager nie musi znać słowa `ventilation`.

### 8.4. Job model D.2 — implementacja do walidacji supervisora

Scheduler zachowuje ordering i leases, a obok legacy status publikuje JobState
bez request content: stabilne UUID request/job, domain/capability/class, lifecycle,
UTC timestamps i assignment istniejącego upstreamu. Terminalna historia jest
ograniczona do 128 rekordów w RAM. Rezerwacja external lease nie udaje joba
wykonania providera. Szczegóły i przejścia: [Component Contracts §7.2](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#72-job-model--stage-d2).
D.3 dodaje registry opisany poniżej; D.4 rozszerzenie admission opisuje §8.6.

### 8.5. Descriptors D.3 — implementacja do walidacji supervisora

Niemutowalny `DescriptorRegistry` zawiera wersjonowane statyczne descriptors
capability/provider/node. Pierwsze wpisy to `ollama-local`, `comfyui-local`,
`hermes-local` na jednym `Settings.node_id`. `/status.registry` publikuje wyłącznie
configured inventory, bez twierdzeń o live readiness. Domyślna konfiguracja jest
w pakiecie; opcjonalne JSON `AI_BRIDGE_GATEWAY_REGISTRY` musi zachować bieżące
single-node bindings. Kontrakt danych pozwala opisać kilka node'ów, ale Gateway D.3
odrzuca taką konfigurację. Nie ma discovery, failover, routingu ani zmian modeli.
Assignment zwykłego HTTP jest walidowany względem registry przy `running`;
external lease nadal ma assignment null. Szczegóły:
[Component Contracts §8.1](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#81-static-descriptors--stage-d3).


### 8.6. Unified admission D.4 — do walidacji supervisora

LLM scheduled HTTP, media external leases i istniejące embeddings routes używają
jednego schedulera oraz descriptor-validated workload bindings w JobState.
Reservation lifecycle, semantic priority, FIFO/limits, cancellation i TTL pozostają
zachowane. Deklaracja workload nie oznacza provider readiness ani sukcesu media.
Leased HTTP i external-use guard nie pozwalają równolegle wykonywać dwóch faz
pod jednym ticketem; wspólny lease nadal obejmuje Qwen, a następnie ComfyUI.
Supported media adapter/wrapper odmawia expensive execution bez aktywnego lease.
Future EmbeddingProvider ma obowiązek użyć tej samej granicy admission; brak
konkretnego adaptera/modelu, Knowledge Service i multi-node execution w D.4.

Nie wykonano production validation/cutover. Compatibility endpointy pozostają;
Migrację D.5 opisuje §8.7; D.6 walidacja pozostaje osobnym krokiem. Kontrakt operacyjny i ograniczenia
cleanup: [Component Contracts §7.3](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#73-unified-admission--stage-d4).
[Raport D.4](../reports/AI_PLATFORM_STAGE_D4_UNIFIED_ADMISSION_2026-09-22_PL.md).

### 8.7. Compatibility migration D.5 — do walidacji supervisora

Istniejące endpointy Gateway pozostają granicą klientów podczas migracji.
WVC przechodzi z generic chat na istniejący namespace ventilation, zachowując
numeric priority override, model, schema i jawny direct-Ollama recovery mode.
Repo helper adaptuje znane callery telegram-chat/discord-chat do workload llm,
bez nowego patcha Hermesa. Nieznany legacy caller nadal używa external, jawny
workload ma pierwszeństwo. Kolejka, identyfikacja rozmów i WAIT/START bez zmian.
Media prompt compilers odrzucają direct backend URL: wymagany loopback :11435.
D.4 media guards i wspólny lease Qwen -> ComfyUI pozostają.

Nie wykonano cutover ani D.6. Kontrakt i recovery inventory:
[Component Contracts §7.4](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#74-compatibility-migration--stage-d5).
[Raport D.5](../reports/AI_PLATFORM_STAGE_D5_COMPATIBILITY_MIGRATION_2026-09-22_PL.md).

---


## 9. Agent Service

Agent Service odpowiada za:

- sesję/rozmowę,
- tool loop,
- jawny kontekst domenowy,
- delegowanie do Knowledge Service i Tool Registry,
- komunikację z LLMProvider przez Resource Manager.

Hermes jest obecnie implementacją AgentProvider, ale nie może być patchowany w miejscu jako trwały mechanizm integracji.

Docelowo:

```text
Telegram/Discord
     |
Messaging Adapter
     |
Platform Agent API
     |
AgentProvider -> HermesAdapter / FutureAdapter
```

Patch-in-place produkcyjnego Hermesa jest oznaczony jako **DEPRECATED** i musi zniknąć etapowo.

---

## 10. Knowledge Service

Knowledge Service jest wspólną usługą platformową, ale nie zastępuje wszystkich baz.

Źródła:

- PostgreSQL,
- full-text/BM25,
- vector search,
- reranker,
- pliki/PDF,
- GitHub/project docs,
- object storage,
- przyszły graph,
- narzędzia domenowe/API.

Namespaces:

```text
ecu-repair
wvc
crt
pv-home
ai-server
shared
```

Każde zapytanie ma jawny zakres domenowy.

### 10.1. Routing danych

```text
exact part number / DTC       -> SQL + exact/full-text
dokumentacja                  -> hybrid retrieval
telemetria                    -> SQL/time-series
stan urządzenia               -> live API/tool
BIN/EEPROM/FLASH              -> binary analyzer + metadata
relacje                        -> graph, jeśli uzasadniony
opisowe pytanie                -> RAG/hybrid + LLM
```

### 10.2. Wybór vector backendu

Na v1 **nie zatwierdzamy jeszcze** pgvector vs Qdrant.

Kontrakt `KnowledgeBackend` musi pozwolić na obie implementacje.

---

## 11. Domain layer

### 11.1. WVC

WVC zachowuje autonomiczne sterowanie i safety.

AI:
- odbiera dane,
- analizuje,
- raportuje,
- rekomenduje.

AI **nie steruje wentylacją**.

Jeżeli brak świeżej telemetrii, analiza cykliczna ma kończyć się deterministycznym:

`skipped / no_fresh_data`

bez uruchamiania kosztownej inferencji.

Historyczna telemetria pozostaje centralnie przechowywana zgodnie z ADR-004.

### 11.2. CRT

CRT pozostaje właścicielem logiki CAN/UDS/J1939.

Platforma dostarcza AI, knowledge, jobs, storage i analysis capabilities.

### 11.3. EcuRepairService

EcuRepairService jest domeną wysokiego poziomu, która łączy:

- repair cases,
- identyfikację ECU,
- DTC,
- pomiary,
- zdjęcia PCB,
- dokumentację,
- binarki,
- CAN/UDS/J1939,
- diagnozę,
- historię napraw.

Nie wprowadzamy danych ECU do wspólnego namespace bez jawnej decyzji.

---

## 12. Data architecture

### 12.1. Klasy danych

```text
STATEFUL / BACKUP-CRITICAL
- PostgreSQL
- repair cases
- telemetry history
- documents
- photos
- binaries
- user data
- platform/domain configuration requiring persistence
- audit records

REGENERABLE
- model files
- vector indexes if source data exists
- caches
- thumbnails
- derived artifacts

EPHEMERAL
- temp
- test outputs
- worktrees
- scratch
- transient job files
```

### 12.2. Docelowy layout logiczny

```text
/srv/ai-data/
├── platform/
│   ├── jobs/
│   ├── audit/
│   └── object-store/
├── domains/
│   ├── wvc/
│   ├── crt/
│   ├── ecu-repair/
│   └── pv-home/
├── providers/
│   ├── hermes/
│   └── comfyui/
└── cache/
    ├── models/
    └── derived/
```

To jest model logiczny; fizyczna migracja istniejących katalogów nastąpi dopiero w odpowiednim etapie.

### 12.3. Retention

Każda klasa job/output musi mieć:

- owner/domain,
- created_at,
- retention class,
- delete_after lub policy,
- możliwość zachowania jako trwały artefakt.

Nie utrzymujemy bezterminowo katalogów jobów tylko dlatego, że kiedyś powstały.

---

## 13. Deployment architecture

### 13.1. Wymaganie

Produkcja musi być reprodukowalna z GitHub + secrets/backup danych.

### 13.2. Release model

Każdy deploy ma posiadać:

- git SHA,
- build/release ID,
- config schema version,
- migration version,
- provider/model configuration version.

Rekomendowany pierwszy etap bez zmiany całej technologii:

```text
/opt/ai-platform/releases/<release-id>/
                         |
                         +-- platform services
                         +-- package metadata

/opt/ai-platform/current -> releases/<release-id>
/etc/ai-platform/         -> desired config / env refs
/srv/ai-data/             -> persistent state
```

Rollback = przełączenie na poprzedni zwalidowany release + kompatybilna migracja danych.

### 13.3. Systemd vs containers

Na pierwszym etapie **nie wymagamy Kubernetesa**.

Preferujemy minimalny krok:
- wersjonowane release artifacts,
- systemd lub Compose jako mechanizm uruchomieniowy,
- kontrakty niezależne od mechanizmu.

Konteneryzacja jest dopuszczalna i prawdopodobnie użyteczna dla nowych stateless services, ale nie jest warunkiem rozpoczęcia migracji.

---

## 14. Security architecture

Stan po Stage B, potwierdzony po Stage C: Ollama, ComfyUI i AI Gateway są localhost-only, AI Bridge pozostaje wymaganym API LAN, a host firewall działa deny-by-default.

Docelowe zasady:

1. **deny by default** na hoście,
2. Tailscale jako preferowany kanał administracyjny,
3. SSH tylko dla administracji,
4. Ollama/ComfyUI/backendy providerów — localhost/private service network,
5. Platform API — tylko wymagane interfejsy,
6. authN/authZ przed udostępnieniem GUI i domen,
7. service-to-service identity dla komunikacji między node'ami,
8. secrets poza Git,
9. least privilege dla użytkowników usług,
10. audyt operacji administracyjnych i wrażliwych.

Nie zakładamy, że „LAN = trusted forever”.

---

## 15. Observability

Minimalny wspólny standard:

- structured logs,
- request/job correlation ID,
- health/readiness,
- queue state,
- provider/model/node used,
- request latency,
- queue wait time,
- error classification,
- resource utilization,
- storage/job retention metrics.

Platform API i GUI mają umożliwiać widok:

```text
request -> job -> resource lease -> provider -> model/node -> result
```

bez przechowywania w logach niepotrzebnej treści promptów/sekretów.

---

## 16. AI Control Center

Docelowo jedno WebGUI dla platformy.

```text
AI CONTROL CENTER
├── Overview
├── AI / Assistant
├── Knowledge
├── Jobs
├── Systems
│   ├── EcuRepairService
│   ├── WVC
│   ├── CRT
│   └── future modules
├── Models / Compute
├── Storage
├── Logs / Observability
└── Settings
```

GUI rozmawia wyłącznie ze stabilnym Platform API.

Globalny asystent dostaje jawny context envelope, np.:

```json
{
  "domain": "ecu-repair",
  "case_id": "CASE-000184",
  "current_view": "measurements"
}
```

Agent nie zgaduje stanu GUI.

---

## 17. Performance targets

Dla zwykłego requestu lokalnego:

**narzut platformy przed główną inferencją: typowo < 1 s**

Obejmuje:
- routing,
- auth,
- queue admission,
- embeddings,
- retrieval,
- rerank,
- SQL,
- context assembly.

Złożone diagnostyki agentowe mogą trwać dłużej, ale liczba pełnych wywołań LLM ma być ograniczana przez deterministyczne kroki.

---

## 18. Multi-node readiness

V1 może działać na jednym Minisforum.

Kontrakty muszą jednak pozwalać na:

```text
ai-node-01: reasoning + embeddings
gpu-node-02: vision + image/video
storage-node: object storage / DB
```

Aplikacja domenowa nie wskazuje hostname/IP node'a.

Resource Manager + Registry wybierają zasób.

---

## 19. Backup & Disaster Recovery

Przed migracją wymagany jest formalny DR plan.

Backup-critical:

- PostgreSQL,
- domain data,
- Hermes/user state do czasu migracji,
- object storage,
- dokumentacja i binarki,
- secrets/config references.

Regenerowalne:

- model cache,
- vector indexes,
- build artifacts.

Każdy backup musi mieć procedurę **restore test**, nie tylko procedurę wykonania kopii.

---

## 20. Elementy obecnego runtime — decyzje

| Element | Target decision |
|---|---|
| Minisforum | KEEP jako `ai-node-01` |
| PostgreSQL | KEEP |
| AI Bridge | MIGRATE / rozdzielić role |
| AI Gateway | KEEP / EVOLVE do Resource Manager |
| Ollama | KEEP jako pierwszy LLMProvider adapter |
| Qwen | KEEP jako bieżący model, nie kontrakt |
| Hermes | KEEP tymczasowo / adapter; patch-in-place DEPRECATE |
| ComfyUI | KEEP jako MediaGenerationProvider adapter |
| Tailscale | KEEP dla administration plane |
| Docker | opcjonalny mechanizm deploymentu; nie architektura |
| stare worktree/stage/backup | DELETE/ARCHIVE po migracji i verified backup |
| direct backend LAN exposure | DELETE poprzez hardening |
| branch-pinned installers | DEPRECATE |
| dirty production checkout | DEPRECATE |
| release bez build stamp | DEPRECATE |

---

## 21. Definition of Done dla zmian platformy

Etap migracyjny jest zakończony dopiero, gdy:

1. testy automatyczne PASS,
2. smoke/E2E PASS,
3. health/readiness PASS,
4. rollback jest zweryfikowany lub jawnie opisany,
5. repo dokumentuje nowy stan,
6. produkcja ma release/build ID,
7. brak nieplanowanego dirty state,
8. zbędne artefakty testowe/worktree/backupy zostały usunięte,
9. `git status` i inventory runtime są czyste/oczekiwane,
10. decyzje architektoniczne zostały zapisane.

---

## 22. Decyzje świadomie odłożone

Nie zatwierdzamy jeszcze:

- pgvector vs Qdrant,
- konkretnego embedding modelu,
- konkretnego rerankera,
- React/Next.js vs alternatywy GUI,
- Docker Compose vs Podman Compose jako finalnego mechanizmu,
- orchestratora multi-node,
- graph DB.

Te wybory mają być podejmowane przez osobne ADR-y wtedy, gdy są potrzebne.

---

## 23. Relacja do istniejących ADR

### ADR-003

Kierunek „wspólna platforma + adaptery domenowe” pozostaje ważny.

Zmiana: nazwa `AI Bridge` nie będzie już nazwą całej platformy; przechodzimy do szerszego pojęcia `AI Platform`.

### ADR-004

Pozostaje obowiązujący dla retencji WVC. Audyt potwierdził, że centralna historia istnieje.

### ADR-005 AI Gateway

Pozostaje obowiązującym fundamentem schedulera, ale jego zakres ewoluuje do Resource Managera obejmującego inne capability niż Ollama.

### Kolizja ADR-005

Istniejące podwójne użycie numeru ADR-005 musi zostać uporządkowane przy porządkowaniu indeksu ADR; nie zmieniamy historycznych nazw bez kontrolowanej migracji odnośników.

---

## 24. Architektura po pierwszej migracji

Minimalny cel pierwszej generacji po przebudowie:

```text
Clients
  |
Platform API
  |
  +-- Agent Service -> HermesAdapter
  +-- WVC Domain Adapter
  +-- Job API
  +-- Resource Manager
          |
          +-- OllamaAdapter -> Qwen
          +-- ComfyUIAdapter -> image/video

Data
  +-- PostgreSQL
  +-- /srv/ai-data structured persistent storage

Operations
  +-- release/build stamp
  +-- desired-state deployment
  +-- deny-by-default firewall
  +-- health/observability
```

Knowledge Service i AI Control Center mogą zostać dołożone następnie bez przebudowy powyższych kontraktów.

---

## 25. Kryterium sukcesu architektury

Architektura jest poprawna, jeżeli możemy:

- wymienić Qwen bez zmiany WVC/CRT/EcuRepairService,
- wymienić Ollamę bez zmiany domen,
- wymienić Hermesa bez zmiany Platform API,
- przenieść inference na drugi node bez zmiany klientów,
- dodać nową domenę bez kopiowania całej infrastruktury AI,
- odtworzyć produkcję z GitHub + backupów,
- usunąć testowy eksperyment bez pozostawienia artefaktów,
- zobaczyć kto/co używa zasobów,
- zabezpieczyć backendy bez łamania klientów.

To jest nadrzędny test każdej kolejnej decyzji technicznej.

## 26. D.6 preparation — stan 2026-09-22

Bieżący kompletny kandydat Resource Manager v2 ma release metadata D.6,
config schema 3 i migration_version=resource-manager-v2, zgodnie z decyzją
supervisora. Umbrella Resource Manager contract=2; podkontrakty D.1–D.5=1;
provider contracts bez zmian. To nie jest wersja Platform API (Stage E).
[Dokładny kontrakt](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#20-release-contract-resource-manager-v2--decyzja-supervisora-2026-09-22).

Status: **READY FOR PRODUCTION VALIDATION — implementation ready for supervisor
validation**. Produkcja nie została zmieniona ani zwalidowana przez przygotowanie.
Historyczny runtime D.0 i rollback Stage C pozostają zachowane. Local coverage,
readiness tooling i przyszły plan WVC/multiuser/media/rollback opisuje
[raport D.6](../reports/AI_PLATFORM_STAGE_D6_PREPARATION_2026-09-22_PL.md).


### Korekta production gate D.6 — 2026-09-22

D6GATEFIX dodaje wersjonowane apply/restore dokładnie pięciu aktywnych klientów
z realnego inventory. Oryginalny snapshot pozostaje niemutowalny; legacy generatory
libexec pozostają do Stage H. Restore bytes/hash/stat i r1/r2 semantics określa
[Component Contracts §20.1](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#201-d6-matched-client-transition--decyzja-supervisora-2026-09-22).

Rollback przywraca old clients i restartuje Hermesa jeszcze pod D.6 Gateway,
a dopiero potem przełącza release na D.0. Re-activation przełącza najpierw release
na D.6, potem klientów. Celowy restart Hermesa przeładowuje cached helper;
nowy PID baseline obowiązuje w kolejnej fazie smoke, ComfyUI pozostaje bez restartu.
Status: **implementation ready for supervisor validation**, production NOT RUN.
[Raport korekty](../reports/AI_PLATFORM_STAGE_D6_GATE_FIX_2026-09-22_PL.md).
Stage E i dalsze etapy nie zostały rozpoczęte.

## 27. Stage E — addytywny kandydat Platform API

Platform API v1 jest montowane pod `/api/v1` na istniejącym prywatnym Gateway.
Współdzieli scheduler/leases D.6 zamiast tworzyć drugi resource pool. Klient używa
capability i logical model; async execution port izoluje wire protocol providera.
Auth jest oddzielną polityką service-wide (token albo loopback), a context actor
nie jest dowodem tożsamości. Health nie publikuje backend URL, modeli fizycznych,
promptów, tool output ani sekretów. Nie dodano nowego listenera ani ekspozycji LAN.

Legacy WVC/Hermes/media ścieżki i matched D.6 clients pozostają, podobnie jak D.0/D.6
recovery evidence. Produkcyjny rollback target: verified D.6 r2. Zakres, wersje,
ograniczenia i komplet supervisor scripts: [Stage E](../../deploy/stage-e/README.md).
Status: kandydat do independent review; production validation nie była wykonywana
przez implementera.
