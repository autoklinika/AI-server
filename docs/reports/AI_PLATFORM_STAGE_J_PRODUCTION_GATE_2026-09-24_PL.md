# AI Platform — Stage J Knowledge Service — production acceptance

**Data:** 2026-09-24  
**Status:** **PRODUCTION PASS / STAGE J COMPLETE**  
**Accepted source SHA:** `3b456a56343a533d2d920e1e63dfe304530c865b`  
**Accepted release:** `stage-j-3b456a56343a`  
**Rollback release:** `stage-i-30626dcc60f8`

## Wynik końcowy

Stage J został zaakceptowany produkcyjnie po pełnym, odwracalnym cyklu:
`Stage I -> Stage J candidate -> Stage I rollback -> Stage J reactivation -> finalize`.

Końcowy runtime wskazuje `/opt/ai-platform/releases/stage-j-3b456a56343a`.
Po `90_finalize` Gateway, AI Bridge, WVC analysis timer i ComfyUI są aktywne,
Gateway `/health` zwraca `status=ok`, scheduler jest idle
(`active=0`, `queued=0`), admission jest odblokowany, a liczba lease wynosi 0.

## Production gate — zaakceptowany przebieg

- `00_preflight` — PASS.
- `10_build_install` — PASS.
- `20_cutover` — PASS.
- `30_smoke` — PASS.
- `40_rollback` — PASS.
- `50_rollback_smoke` — PASS.
- `60_reactivate` — PASS.
- `70_reactivate_smoke` — PASS.
- `90_finalize` — PASS.
Zaakceptowana część automatyczna od `30_smoke` do `90_finalize` rozpoczęła się
2026-09-24 12:14:43 CEST. Finalizacja zakończyła się o 12:31:06 CEST.

Operator-side log przebiegu:
`/home/harrypotter/agent-state/stage-j-production/remaining-gate.log`.

## Zakres potwierdzony przez candidate/final smoke

Candidate i final smoke potwierdziły jednocześnie:
- istniejący Platform API i observability contract;
- raw Knowledge search;
- RAG `Zapytaj AI` z claim-level citations;
- otwieranie metadanych dokumentu i immutable source content;
- WVC reasoning przez wspólny Resource Manager;
- Hermes inference;
- synthetic Telegram/Discord messaging boundary;
- realny outbound Hermes do skonfigurowanego Telegrama i Discorda;
- media preflight;
- zachowanie matched clients oraz health/idle invariants.

W schedulerze końcowego final smoke widoczne były poprawnie zakończone workloady
`reasoning`, `embeddings`, `structured-generation` dla `ecu-repair`,
`reasoning` dla WVC oraz kolejne `chat` dla messaging boundary.

## Rollback

Kontrolowany rollback do `stage-i-30626dcc60f8` zakończył się PASS.
Rollback smoke potwierdził zdrowy Stage I oraz brak Stage J Knowledge routes,
przy zachowaniu wcześniejszych kontraktów platformy.

Następnie `60_reactivate` przywrócił Stage J, a `70_reactivate_smoke`
ponownie zweryfikował cały wymagany zakres przed `90_finalize`.
## Data preparation i integralność

`10_build_install` wykonał fail-closed production data preparation wymagane przez
Stage J: backup PostgreSQL przed ingestem, dwukrotny PDF ingestion,
drain pending index jobs oraz SHA-256 verification content-addressed canonical store.

Drugi przebieg ingestion jest wymagany jako idempotency gate i musi tworzyć
0 nowych wersji oraz 0 nowych chunków. Kandydat nie jest budowany, jeśli którykolwiek
z tych warunków, backup verification, reindex drain lub object integrity nie przejdzie.

EcuRepairService pozostaje źródłem read-only; Qdrant pozostaje rebuildable projection,
a canonical PostgreSQL + immutable object store są source of truth.

## Recovery / incydenty ujawnione podczas acceptance

Wcześniejsze próby ujawniły dwa problemy operacyjne, które nie są częścią
zaakceptowanego przebiegu końcowego:

1. Wcześniejszy candidate smoke został przerwany po zapisaniu markera
   `candidate-smoke-started.json`. Evidence nie zostało usunięte ani nadpisane;
   kolejny przebieg otrzymał nowy source SHA.
2. Rollback smoke ujawnił krótkie okno po restarcie Hermes, w którym
   `gateway_state.json` raportował kanały jako connected, ale pierwszy realny outbound
   mógł jeszcze nie być gotowy.

Drugi problem został naprawiony przez bounded retry messaging boundary oraz
recoverable smoke evidence. Trwały błąd nadal kończy gate fail-closed.
Zmiana przeszła lokalny pełny suite oraz GitHub CI, w tym
`Validate Stage J release build`, i została scalona przez PR #80.
## Release contract

Accepted release deklaruje:
- stage `J`, phase `J`;
- migration `knowledge-service-v1`;
- Platform API contract `1`;
- Resource Manager contract `2`;
- provider registry schema `1`;
- unified admission contract `1`;
- observability contract `1`;
- Knowledge Service contract `1`.

Publiczna granica Knowledge pozostaje backend-neutralna. Qdrant, Ollama,
fizyczne modele i ścieżki storage nie są częścią publicznego kontraktu API.

## Decyzja

**Stage J = PRODUCTION COMPLETE.**

Zweryfikowany rollback point pozostaje `stage-i-30626dcc60f8`.
Aktywny zaakceptowany release to `stage-j-3b456a56343a`.

Kolejne etapy platformy mają konsumować stabilne Knowledge Service API;
nie powinny omijać go bezpośrednim dostępem do Qdrant ani canonical storage.
