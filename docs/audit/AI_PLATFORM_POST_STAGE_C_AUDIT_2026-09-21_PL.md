# AI Platform — Post-Stage C Audit

**Data:** 2026-09-21  
**Repo:** `autoklinika/AI-server`  
**Audytowany branch:** `main` po merge PR #36  
**Merge commit:** `df55674c2c1f023567adc7890856a87b260f0b4d`  
**Aktywny zwalidowany runtime:** `stage-c-provider-abstraction-20260921-r3`  
**Runtime source SHA:** `cfe1b12ba5a35e2975ff942a2509ab2eaa3e21c5`

## 1. Executive summary

Stage C zakończył się poprawnie i obecny runtime jest stabilną bazą do kolejnego etapu. Nie znaleziono problemu klasy P0 wymagającego rollbacku lub zatrzymania prac.

Najważniejsze fakty po Stage C:
- provider abstraction działa;
- WVC ingest działa po naprawie schema drift;
- media idą przez `MediaGenerationProvider`;
- Telegram `/wideo` E2E działa;
- Resource Manager/AI Gateway jest funkcjonalnym globalnym admission point;
- scheduler/leases mają sensowny zestaw testów;
- backendy Ollama i ComfyUI pozostają localhost-only;
- release r3 jest reprodukowalny i ma rollback.

Jednocześnie repo nie jest jeszcze gotowe, aby po prostu kontynuować Stage C toolingiem do Resource Manager v2. Stage D wymaga najpierw uporządkowania kilku granic desired state i deployment.

## 2. Runtime baseline — PASS

Ostatnia produkcyjna walidacja r3 potwierdziła:
- AI Bridge health: PASS;
- AI Gateway/Ollama health: PASS;
- effective node identity: `ai-node-01`;
- real media smoke: H.264 640x384, 24 fps, 25 frames, ~1.04 s;
- Resource Manager po smoke: 0 active / 0 queued / 0 leases;
- ComfyUI queue: empty;
- WVC: ciągłe HTTP 200;
- Hermes PID bez nieplanowanego restartu;
- ComfyUI PID bez nieplanowanego restartu;
- Telegram `/wideo`: PASS.

Produkcja jest na SHA `cfe1b12...`, podczas gdy `main` jest później. Porównanie wykazało, że jedyną zmianą po runtime SHA jest końcowy raport dokumentacyjny; nie ma kodowego driftu produkcja vs main.

## 3. Provider abstraction — PASS

W `main` istnieją stabilne kontrakty: `LLMProvider`, `AgentProvider`, `MediaGenerationProvider`, `EmbeddingProvider`, `KnowledgeBackend`. Adaptery produktowe są oddzielone: `OllamaAdapter`, `HermesAdapter`, `ComfyUIAdapter`.

## 4. Resource Manager baseline — funkcjonalny, ale jeszcze v1

Obecny `PriorityScheduler` zapewnia priority ordering, FIFO w ramach tego samego priorytetu, max concurrency, queue limit, cancellation cleanup i external reservation.

`ResourceLeaseRegistry` zapewnia wspólny slot dla workerów zewnętrznych, queued/active lease state, heartbeat, TTL dla idle lease, begin/end use oraz release explicit/release-after-use.

Test coverage obejmuje priority ordering, FIFO, queue full, cancellation after dispatch, lease sharing, queued lease protection, TTL reaping, leased HTTP release i media lease utrzymywany między Qwen i ComfyUI. Nie ma potrzeby przepisywania schedulera od zera.

## 5. P1 — CI nie chroni aktualnego main

Repo ma jeden workflow `.github/workflows/ai-gateway-tests.yml`. Jego `push.branches` zawiera historyczne feature branche i nie zawiera `main`. Merge commit `df55674...` ma 0 workflow runs.

PR path filter nie obejmuje wprost m.in. `src/ai_bridge/providers/**` ani `deploy/stage-c/**`. Stage C był poprawnie zwalidowany manualnie pełnym suite, więc to nie jest wada bieżącego runtime, ale luka procesu.

Zalecenie D.0: workflow na PR do `main` i push do `main`, full pytest, syntax checks dla aktywnych deployment scripts, provider/contract tests i release-build validation. Następnie required check / branch protection.

**Priorytet: P1.**

## 6. P1 — desired-state drift: WVC może domyślnie ominąć Gateway

`Settings.analysis_use_gateway` nadal domyślnie wynosi `False`. `deploy/ai-bridge.env.example` również ma `AI_BRIDGE_ANALYSIS_USE_GATEWAY=false` z komentarzem Safe rollout, mimo że Gateway został zwalidowany produkcyjnie.

`analysis/main.py` nadal zawiera compatibility branch `gateway_url if use_gateway else ollama_url`.

Ryzyko: nowa instalacja oparta na example env może uruchomić WVC analysis bez admission control.

Zalecenie Stage D: Gateway jako domyślna ścieżka; direct Ollama jedynie jako jawny recovery/debug compatibility mode albo usunąć po zwalidowaniu rollbacku.

**Priorytet: P1.**

## 7. P1 — canonical systemd desired state jest rozproszony

Bazowe `deploy/systemd/ai-bridge.service`, `ai-gateway.service` i `ai-bridge-analysis.service` nadal wskazują `/opt/ai-bridge` i `/opt/ai-gateway`.

Aktualna produkcja jest poprawnie zarządzana przez drop-iny Stage A kierujące na `/opt/ai-platform/current/services/...`.

Runtime jest poprawny, ale source of truth do odtworzenia hosta jest rozdzielony między legacy unit i migracyjny drop-in.

Zalecenie: canonical release-managed systemd units w repo + idempotent install/restore. Stage A drop-ins pozostawić tylko jako migracyjny compatibility layer.

**Priorytet: P1.**

## 8. P1 — obecny release pipeline celowo blokuje Stage D

`deploy/stage-c/build_release.sh` wymusza brak zmian w `src/ai_bridge/gateway`, `scheduler_source_changed: false` i `stage=C`. To było właściwe zabezpieczenie Stage C.

Stage D ma z definicji zmienić Gateway/Resource Manager, więc obecnego buildera nie wolno rozszerzać przez obchodzenie guardów.

Zalecenie: stage-neutral release tooling albo jawny `deploy/stage-d/`, zachowujący final-path venv, checksums, install-without-activation, health/idle gates i rollback do poprzedniego release.

**Priorytet: P1 / blocker produkcyjnego cutover Stage D.**

## 9. P2 — priorytety są jeszcze domenowe i numeryczne

Konfiguracja nadal ma `gateway_priority_ventilation=10`, `interactive=50`, `normal=100`, `background=200`; Gateway akceptuje `X-AI-Priority`, `X-AI-Source` i compatibility endpointy `/clients/ventilation/...` oraz `/clients/hermes/...`.

Target Architecture wymaga semantic priority classes. Stage D powinien wprowadzić klasy np. `infrastructure`, `interactive-high`, `interactive`, `normal`, `background`, `maintenance`, a mapowanie do liczb pozostawić wewnętrzne.

Compatibility endpoints/header można zachować przejściowo.

## 10. P2 — brak capability/provider/node routing w Resource Managerze

Obecny Gateway jest schedulerem + proxy do jednego upstream Ollama. Media współdzielą lease, ale ComfyUI wykonuje się poza Gateway proxy.

Brakuje wspólnego modelu capability, provider, node, resource class, assignment i provider readiness. To jest główny zakres Resource Manager v2, a nie błąd Stage C.

## 11. P2 — observability jest operacyjne, ale nie docelowe

`/status` pokazuje active/queued, priority, source, wait i leases. Brakuje stabilnych pól: request_id/correlation_id, capability, priority_class, assigned_provider, assigned_node, lifecycle timestamps i error classification.

Stage D powinien wprowadzić JobState bez logowania treści promptów.

## 12. P2 — legacy stageXX i branch-pinned tooling

W `main` nadal są historyczne stage23–stage30 media scripts, branch-pinned installery, stare gateway stage1/2/3 cutovers i rollbacki do `/opt/ai-bridge`/`/opt/ai-gateway`.

Nie usuwać ich natychmiast, bo część jest recovery evidence. Po stabilnym Stage D i nowym recovery point oznaczyć obsolete i wykonać kontrolowany cleanup.

## 13. P2 — dokumentacja zawiera historyczne, dziś nieprawdziwe stany

Przykłady: Target Architecture nadal jest opisana jako kandydat do `main`; mówi o `UFW inactive / INPUT accept`; Migration Plan mówi, że WVC jest odłączony; Final Hardening report ma `runtime validation pending`; env example nadal opisuje Gateway jako niezwalidowany rollout.

Historyczne raporty mogą zachować dawny stan, ale current target/desired-state docs należy odświeżyć w D.0.

## 14. P2 — release manifest Stage C jest za wąski

Manifest Stage C wymienia llm/agent/media, ale nie kontrakty embedding/knowledge. `behavior_change: false` jest też zbyt ogólne dla release zawierającego m.in. WVC schema compatibility i media cutover.

Stage D manifest powinien zawierać changed components, contract versions, config/migration versions, provider/model config i compatibility flags.

## 15. Known debt — Hermes patch-in-place

Hermes pozostaje stabilnym AgentProvider, ale produkcja nadal opiera część integracji na historycznych patchach/global queue. To znany dług do późniejszego etapu Hermes clean integration. Stage D nie powinien go powiększać.

## 16. Security

Po Stage B backendy Ollama/ComfyUI/Gateway są localhost-only, AI Bridge pozostaje wymaganym LAN API, a host firewall został wdrożony deny-by-default. Stare dokumenty opisujące pre-Stage-B stan są dokumentacyjnym driftem.

Resource Lease API nie ma osobnego auth, ale działa na localhost-only Gateway. Dla single-node jest to akceptowalne; multi-node będzie wymagał service identity/authN.

## 17. Ocena gotowości

- Produkcja po Stage C: **GREEN**.
- Repo jako source of truth: **AMBER/GREEN**.
- Gotowość do rozpoczęcia Stage D development: **GREEN**.
- Gotowość do Stage D production cutover: **AMBER**.

Przed cutoverem Stage D należy zamknąć cztery P1: CI, canonical systemd desired state, gateway-default/direct-bypass policy oraz Stage-D-compatible release tooling.

## 18. Rekomendowany podział Stage D

### D.0 — Foundation cleanup
- CI on PR/main;
- canonical systemd units;
- production gateway-default policy;
- nowy release/deploy tooling;
- update current architecture/docs.

### D.1 — Semantic priority classes
- priority class contract;
- mapping do numeric priority;
- compatibility dla `X-AI-Priority`;
- zachowanie obecnego ordering behavior.

### D.2 — Job model
- request_id/job_id/domain/capability/priority_class/state;
- queue/lifecycle timestamps;
- assigned provider/node.

### D.3 — Capability/provider/node descriptors
- logical provider registry/config;
- obecne Ollama/ComfyUI/Hermes jako pierwsze wpisy;
- bez wymiany modeli/backendów.

### D.4 — Unified admission
- LLM HTTP;
- media external leases;
- przyszłe embeddings;
- jeden status model.

### D.5 — Compatibility migration
- zachować istniejące endpointy podczas migracji;
- WVC/Telegram/Discord bez regresji;
- WAIT/START UX bez zmian.

### D.6 — Production validation
- full tests;
- concurrency/priority/cancellation/crash/TTL tests;
- WVC regression;
- Telegram multiuser;
- media real smoke;
- rollback;
- docs/report.

## 19. Final verdict

Stage C osiągnął swój cel i można na nim budować dalej.

Nie należy teraz zmieniać modelu Qwen, dodawać nowego GPU jako warunku, wdrażać Knowledge Service, wybierać pgvector/Qdrant ani przepisywać schedulera od zera.

Najbardziej wartościowym kolejnym krokiem jest **Stage D.0 + Resource Manager v2**, wykorzystujący istniejący `PriorityScheduler` i `ResourceLeaseRegistry` jako działający fundament.