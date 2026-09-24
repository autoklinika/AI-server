# AI Platform — Stage L1.1 — ERS Persistence Foundation Dev Gate

**Data:** 2026-09-24
**Status:** DEV GATE PASS — PRODUCTION MIGRATION NOT APPLIED
**Baseline main:** `6d28379402cb5e0dbf4f157dfd4ea8f73837cd3d`

## Cel

L1.1 tworzy trwały model relacyjny EcuRepairService zgodny z kontraktem L0,
bez uruchamiania API ERS, bez migracji legacy cases i bez zmiany aktywnego runtime.

Source of truth pozostaje:
`PostgreSQL ers_* + immutable Object Store`.

Knowledge/Qdrant nie są używane jako storage przypadku naprawy.
## Implementacja

Dodano migrację:
`0004_ers_core_persistence`

Rewizja:
`0003_knowledge_canonical -> 0004_ers_core_persistence`.

Alembic metadata rejestruje ERS jako osobną domenę.
Migracja tworzy 23 tabele `ers_*`, łącznie z technicznym
`ers_case_counters` dla atomowego numerowania czytelnych case codes.

PostgreSQL używa natywnego UUID i JSONB.
SQLite pozostaje backendem testowym bez zmiany kontraktu produkcyjnego.
## Core schema

Case/audit:
- `ers_case_counters`;
- `ers_cases`;
- `ers_case_events`.

Asset/ECU:
- `ers_assets`, `ers_asset_revisions`, `ers_case_assets`;
- `ers_ecus`, `ers_case_ecus`;
- `ers_ecu_identity_observations`;
- `ers_ecu_software_observations`.

Workshop diagnostics:
- `ers_symptoms`;
- `ers_dtcs`;
- `ers_measurements`;
- `ers_diagnostic_steps`;
- `ers_hypotheses`;
- `ers_hypothesis_evidence`.
Repair/evidence/artifacts:
- `ers_repair_actions`;
- `ers_case_results`;
- `ers_provenance_records`;
- `ers_provenance_edges`;
- `ers_evidence`;
- `ers_artifacts`;
- `ers_artifact_versions`.

L2 binary analysis tables, L3 publication tables i L4 diagnosis runs
nie zostały przedwcześnie utworzone.
## Case identity i concurrency

Techniczne PK: UUID.

Czytelny case code:
`CASE-000001`, `CASE-000002`, ...

Numer jest przydzielany atomowo przez rekord licznika w tej samej transakcji.
Nie koduje producenta, ECU ani DTC.

`row_version` zapewnia optimistic concurrency.
Każda mutacja nagłówka/lifecycle zwiększa wersję i tworzy audit event
o `event_seq == row_version`.

Stary klient z nieaktualnym `row_version` kończy się fail-closed
`ErsCaseVersionConflict`.
## Lifecycle

W repository wymuszono przejścia:

`draft -> open | cancelled`
`open -> resolved | cancelled`
`resolved -> open | closed`
`closed -> open`
`cancelled -> terminal`

`closed -> open` generuje jawny event `reopened`.

Work state jest niezależny od lifecycle i walidowany względem kontraktu L0.
AI nie uczestniczy w tej warstwie.
## Evidence/provenance

Model utrzymuje jawne relacje:
case -> asset/ECU -> measurement/artifact -> evidence -> hypothesis.

Evidence może wskazywać stabilne Knowledge IDs:
`document_id/version_id/chunk_id`, ale nie Qdrant point ID.

ArtifactVersion ma:
- immutable version number;
- byte size;
- availability;
- SHA-256 reference;
- provenance;
- derivation parent.

Dla `availability=available` baza wymaga obecności SHA-256.
## Walidacja

Targeted tests L1.1:
**7/7 PASS**.

Sprawdzone:
- migration upgrade/downgrade;
- seed case counter;
- monotonic case IDs;
- creation audit event;
- lifecycle + explicit reopen;
- stale-write rejection;
- mutable case-header update z audit event;
- evidence graph relations;
- available artifact wymaga hash.

Schema drift po `upgrade head`:
`[]` — PASS.
PostgreSQL offline DDL:
- 419 linii;
- `CREATE TABLE ers_cases`: obecne;
- UUID: obecne;
- JSONB: obecne;
- PASS.

Native PostgreSQL 18 gate wykonano na tymczasowym klastrze w `/tmp`
z UTF8/C.UTF-8, bez połączenia z production DB:
- `alembic upgrade head`: PASS;
- 23 tabele ERS: PASS;
- `ers_cases.id`: native `uuid`;
- `ers_cases.metadata`: native `jsonb`;
- repository create: `CASE-000001`;
- lifecycle `draft -> open`: PASS;
- `alembic downgrade 0003_knowledge_canonical`: PASS;
- po downgrade: 0 tabel `ers_*`.

Pełny regression suite AI Platform:
**PASS 100%**.

`git diff --check` i `compileall`: PASS.

## Granica bezpieczeństwa

Nie wykonano:
- `alembic upgrade` na production PostgreSQL;
- zmian runtime Stage J;
- seed/import CASE-0001/CASE-0002 do Case Store;
- API ERS;
- ObjectStore upload API;
- Knowledge publication.

L1.1 jest gotowe do review/merge jako persistence foundation.
