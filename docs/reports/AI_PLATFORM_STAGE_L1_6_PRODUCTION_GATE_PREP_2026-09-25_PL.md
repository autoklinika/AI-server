# AI Platform — Stage L1.6 — Production Gate Preparation

**Data:** 2026-09-25
**Status:** DEV/PRE-PROD GATE PASS — LIVE CUTOVER PENDING
**Rollback release:** `stage-j-3b456a56343a`
**Rollback schema:** `0003_knowledge_canonical`
**Target schema:** `0004_ers_core_persistence`

## Cel

Przygotować pełny, odwracalny production gate L1:
`Stage J / schema 0003 -> Stage L / schema 0004 -> rollback J/0003 -> reactivation L/0004`.

Gate obejmuje runtime, PostgreSQL, deterministic legacy import, Stage J compatibility
oraz Stage K backup/restore evidence.

## Candidate runtime

Stage L release:
- nowy release ID: `stage-l-<source-sha-prefix>`;
- `migration_version=ers-domain-v1`;
- `observability_contract_version=1`;
- `knowledge_service_contract_version=1`;
- `ers_domain_contract_version=1`.

W Stage L domyślna kompozycja AI Bridge zawiera:
- WVCAdapter;
- ERSAdapter.

Stage J rollback release pozostaje niezmieniony i nie udostępnia ERS API.

## Production DB operations

Dodano `deploy/stage-l/production_ops.py`.

Helper:
- jest uruchamiany jako nie-root owner platformy;
- czyta DB URL wyłącznie z istniejącego `/etc/ai-bridge/ai-bridge.env`;
- nie przyjmuje DB URL przez CLI;
- wykonuje upgrade/downgrade Alembic;
- importuje CASE-0001/CASE-0002 z realnego ERS source-cache;
- używa shared immutable ObjectStore;
- weryfikuje case status/work_state, event sequence, artifact counts i object hashes.

Obsługiwane akcje:
`upgrade | downgrade | import | verify-active | verify-inactive`.

## Native PostgreSQL validation

Ten sam production helper przetestowano na tymczasowym PostgreSQL 18,
z prawdziwymi seedami CASE-0001/CASE-0002 i tymczasowym ObjectStore.

Wynik:
- upgrade do `0004_ers_core_persistence`: PASS;
- first import: 2 case / 33 artifact versions: PASS;
- CASE-0001: 17 artifacts, row_version 32;
- CASE-0002: 16 artifacts, row_version 29;
- drugi import: oba case `reused`, bez duplikacji;
- object integrity: PASS;
- downgrade do `0003_knowledge_canonical`: PASS;
- po downgrade `ers_*=0`.

`STAGE_L16_PRODUCTION_OPS_NATIVE_PG=PASS`.

## Production gate 00–90

Dodano komplet:
- 00 preflight;
- 10 build/install;
- 20 cutover;
- 30 candidate smoke;
- 40 rollback;
- 50 rollback smoke;
- 60 reactivation;
- 70 final smoke;
- 90 finalize.

Preflight wymaga:
- aktywnego, zweryfikowanego Stage J;
- schema 0003 i 0 tabel ERS;
- clean ERS source-cache;
- świeżego manualnego Stage K backupu schema 0003.

Finalizacja wymaga:
- Stage L aktywnego;
- schema 0004;
- zweryfikowanych dwóch case;
- świeżego Stage K ERS Case Store backupu;
- pełnego cyklu rollback/reactivation.

## Smoke

Każdy candidate/final smoke sprawdza:
- Platform API;
- observability;
- Knowledge Search/RAG/source opening;
- WVC;
- Hermes connected + real inference;
- Telegram/Discord messaging boundary;
- unchanged external clients;
- media preflight;
- runtime health;
- ERS HTTP read dla CASE-0001 i CASE-0002;
- schema 0004, 33 artifacts/versions i ciągłość eventów.

Rollback smoke sprawdza:
- Stage J runtime;
- Knowledge nadal działa;
- ERS API jest nieobecne;
- schema wróciła do 0003;
- 0 tabel `ers_*`.

## ObjectStore rollback semantics

Rollback bazy usuwa tabele ERS przez Alembic `0004 -> 0003`.

Immutable bytes zapisane wcześniej do shared ObjectStore nie są kasowane.
Po rollbacku mogą pozostawać jako niepodpięte content-addressed objects,
co jest bezpieczniejsze niż kasowanie podczas recovery.

Reactivation:
- ponownie wykonuje `0003 -> 0004`;
- deterministic import reuses istniejące object hashes;
- odtwarza Case Store bez modyfikowania original bytes.

## Dev validation

- Stage L1.1–L1.5 targeted stack: **36/36 PASS**;
- Stage L production/API/control-plane targeted: **39/39 PASS**;
- native PostgreSQL production_ops cycle: **PASS**;
- pełny AI Platform regression suite: **PASS 100%**;
- shell syntax: PASS;
- Python compile: PASS;
- `git diff --check`: PASS.

CI został rozszerzony o realny Stage L release build.

## Privilege bridge

Ograniczony root executor został rozszerzony przez osobny PR #95:
- Stage L jest mapowany wyłącznie na `~/agent-worktrees/stage-l`;
- pozostają wymagania exact branch, exact SHA, clean worktree, remote SHA,
  main ancestor i committed script hash;
- nie jest przyznawany generalny root shell.

Live gate wymaga jednorazowej reinstalacji bridge'a przez operatora po merge PR #95.

## Granica bezpieczeństwa

Na etapie tego raportu produkcja nie została zmieniona:
- active runtime nadal Stage J;
- schema nadal 0003;
- production `ers_*` nadal 0;
- CASE-0001/CASE-0002 nie są jeszcze w production Case Store.

Następny krok po candidate CI i aktualizacji privilege bridge:
fresh Stage K backup -> 00 preflight -> 10 build/install -> 20/30 ->
40/50 -> 60/70 -> final Stage K backup/restore -> 90 finalize.
