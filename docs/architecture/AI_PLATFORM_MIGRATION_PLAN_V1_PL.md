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

## 2. Stan bieżący po Stage C

Stan zwalidowany 2026-09-21:

- Stage A: recovery baseline i release model działają; produkcja używa `/opt/ai-platform/releases` + atomowego `/opt/ai-platform/current`;
- Stage B: Ollama, ComfyUI i AI Gateway są localhost-only; host firewall działa deny-by-default;
- Stage C: provider abstraction działa (`LLMProvider`, `AgentProvider`, `MediaGenerationProvider`, `EmbeddingProvider`, `KnowledgeBackend`);
- aktywny zwalidowany runtime Stage C to `stage-c-provider-abstraction-20260921-r3`;
- WVC ingest działa i podczas końcowej walidacji zwracał ciągłe HTTP 200; lokalny backlog CM5 był pusty;
- media i Telegram `/wideo` przeszły real smoke/E2E;
- Resource Manager v1 (`PriorityScheduler` + `ResourceLeaseRegistry`) pozostaje fundamentem Stage D;
- znanym długiem pozostaje Hermes patch-in-place; Stage D nie może go powiększać;
- przed produkcyjnym cutoverem Stage D trzeba zamknąć D.0: CI, canonical systemd, Gateway-default policy i Stage-D-compatible release tooling.

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

Osobny ADR: pgvector vs Qdrant.

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
15. AI Control Center,
16. multi-node expansion.

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

Stage A, B i C zostały zakończone i zwalidowane. Aktualnym etapem jest:

**Stage D — Resource Manager v2**, rozpoczynany od **D.0 — Foundation cleanup**.

D.0 nie zmienia jeszcze semantyki schedulera. Najpierw zamyka luki desired state i deployment wykazane przez audyt po Stage C:

- CI chroniące `main`,
- canonical release-managed systemd units,
- Gateway jako domyślna ścieżka WVC analysis,
- Stage-D-compatible release/deploy tooling,
- aktualna dokumentacja source-of-truth.
