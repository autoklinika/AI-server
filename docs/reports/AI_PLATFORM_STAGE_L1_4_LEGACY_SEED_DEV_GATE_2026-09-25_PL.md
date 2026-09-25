# AI Platform — Stage L1.4 — Legacy Seed Migration Dev Gate

**Data:** 2026-09-25
**Status:** DEV GATE PASS — PRODUCTION IMPORT NOT APPLIED
**Baseline main:** `e39c56329877806e78ca1f19b27e0fe3496262eb`

## Cel

Zamknąć deterministyczną migrację historycznych przypadków ERS do aktywnego
Case Store bez ręcznego przepisywania danych i bez tworzenia fikcyjnych artefaktów.

Zakres:
- CASE-0001 GAYK / Hatz / SPN107 FMI3;
- CASE-0002 Scania EMS S6 clone;
- deterministic seed;
- content-addressed ObjectStore;
- idempotent apply;
- provenance i audit events;
- fail-closed przy brakującym/zmienionym originalu.

## Źródło

ERS source-cache:
`/srv/ai-data/knowledge/source-cache/EcuRepairService`

Source revision:
`2e52551e7550448a135d1a844798ce1b53aa432b`

Importer wymaga czystego tracked checkoutu.
Local originals pozostają poza Git i są walidowane po SHA-256/size.

## CASE-0001 originals recovery

Seed wymagał 13 oryginalnych JPEG-ów w `local-originals/`.
Pierwszy realny plan zatrzymał się fail-closed, ponieważ plików fizycznie brakowało.

Oryginały odzyskano z Biblioteki ChatGPT.
Każdy z 13 plików:
- nazwa zgodna z seed;
- byte size zgodny z seed;
- SHA-256 zgodny z seed.

Recovery ZIP:
- SHA-256: `dd739592161db06a4c865d47ed967a3a894ea579165ba14dbaf7ec2c66226523`;
- 13 plików;
- po ekstrakcji `sha256sum -c EXPECTED_SHA256SUMS.txt`: 13/13 PASS.

Safety K3:
- backup `20260925T083648Z`;
- isolated restore: PASS;
- ERS files: 105.

Po backup+restore źródłowy ZIP został usunięty jako redundantny.
Finalny stan `local-originals/`:
13 originals + manifest + README = 15 files.

## Final Stage K po recovery

Finalny K3:
`20260925T083725Z`

Wynik:
- ERS files: 104;
- isolated restore: PASS;
- production_modified=false;
- evidence:
  `/srv/ai-data/backups/stage-k/k3-restore-validation/20260925T083725Z-20260925T083740Z-553498`.

Raw CASE-0001 i CASE-0002 originals są objęte off-host DR.

## Real plan

CLI:
`deploy/stage-l/legacy/seed_cases.py plan`

Wynik:
- status: PASS;
- source revision: `2e52551e7550448a135d1a844798ce1b53aa432b`;
- 2 cases.

CASE-0001:
- artifacts: 17;
- local originals: 13;
- final status: `closed`;
- final work_state: `none`;
- fingerprint:
  `b0e73aeaeea3a46781a64b3385d4fd50e74688faa0fc46f2abcaa8eb623abad2`.

CASE-0002:
- artifacts: 16;
- local originals: 11;
- final status: `open`;
- final work_state: `verifying`;
- fingerprint:
  `f00ddc319c3ce45df491f1c4d96bbb5bb8896ad75a25625b5000c484a8839a70`.

## Isolated native PostgreSQL apply

Uruchomiono tymczasowy PostgreSQL 18 i tymczasowy ObjectStore pod `/tmp`.
Production DB/ObjectStore nie były używane.

Pierwszy apply:
- CASE-0001: `created`, 17 artifacts;
- CASE-0002: `created`, 16 artifacts.

Drugi apply tego samego seeda:
- CASE-0001: `reused`;
- CASE-0002: `reused`;
- brak duplikacji.

Po pierwszym apply:
- cases: 2;
- artifacts: 33;
- artifact versions: 33;
- object files: 33;
- case events: 61.

CASE-0001:
- status: `closed`;
- work_state: `none`;
- row_version: 32;
- event sequence: 1..32, bez luk.

CASE-0002:
- status: `open`;
- work_state: `verifying`;
- row_version: 29;
- event sequence: 1..29, bez luk.

`REAL_LEGACY_APPLY=PASS`.

## Rollback gate

Po isolated apply wykonano:
`alembic downgrade 0003_knowledge_canonical`

Wynik:
- 0 tabel `ers_*`;
- PASS.

`REAL_LEGACY_DOWNGRADE=PASS`.

## Implementacja

Dodano:
- `src/ai_bridge/domains/ers/legacy_seed_schemas.py`;
- `src/ai_bridge/domains/ers/legacy_seed.py`;
- `deploy/stage-l/legacy/seed_cases.py`;
- targeted tests L1.4.

Importer:
- plan jest read-only;
- waliduje path traversal;
- waliduje local_original hash/size;
- tworzy fingerprint seeda;
- zapisuje provenance;
- importuje asset/ECU/symptoms/DTC/steps/repairs/results/artifacts;
- używa wspólnego content-addressed ObjectStore;
- prowadzi lifecycle do stanu końcowego;
- drugi identyczny apply jest idempotentny;
- zmieniony seed dla istniejącego legacy_case_code kończy się konfliktem.

## Testy

Targeted L1.4:
**6/6 PASS**.

Pełny regression suite AI Platform po L1.4:
**PASS 100%**.

Dodatkowo:
- `compileall`: PASS;
- `git diff --check`: PASS;
- real plan CASE-0001/0002: PASS;
- native PostgreSQL apply/reuse/downgrade: PASS.

## Granica produkcyjna

Na koniec dev gate produkcja pozostaje bez zmian:
- active runtime:
  `/opt/ai-platform/releases/stage-j-3b456a56343a`;
- Alembic:
  `0003_knowledge_canonical`;
- production `ers_*` tables: 0.

Nie wykonano:
- production `alembic upgrade 0004`;
- produkcyjnego importu CASE-0001/CASE-0002;
- włączenia ERSAdapter w aktywnym runtime;
- publikacji ERS -> Knowledge.

## Następny krok

Po merge L1.4 potrzebny jest kontrolowany production gate:
1. świeży Stage K backup;
2. `alembic upgrade 0004_ers_core_persistence`;
3. schema verification;
4. deterministic apply CASE-0001/CASE-0002;
5. real Case Store verification;
6. runtime release z ERSAdapter;
7. HTTP smoke;
8. rollback/restore test;
9. final Stage K backup/restore.

L1.4 dev gate sam nie modyfikuje produkcji.
