# AI Platform — Migration Plan v1

**Status:** POST-AUDIT MIGRATION PLAN v1  
**Data:** 2026-09-19  
**Cel:** przejście z obecnego działającego Serwera AI do Target Architecture v1 bez utraty danych i bez jednorazowego „big bang”.

---

## 1. Zasady migracji

1. Produkcja ma pozostać działająca przez cały proces poza kontrolowanymi oknami serwisowymi.
2. Każdy etap musi być mały, mierzalny i odwracalny.
3. Nie zmieniamy jednocześnie wszystkich providerów, storage, agenta i schedulera.
4. Dane stateful są chronione przed refaktoryzacją stateless services.
5. Każdy etap kończy się testem, cleanupem i dokumentacją.
6. Stare artefakty usuwamy dopiero po potwierdzonym rollback point.
7. GitHub ma reprezentować desired state przed przejściem do kolejnego etapu.

---

## 2. Stan bieżący po walidacji D.0

Stan zwalidowany 2026-09-21:

- Stage A: recovery baseline i release model działają; produkcja używa `/opt/ai-platform/releases` + atomowego `/opt/ai-platform/current`;
- Stage B: Ollama, ComfyUI i AI Gateway są localhost-only; host firewall działa deny-by-default;
- Stage C: provider abstraction działa (`LLMProvider`, `AgentProvider`, `MediaGenerationProvider`, `EmbeddingProvider`, `KnowledgeBackend`);
- D.0 Foundation Cleanup przeszedł pełny production cutover, real smoke/E2E oraz rollback validation;
- aktywny runtime to `stage-d0-foundation-20260921-r2`, source `3496f21249474d16c09a791db39afd321beb935c`;
- zweryfikowany rollback point to `stage-c-provider-abstraction-20260921-r3`;
- canonical systemd używa `/opt/ai-platform/current/services/...`; historyczne production-source/analysis override’y zostały usunięte;
- WVC analysis domyślnie używa AI Gateway; podczas walidacji CM5/WVC był fizycznie odłączony, więc brak świeżej telemetrii był stanem oczekiwanym;
- realny request `ventilation` przez Resource Manager -> Qwen z priority 10: PASS;
- realny Stage30 media render pod external lease priority 50: PASS;
- Telegram `/wideo`: PASS;
- pełny rollback D.0 r2 -> Stage C r3 -> D.0 r2: PASS;
- Resource Manager v1 (`PriorityScheduler` + `ResourceLeaseRegistry`) pozostaje fundamentem Stage D;
- znanym długiem pozostaje Hermes patch-in-place; Stage D nie może go powiększać;
- `main` jest chroniony aktywnym rulesetem `main-protection`; wymagany jest `platform-ci` i aktualność gałęzi przed merge.

---

## 3. Etap 0 — Freeze i recovery baseline

### Cel

Zabezpieczyć stan, który można odtworzyć przed pierwszą zmianą architektury.

### Działania

- zrobić pełny backup PostgreSQL,
- zrobić backup trwałego `/srv/ai-data` wymagającego ochrony,
- zachować Hermes config/state wymagane do odtworzenia,
- przechwycić pełny diff dirty Hermesa,
- zapisać listę aktywnych systemd units/drop-ins,
- zapisać model list/versions,
- zapisać dokładne SHA obecnych repo i wdrożeń,
- przetestować restore co najmniej krytycznej bazy/config.

### Exit criteria

- istnieje udokumentowany recovery point,
- restore PostgreSQL został zweryfikowany,
- patch Hermesa można odtworzyć,
- nie ma nieznanych krytycznych plików.

### Rollback

Nie dotyczy — to etap zabezpieczający.

---

## 4. Etap 1 — Source of truth i release model

### Cel

Przestać wdrażać produkcję jako historyczny working tree + kolejne patche.

### Działania

1. Wprowadzić release manifest:
   - git SHA,
   - release ID,
   - config schema,
   - migration version.
2. Przygotować wersjonowany layout `/opt/ai-platform/releases`.
3. Zbudować pierwszy reprodukowalny release obecnej funkcjonalności bez zmian zachowania.
4. Wprowadzić `current` symlink lub równoważny atomowy mechanizm aktywacji.
5. Ujednolicić systemd units tak, aby wskazywały release, nie repo robocze.
6. Usunąć zależność installerów od historycznych feature branchy.

### Exit criteria

- produkcja ma widoczny release ID,
- ten sam release można odtworzyć z GitHub,
- working checkout nie jest wymagany do działania runtime,
- rollback do poprzedniego release działa.

### Rollback

Przełączenie `current` na poprzedni release i restart wyłącznie migrowanych usług.

---

## 5. Etap 2 — Security hardening bez zmiany funkcji

### Cel

Zamknąć backendy i wprowadzić jawny network policy.

### Działania

- Ollama bind do localhost/private network,
- ComfyUI bind do localhost/private network,
- pozostawić Gateway lokalny,
- ustalić, które endpointy Platform/AI Bridge muszą być osiągalne z LAN,
- włączyć host firewall deny-by-default,
- jawnie dopuścić:
  - Tailscale/admin,
  - SSH według polityki,
  - wymagane API domenowe,
- zweryfikować, że klienci nie omijają Resource Managera.

### Exit criteria

- backend inference nie jest bezpośrednio dostępny z LAN,
- WVC/API potrzebne domenom nadal działają,
- Tailscale/SSH administracja działa,
- smoke test Telegram/Discord/media PASS.

### Rollback

Przywrócenie poprzednich bind/firewall rules z backupu konfiguracji.

---

## 6. Etap 3 — Provider abstraction

### Cel

Oddzielić platformę od Ollamy, Qwena, Hermesa i ComfyUI.

### Działania

Wprowadzić porty:

- `LLMProvider`,
- `AgentProvider`,
- `MediaGenerationProvider`,
- `EmbeddingProvider`,
- `KnowledgeBackend`.

Pierwsze adaptery zachowują obecną funkcjonalność:

- OllamaAdapter,
- HermesAdapter,
- ComfyUIAdapter.

### Zasada

Na tym etapie **nie zmieniamy jeszcze produktów**. Zmieniamy tylko granicę integracyjną.

### Exit criteria

- istnieją contract tests,
- domena WVC nie importuje bezpośrednio Ollama clienta,
- media nie wymagają bezpośredniej wiedzy klienta o ComfyUI,
- obecny Qwen daje te same wyniki operacyjne przez adapter.

### Rollback

Feature flag / poprzedni release.

---

## 7. Etap 4 — Resource Manager v2

### Cel

Rozszerzyć obecny AI Gateway z Ollama scheduler do wspólnego admission/resource managera.

### Działania

- zmienić priorytety z nazw domen na semantic classes,
- zunifikować leases dla LLM/media/embedding,
- dodać provider/node descriptors,
- dodać capability routing,
- zachować WAIT/START UX,
- zachować compatibility endpoints podczas migracji.

### Exit criteria

- chat, WVC analysis i media korzystają z jednego Resource Managera,
- żaden kosztowny backend nie omija admission control,
- status pokazuje workload bez prompt content,
- obecny priority behavior jest zachowany.

### Rollback

Compatibility mode starego Gatewaya.

---

## 8. Etap 5 — Platform API

### Cel

Wprowadzić stabilną granicę dla wszystkich klientów.

### Zakres v1

Minimum:

```text
/api/v1/ai
/api/v1/jobs
/api/v1/models
/api/v1/systems
/api/v1/health
```

Knowledge API może być dodane w kolejnym etapie.

### Działania

- request/context envelope,
- correlation IDs,
- normalizowane errors,
- job state model,
- health aggregation,
- auth hooks nawet jeśli pierwsza polityka jest prosta.

### Exit criteria

- nowy klient nie potrzebuje URL Ollamy/Hermesa/ComfyUI,
- provider może być zmieniony za Platform API,
- versioning contract jest testowane.

---

## 9. Etap 6 — Hermes bez patch-in-place

### Cel

Usunąć największy obecny dług runtime.

### Działania

1. zachować pełny patch obecnej produkcji,
2. zidentyfikować funkcje patchy:
   - global queue,
   - WAIT/START,
   - Discord/Telegram context,
   - media dispatch,
3. przenieść logikę możliwą do Platform Adapter/Messaging Adapter,
4. ograniczyć patch Hermesa do zera lub minimalnego upstream-supported extension point,
5. uruchomić czysty pin wersji Hermesa.

### Exit criteria

- `git status` Hermesa clean,
- exact version/commit w registry/release manifest,
- Telegram multiuser PASS,
- Discord PASS,
- media PASS,
- queue WAIT/START PASS.

### Rollback

Poprzedni release + zachowany patch snapshot.

---

## 10. Etap 7 — WVC jako prawdziwa domena

### Cel

Oddzielić logikę wentylacji od Platform Core.

### Działania

- utworzyć WVC domain package/adapter,
- zachować istniejące telemetry API podczas migracji,
- wydzielić WVC analysis policy,
- wprowadzić freshness gate,
- gdy brak nowych danych:
  `skipped/no_fresh_data`,
- po ponownym podłączeniu WVC zweryfikować wznowienie ingestu i brak duplikacji.

### Exit criteria

- AI Platform nie zna szczegółów SEN55/fan logic w core,
- WVC jest jednym z wielu domain adapters,
- centralna historia zostaje zachowana,
- AI nadal advisory-only.

---

## 11. Etap 8 — Cleanup legacy

### Warunek

Etap można wykonać dopiero po przejściu przez stabilny release i verified rollback.

### Cleanup obejmuje

- stare worktree,
- test directories,
- `local-leftovers`,
- stare `pre-stage` deploymenty,
- obsolete Hermes stage backups,
- stage-specific helper duplicates,
- branch-pinned installers,
- stare modele, jeśli niepotrzebne,
- nieużywane CI paths.

### Każde usunięcie wymaga

- potwierdzenia braku aktywnej referencji,
- backupu jeśli artefakt był rollbackiem,
- kontroli `git worktree list`,
- kontroli systemd/runtime.

### Exit criteria

- brak zbędnych stageXX w produkcyjnym runtime,
- brak osieroconych worktree,
- repo ma wyłącznie narzędzia utrzymywane długoterminowo,
- storage ma politykę retention.

---

## 12. Etap 9 — Knowledge Service

### Cel

Dodać wspólną warstwę wiedzy bez wiązania jej z jednym RAG backendem.

### Działania

- Knowledge API,
- namespaces,
- full-text/exact search,
- embeddings,
- hybrid retrieval,
- reranker,
- source attribution,
- domain filtering.

### Pierwsza decyzja implementacyjna

Qdrant jest pierwszym backendem retrieval, wdrażanym wyłącznie za neutralnym `KnowledgeBackend`.
Backend pozostaje wymienny, a indeks nie jest source of truth. Decyzję i zasady migracji dokumentuje
[ADR-001](adr/ADR-001_STAGE_J_REPLACEABLE_QDRANT_BACKEND_2026-09-23_PL.md).

### Stage J2 — embedding/chunking gate

Benchmark na rzeczywistym korpusie ECU/WVC wybrał BGE-M3 (1024 dimensions) jako
pierwszy profil embeddingowy oraz heading/paragraph-aware chunking do około 2400
znaków. Przy 13 pytaniach dense-only osiągnięto Recall@3=100% i MRR=0.962;
BGE zachował jakość Qwen3 Embedding 0.6B/4B przy najmniejszym runtime footprint.
Wynik nie zamraża modelu na stałe — canonical Source/Document/Version/Chunk pozostaje
niezależny od embeddingu i pozwala na pełny reindex. Szczegóły i evidence:
[Stage J2 report](../reports/AI_PLATFORM_STAGE_J2_KNOWLEDGE_EMBEDDING_BASELINE_2026-09-23_PL.md).

### Stage J3 — canonical persistence / ingestion / hybrid

J3 dodaje additive Alembic migration po `0002`, trwałe tabele canonical knowledge,
content-addressed immutable object store, idempotentny Markdown ingestion oraz
retryable/supersedable index jobs. Qdrant pozostaje odbudowywalną projekcją.

Pierwszy worker jest single-host/single-run i korzysta z BGE-M3 przez istniejący
Gateway/Resource Manager. Produkcyjna kolekcja jest wersjonowana nazwą profilu.
Exact/keyword czyta tylko bieżące canonical chunks; `hybrid/auto` łączy lexical i
dense przez reciprocal-rank fusion, nadal pod logicznym `knowledge-primary`.

Rollback aplikacji nie wymaga usuwania tabel J3. Po pojawieniu się kanonicznych
danych produkcyjnych schema downgrade do `0002` jest operacją destrukcyjną i nie
jest zwykłym rollbackiem release.

Szczegóły decyzji J3:
[ADR-003](adr/ADR-003_STAGE_J3_CANONICAL_INGESTION_REINDEX_2026-09-23_PL.md).

Następny gate po J3: PDF parser/OCR, learned sparse/reranking oraz publiczne API
`Szukaj` / `Zapytaj AI`.

Nie rozpoczynać od knowledge graph, jeśli nie ma konkretnego wymagania.

---

## 13. Etap 10 — EcuRepairService i CRT

Po stabilizacji core:

### EcuRepairService

- case model,
- object storage,
- repair history,
- binary analyzer,
- knowledge namespace,
- AI diagnosis workflow.

### CRT

- CAN sessions,
- UDS/J1939 tools,
- captures,
- knowledge,
- AI analysis.

Domeny korzystają z gotowych Platform API/Provider contracts.

---

## 14. Etap 11 — AI Control Center

GUI dopiero wtedy, gdy Platform API jest stabilne.

Pierwsza wersja:

- Overview,
- Assistant,
- Jobs,
- Models/Compute,
- Systems,
- Knowledge,
- Health/Logs.

Przed zamrożeniem `Models/Compute` należy wykonać gate gotowości na zewnętrzny
akcelerator/GPU: per-device descriptors, resource pools, routing, residency,
health/recovery i współistnienie obecnego iGPU/UMA z dodatkową kartą. Jeśli karta
zostanie zamontowana wcześniej, ten gate przesuwa się przed jej wdrożeniem.

Nie tworzyć bezpośrednich integracji GUI z Ollama/Hermes/ComfyUI.

---

## 15. Backup/DR jako warunek produkcji

Przed oznaczeniem platformy jako v1 production-ready:

- automatyczny backup DB,
- backup object/domain data,
- config/secrets recovery procedure,
- restore test,
- release rollback,
- dokument RPO/RTO.

---

## 16. CI/CD migration

Obecny stage-oriented workflow zastąpić docelowo:

```text
lint
unit tests
contract tests
migration tests
security/static checks
build release artifact
smoke tests
deployment validation
```

Push/PR ma być związany ze stabilnymi komponentami, nie historycznymi nazwami stage.

---

## 17. Kolejność priorytetowa

### P1 — przed większą rozbudową

1. recovery baseline,
2. source of truth/release model,
3. security hardening,
4. provider abstraction,
5. Resource Manager v2,
6. Platform API,
7. Hermes clean integration.

### P2 — zaraz potem

8. WVC domain separation,
9. legacy cleanup,
10. observability,
11. Knowledge Service,
12. DR automation.

### P3 — rozwój funkcjonalny

13. EcuRepairService,
14. CRT deeper integration,
15. heterogeneous accelerator / external GPU readiness gate,
16. AI Control Center,
17. multi-node expansion.

---

## 18. Zakazane skróty

Podczas migracji nie wolno:

- robić resetu dirty Hermesa bez capture diff,
- kasować stage backups przed nowym recovery point,
- wystawiać nowego providera bez Resource Managera,
- implementować GUI bez Platform API,
- integrować domen bezpośrednio z konkretnym modelem,
- wdrażać zmian bez rollbacku,
- zostawiać testowych worktree/artifacts po zakończonym etapie.

---

## 19. Definition of Done etapu

Każdy etap kończy się:

```text
implementation
-> automated tests
-> real smoke/E2E
-> rollback check
-> runtime health
-> cleanup
-> git status/inventory
-> docs/ADR update
-> merge
```

Dopiero wtedy zaczynamy następny etap.

---

## 20. Aktualny realny task implementacyjny

Stage A, B i C zostały zakończone i zwalidowane.

**Stage D.0 — Foundation cleanup** jest technicznie zwalidowany na produkcji:

- D.0 r2 aktywny,
- canonical systemd PASS,
- Gateway-default WVC policy PASS,
- WVC/Gateway/Qwen PASS,
- media + Telegram PASS,
- rollback Stage C r3 i ponowna aktywacja D.0 r2 PASS.

Repo-governance gate jest zamknięty: `main-protection` wymaga PR, `platform-ci` i aktualności gałęzi przed merge.

Stage D.0 został zmergowany do `main` w PR #38. Decyzje D.1–D.4 opisano poniżej.


### Decyzja implementacyjna D.1 — 2026-09-21

D.1 wprowadza tylko semantic priority contract i mapowanie do dotychczasowego
schedulera: infrastructure=10, interactive-high=25, interactive=50, normal=100,
background=200, maintenance=300. `critical` to alias infrastructure.
`priority_class` jest opcjonalnym polem JSON; jawne legacy liczby mają
pierwszeństwo, a brak pola zachowuje defaulty i WVC. Ordering/FIFO bez zmian.

Status implementacji: **READY FOR PRODUCTION VALIDATION**; nie oznacza zamknięcia
etapu ani wdrożenia. Raport: [Stage D.1](../reports/AI_PLATFORM_STAGE_D1_SEMANTIC_PRIORITY_2026-09-21_PL.md).
D.2–D.6 pozostają poza zakresem: Job model, descriptors/routing, unified admission,
compatibility migration oraz pełna walidacja produkcyjna.


### Decyzja implementacyjna D.2 — 2026-09-22

Poprzedni krok implementacyjny: **D.2 — Job model**. Status: **DEV GATE PASS**
([supervisor gate](../reports/AUTONOMOUS_D2_DEV_GATE_2026-09-22.md)), bez potwierdzenia produkcji. Metadata-only JobState
rozszerza istniejący scheduler i status addytywnie, zachowując D.1 oraz leases.
Nie dodaje registry/routing (D.3), unified admission (D.4) ani Platform API.
[Kontrakt §7.2](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#72-job-model--stage-d2)
i [raport D.2](../reports/AI_PLATFORM_STAGE_D2_JOB_MODEL_2026-09-22_PL.md).
Historyczne informacje o walidacji D.0/D.1 powyżej pozostają dowodem etapów.

### Decyzja implementacyjna D.3 — 2026-09-22

Poprzedni krok: **D.3 — Capability/provider/node descriptors**, **DEV GATE PASS**
([supervisor gate](../reports/AUTONOMOUS_D3_DEV_GATE_2026-09-22.md)). Statyczny, walidowany registry opisuje dotychczasowe trzy
providery i lokalny node; assignment HTTP korzysta z jego identyfikatorów.
Registry nie jest health probe ani nową warstwą admission/routing. Lease opisuje
rezerwację z assignment null. Schemat dopuszcza przyszłe node'y, ale aktywny
Gateway odrzuca konfiguracje zmieniające single-node topology. Modele i produkty
pozostają bez zmian. D.4–D.6 nie są realizowane w tym kroku.
[Kontrakt §8.1](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#81-static-descriptors--stage-d3)
i [raport D.3](../reports/AI_PLATFORM_STAGE_D3_DESCRIPTORS_2026-09-22_PL.md).

### Decyzja implementacyjna D.4 — 2026-09-22

Poprzedni krok: **D.4 — Unified admission**, **DEV GATE PASS**
([supervisor gate](../reports/AUTONOMOUS_D4_DEV_GATE_2026-09-22.md)).
Wspólny scheduler i D.3 workload bindings obejmują LLM HTTP, media external
reservations oraz istniejące embeddings proxy. JobState dodaje metadata-only
workload; D.2 lifecycle rezerwacji pozostaje bez zmian. External-use guard blokuje
kosztowne media bez aktywnego lease; publiczne ścieżki nie mają silent fallback.
Queue/priority/FIFO, HTTP cancellation i heartbeat/TTL zachowane. Nie dodano
EmbeddingProvider/modelu ani Knowledge Service. Endpointy compatibility zostają
na D.5, produkcyjne smoke/rollback na D.6. Nowy guard wymaga zgodnej wersji Gateway
oraz repo helperów przy przyszłym wdrożeniu; bieżące D.0 tooling/recovery guardy
pozostają zachowane.
[Kontrakt §7.3](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#73-unified-admission--stage-d4)
i [raport D.4](../reports/AI_PLATFORM_STAGE_D4_UNIFIED_ADMISSION_2026-09-22_PL.md).

### Decyzja implementacyjna D.5 — 2026-09-22

Aktualny krok: **D.5 — Compatibility migration**, **READY FOR SUPERVISOR VALIDATION**.
Migracja używa istniejących endpointów i D.1–D.4 kontraktów; nie dodaje Platform API.
WVC wybiera namespace ventilation; helper adaptuje znane Telegram/Discord chat
callery do llm bez patchowania produktu. Media compilers wymagają Gateway :11435,
usuwając możliwość przypadkowego direct inference przez loopback :11434.
Legacy API, WAIT/START, explicit numeric priorities i recovery paths pozostają.
D.6 production validation nie rozpoczęto. Lokalna walidacja nie jest production gate.
[Kontrakt §7.4](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#74-compatibility-migration--stage-d5)
i [raport D.5](../reports/AI_PLATFORM_STAGE_D5_COMPATIBILITY_MIGRATION_2026-09-22_PL.md).

### Decyzja D.6 preparation — 2026-09-22

Aktualny krok: przygotowanie kompletnego Stage D do późniejszej walidacji
produkcyjnej. **READY FOR PRODUCTION VALIDATION — implementation ready for
supervisor validation**, bez cutover, real smoke ani live rollback.
Supervisor rozstrzygnął release contract: stage=D, phase=D.6,
config_schema_version=3, migration_version=resource-manager-v2; Resource Manager
contract=2, kontrakty priority/JobState/registry/admission/compatibility=1.
Provider contracts pozostają bez zmian. D.0 foundation metadata jest historyczne,
nie opisuje bieżącego kandydata. Pełne mapowanie stamp/YAML:
[Component Contracts §20](AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#20-release-contract-resource-manager-v2--decyzja-supervisora-2026-09-22).

[Runbook D.6](../../deploy/stage-d/D6_VALIDATION_RUNBOOK.md) definiuje WVC,
Telegram multiuser/Discord, real media, matched client inventory i rollback cycle.
[Raport przygotowania](../reports/AI_PLATFORM_STAGE_D6_PREPARATION_2026-09-22_PL.md)
oddziela testy lokalne od niewykonanej walidacji produkcyjnej. Stage E i kolejne
pozostają poza zakresem. Nie usuwamy D.0 r2 ani Stage C r3 recovery evidence.


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

### Wynik produkcyjnej walidacji D.6 — 2026-09-22

Release `stage-d-resource-manager-v2-20260922-r2`
(`82d55f629f763c9352ad7c9e678e22eadb623639`) przeszedł produkcyjny cutover,
matched client restore/apply oraz pełny cykl D.6 -> D.0 r2 -> D.6.

PASS: WVC/Gateway/Qwen, real media, Telegram multiuser + `/foto` + `/wideo`,
Discord, live priority ordering i non-preemption, final health/idle.
Live client cancellation: NOT RUN; automated cancellation coverage retained.

Stage D.6 production gate jest zaliczony. Desired state został zapisany przez
PR #47 i scalony do `main` jako `62f00ab2a1aade2be9cc86d69e068647652d5a27`.
Pre-merge CI #451 oraz post-merge CI #452 zakończyły się PASS, w tym pełny test
suite i walidacja Stage D release build. **Stage D = COMPLETE.** Następny etap
migracji to Stage E — Platform API.

### Stage E — kandydat implementacyjny

Dodano wersjonowane Platform API na istniejącym Gateway, współdzielone admission,
logical model, request/context correlation, znormalizowane błędy, job API,
health aggregation i auth policy boundary. Compatibility D.6 pozostaje aktywne.
Przygotowano dziewięć skryptów supervisor gate, immutable rollback baseline D.6 r2,
real Platform API/WVC smoke i obowiązkową integrację z prywatnym site E2E harness
Telegram/Discord/media. Brak harness blokuje preflight; unit tests nie zastępują
live dowodu. Stage F/G/H nie są częścią zmiany.

Status i DEV evidence: [raport Stage E](../reports/AI_PLATFORM_STAGE_E_DEV_GATE.md).
Production gate i rollback wykonuje wyłącznie supervisor zgodnie z
[runbookiem](../../deploy/stage-e/README.md). Nie zadeklarowano production COMPLETE.


### Stage E — zweryfikowany production gate

Production validation **PASS** dla `stage-e-38fff86f7704`.
Pełny cykl candidate smoke -> rollback D.6 smoke -> reactivation smoke przeszedł
z realnym inference, outbound Telegram/Discord i renderem media pod admission.
CI źródła: 764 tests PASS. D.0/D.6 i matched clients zachowane.
[Raport produkcyjny](../reports/AI_PLATFORM_STAGE_E_PRODUCTION_GATE.md),
[diagnoza i naprawa gate](../reports/AI_PLATFORM_STAGE_E_RECOVERY_2026-09-22.md).
Stage F wymaga świeżego inbound multiuser i pełnych messaging/media user paths;
dowody Stage E nie zastępują tych kryteriów.


### Stage F — prerequisite gate 2026-09-23

**BLOCKED przed implementacją i deploymentem**: brak provisioned external-user
E2E harness / uczestników do świeżego Telegram multiuser i messaging user-path gate.
Stage E COMPLETE (PR #53, final i post-merge CI PASS); aktywny release pozostaje
`stage-e-38fff86f7704`. Stage G/H NOT STARTED.
[Dowody i warunki wznowienia](../reports/AI_PLATFORM_STAGE_F_PREREQUISITE_BLOCKER_2026-09-23.md).

### Stage F — approved internal evidence boundary, 2026-09-23

The operator superseded the human-participant prerequisite with controlled
SYNTHETIC/INTERNAL E2E on AI Server. Two independent Telegram-like contexts and
analogous Discord-like contexts must exercise every changed internal boundary:
request/job correlation, isolation/routing, WAIT→START, media command context,
Resource Manager leases/admission, Hermes integration, artifacts and idle recovery.
Use real local production components where safe. External Telegram/Discord inbound
transport remains DEFERRED/NOT TESTED, never PASS. This boundary plus passing
production compatibility tests is sufficient for F acceptance and sequential G/H.
Historical D.6 external-user evidence remains historical only.

A stable candidate stays active while repairable validation issues are corrected.
Rollback is required for unsafe/degraded/uncertain runtime or the mandatory planned
rollback test, rather than automatically after every failed assertion. Stage F
implementation/review is in progress; completion still requires the full production,
rollback/reactivation, Git/PR/CI/merge sequence.

### Stage F — GPU incident, 2026-09-23

F remains draft: pre-existing AMD MES ring-full errors prevent real inference even
after a guarded model-service restart. E source/release retained; inference ingress
paused, telemetry/history and idle Comfy preserved. G/H NOT STARTED. See
[incident and resumption requirements](../reports/AI_PLATFORM_STAGE_F_GPU_BLOCKER_2026-09-23.md).
External transport deferral is not the blocker. Internal harness review gaps and the
full candidate/rollback/reactivation cycle remain required after host GPU recovery.

### Stage F — post-reboot residency validation, 2026-09-23

Production gate **PASS** for `stage-f-d8f68cadd953`: 799 local tests, immutable
build/install, kernel-guarded candidate smoke, planned E rollback/smoke, F
reactivation/full smoke and finalize. Eight real media jobs across two independent
internal E2E cycles verified Ollama drainage, Comfy cleanup and later Qwen inference.
Ollama was not restarted; no new GPU kernel faults were observed. This repairs
shared-GPU residency ownership and does **not** claim a driver fix.

External inbound Telegram/Discord remains **DEFERRED/NOT TESTED**. Messaging
acceptance uses the approved SYNTHETIC/INTERNAL boundary. PR #63 merged as `245caef`; final CI and post-merge CI #35837338807 PASS.
**Stage F COMPLETE.** Stage G can start. See the
[production report](../reports/AI_PLATFORM_STAGE_F_PRODUCTION_GATE.md).

### Stage G — implementation candidate

WVC schemas, analysis profiles/services/policy, persistence and telemetry/delivery
API live in `ai_bridge.domains.wvc`, composed through a domain adapter. Compatibility
imports/routes and existing database schema/history are preserved. Scheduled empty
windows return `skipped/no_fresh_data` without inference or a placeholder row.
Fresh windows resume processing; inter-process serialization and existing unique
identities prevent duplicate analysis. AI remains advisory-only. Production
candidate/rollback/reactivation, GitHub CI and merge are still pending. See
[domain architecture](WVC_DOMAIN.md) and [gate](../../deploy/stage-g/README.md).

### Stage G — new GPU blocker, 2026-09-23

Candidate `stage-g-7ccc9c14da33` and planned F rollback/full smoke passed. Actual
WVC policy and installed timer returned `skipped/no_fresh_data`; historical hashes
were preserved. Final reactivation smoke failed after a video at 11:21:36 CEST
with MES WAIT_REG_MEM errors despite zero observed Ollama residents. **G BLOCKED;
H NOT STARTED.** Verified F was restored with inference/media ingress paused,
telemetry/history active, no GPU probes/restarts and all recovery evidence retained.
F's completed historical validation is not a claim that the GPU driver is fixed.
[Full incident and evidence](../reports/AI_PLATFORM_STAGE_G_PRODUCTION_GATE.md).

### Stage G/H — completion and live post-acceptance evidence, 2026-09-23

Stage G production validation ultimately passed after bounded ComfyUI cleanup wakeups
were corrected; PR #64 merged and post-merge CI passed. Stage H then completed the
reversible four-file legacy-helper quarantine with full G rollback/reactivation;
PR #65 merged and post-merge CI passed. No purge was performed.

After H, real external acceptance additionally verified Telegram video, Discord
voice/photo/video and physical WVC reconnect. CM5 telemetry from `192.168.1.64`
resumed without duplicate-ingest symptoms. The H finalization defect that left the
WVC analysis timer stopped was corrected in PR #66; the timer is now enabled/active
and completed a scheduled Gateway/Qwen advisory over 141 real CM5 samples. Missing
sensor values in that window are expected because physical WVC peripherals were
intentionally disconnected. No new MES/ring/reset/timeout fault was observed.

### Stage I — Observability & operations hardening — decyzja 2026-09-23

P2 orders observability before Knowledge Service. Therefore the next migration step
is Stage I, inserted explicitly between completed H and the first new knowledge
functionality. This does not renumber the historical E–H evidence; it names the
operational hardening step needed before further product expansion.

Stage I adds a bounded metadata-only Platform observability contract and structured
request correlation. It does not add Prometheus/Grafana, persistent metrics storage,
a model/GPU change, a new public listener, Knowledge Service or domain control.
The verified rollback point is `stage-h-b9362bdae1c3`.

Knowledge Service remains the next functional stage after I and should be treated as
Stage J in the continuation of this lettered migration sequence. Its pgvector/Qdrant
ADR remains out of Stage I scope.

### Stage I — production completion 2026-09-23

Production gate **PASS** for `stage-i-30626dcc60f8` (`30626dcc60f86c80bacb3c602b87f2d345b22221`). Full H → I candidate smoke → verified H rollback/smoke → I reactivation/final smoke → finalize cycle passed. Functional rollback proved `/api/v1/observability` absent on H. Final runtime is I with Hermes and WVC analysis timer active, RM idle, GPU residency `llm`, and no new MES/ring/reset/timeout kernel fault. Production evidence: [Stage I report](../reports/AI_PLATFORM_STAGE_I_PRODUCTION_GATE_2026-09-23.md).

**Stage I = PRODUCTION COMPLETE.** Repository closure still requires PR #68 merge and post-merge CI; the accepted runtime release remains immutable regardless of later documentation-only commits.

### Stage J — Knowledge Service foundation — 2026-09-23

J0/J1 ustanowiły Qdrant jako pierwszy, ale wymienny backend retrieval za neutralnym
`KnowledgeBackend`. Qdrant nie jest source of truth; publiczni klienci znają tylko
Knowledge Service. Runtime Qdranta jest self-hosted, loopback-only i przeszedł live
adapter/source-attribution smoke. Foundation została scalona przez PR #70.

J2 definiuje backend-neutralny canonical model
`Source -> Document -> DocumentVersion -> Chunk`, deterministyczne identyfikatory,
SHA-256/provenance oraz referencję ACL niezależną od vector DB. Knowledge Service
generuje query embedding wewnętrznie przez neutralny `EmbeddingProvider`; klient
nie podaje fizycznego modelu ani wymiarów.

Benchmark na rzeczywistych danych ECU/WVC wybiera pierwszy dense baseline:
`bge-m3`, 1024D cosine, heading-aware chunk około 2400 znaków. Evidence-based
quality: Recall@1 92.3%, Recall@3/5 100%, MRR 0.962. Baseline jest wymienialny przez
reindex i nie zmienia publicznego API.

J2 nie oznacza jeszcze pełnego RAG ani produkcyjnego ingestion. Następny gate powinien
dodać trwały canonical store/ingestion oraz wersjonowany indeks, a potem
exact/full-text/sparse/hybrid retrieval i reranking. Szczegóły:
[ADR-001](adr/ADR-001_STAGE_J_REPLACEABLE_QDRANT_BACKEND_2026-09-23_PL.md),
[ADR-002](adr/ADR-002_STAGE_J2_EMBEDDING_BASELINE_2026-09-23_PL.md).

### Stage J3 — production completion 2026-09-23

Stage J3 production gate **PASS** after merge PR #73 plus PostgreSQL FK-ordering
hotfix PR #75. Canonical knowledge is now durable in PostgreSQL plus immutable
content-addressed objects; Qdrant is a rebuildable projection.

Real read-only ingestion of EcuRepairService at
`0ee98b94705b691d7347c8a6a5676ac63159e359` produced 19 documents,
19 versions, 67 chunks and 19 completed index jobs. Repeated ingestion produced
0 new versions/chunks; reindex retry after completion selected 0 jobs.

Production Qdrant collection `knowledge_dense_bge_m3_1024_v1` is green with
67 points and indexed canonical payload fields. Exact, semantic and hybrid probes
passed on real ECU knowledge. All 19 immutable objects passed SHA-256 revalidation.
EcuRepairService remained clean and unmodified.

The first production ingest exposed an FK flush-order defect; PostgreSQL rolled
the transaction back fully. The fix adds explicit parent flushes and SQLite CI
tests with foreign keys enabled. See the
[Stage J3 production report](../reports/AI_PLATFORM_STAGE_J3_PRODUCTION_GATE_2026-09-23_PL.md)
for backup, incident, hotfix and acceptance evidence.

**Stage J3 = PRODUCTION COMPLETE.**

### Stage J4 — final Knowledge Service gate

Końcowy Stage J dodaje page-aware PDF ingestion z Tesseract fallback OCR,
technical-evidence reranking oraz publiczne Platform API `Szukaj` / `Zapytaj AI`.
RAG używa wyłącznie retrieval context i structured claims z claim-level citations;
nieznane źródło lub niepoprawny structured output są odrzucane fail-closed.

Stage J otrzymuje własny immutable release `knowledge-service-v1` z funkcjonalnym
rollbackiem do zweryfikowanego Stage I. Rollback ma dowieść, że Knowledge routes
są nieobecne na I, podczas gdy obserwowalność i wcześniejsze funkcje pozostają.

PDF source content jest przechowywany kanonicznie jako immutable object, a page
locator jest zachowywany w chunkach/cytowaniach. GUI nie należy do Stage J — późniejszy
AI Control Center ma konsumować stabilne Knowledge API.

Szczegóły: [ADR-004](adr/ADR-004_STAGE_J4_RAG_PDF_API_2026-09-24_PL.md).

### Stage J — production completion 2026-09-24

Pełny Stage J production gate **PASS** dla `stage-j-3b456a56343a`
(`3b456a56343a533d2d920e1e63dfe304530c865b`). Zweryfikowano pełny cykl
`I -> J -> I -> J`: candidate smoke, funkcjonalny rollback do Stage I,
rollback smoke, reactivation, final smoke i finalize.

Końcowy runtime to Stage J z aktywnym Gateway, AI Bridge, WVC analysis timer i
ComfyUI; Gateway health jest `ok`, Resource Manager idle, admission odblokowany,
a liczba active leases wynosi 0. Candidate/final smoke objęły Knowledge search,
claim-level cited RAG, source opening, WVC, Hermes inference, Telegram/Discord
messaging boundary i media preflight. Rollback smoke potwierdził brak Knowledge
routes na Stage I przy zachowaniu wcześniejszych kontraktów.

Acceptance ujawnił i zamknął race condition gotowości outbound Hermes po restarcie;
bounded retry pozostaje fail-closed dla trwałych błędów, a przerwany smoke może
zachować wcześniejsze write-once evidence i wznowić się przez recovery evidence.
Zmiana przeszła GitHub CI wraz z `Validate Stage J release build` i została scalona
przez PR #80.

Production evidence:
[Stage J production report](../reports/AI_PLATFORM_STAGE_J_PRODUCTION_GATE_2026-09-24_PL.md).

**Stage J = PRODUCTION COMPLETE.**
