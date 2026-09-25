# AI Platform — Stage L1.3 — ERS Case API / Lifecycle Dev Gate

**Data:** 2026-09-25
**Status:** DEV GATE PASS — PRODUCTION SCHEMA STILL 0003
**Baseline main:** `c513169e52ea912c1f807b4b80376ed24be33148`

## Cel

Udostępnić publiczny, transakcyjny API contract ERS dla aktywnego przypadku naprawy,
bez uruchamiania AI diagnosis, bez Knowledge publication i bez bezpośredniego dostępu
do Qdranta/Ollamy.

Zakres L1.3:
- Case create/read/update;
- lifecycle;
- Asset/Vehicle/Machine metadata;
- ECU identity + software/calibration identity;
- symptoms;
- DTC;
- measurements;
- diagnostic steps.

Artifact upload API pozostaje poza tym gate'em.

## API

Prefix:
`/api/v1/ecu-repair`

Endpointy:
- `POST /cases`;
- `GET /cases/{case_id}`;
- `PATCH /cases/{case_id}`;
- `POST /cases/{case_id}/events`;
- `POST /cases/{case_id}/assets`;
- `POST /cases/{case_id}/ecus`;
- `POST /cases/{case_id}/symptoms`;
- `POST /cases/{case_id}/dtcs`;
- `POST /cases/{case_id}/measurements`;
- `POST /cases/{case_id}/diagnostic-steps`.

Każdy request schema ma `schema_version=1` i `extra=forbid`.
Nieznane pola są odrzucane przez Pydantic.

## Concurrency i ETag

`row_version` pozostaje jedynym concurrency tokenem case.

GET/POST/PATCH zwracają:
`ETag: W/"<row_version>"`.

Mutacje istniejącego case wymagają:
`If-Match`.

Brak nagłówka:
- HTTP 428 `if_match_required`.

Niepoprawny format:
- HTTP 400 `invalid_if_match`.

Stale write:
- HTTP 409 `case_version_conflict`.

Append danych diagnostycznych również zwiększa `row_version` i tworzy audit event.
Dzięki temu operator widzi konflikt także wtedy, gdy inny klient dopisał DTC/pomiar,
a nie tylko po zmianie tytułu/statusu.

## Lifecycle

Repository L1.1 nadal wymusza:
- `draft -> open | cancelled`;
- `open -> resolved | cancelled`;
- `resolved -> open | closed`;
- `closed -> open`;
- `cancelled -> terminal`.

`closed -> open` zapisuje event `reopened`.

Nieprawidłowe przejście:
HTTP 409 `invalid_case_transition`.

API nie potrafi zamknąć case przez AI ani wykonać automatycznej decyzji diagnostycznej.

## Intake repository

Dodano transakcyjny `ErsIntakeRepository`.

Każdy append:
1. blokuje case przez `SELECT ... FOR UPDATE` na PostgreSQL;
2. sprawdza oczekiwany `row_version`;
3. zapisuje immutable observation/measurement/step;
4. zwiększa wersję case;
5. zapisuje `ers_case_events` z `event_seq == row_version`;
6. commit następuje atomowo.

Cross-case ECU reference jest odrzucany przed zapisem measurement/DTC.

Diagnostic steps mają monotoniczny `step_seq`, serializowany przez lock case.

## Scope integrity

L1.3 rozszerza także artifact boundary z L1.2:
Artifact nie może wskazać ECU/Asset należącego do innego case.

Walidacja scope odbywa się przed zapisaniem bytes do ObjectStore,
więc niepoprawny request nie pozostawia osieroconego immutable object.

Naprawiono również semantykę nullable JSON measurement value:
`value_json=None` jest SQL NULL, a nie JSON `null`,
co zachowuje DB constraint "exactly one measurement value".

## Error boundary

ERS nie rejestruje globalnego handlera `SQLAlchemy IntegrityError`.

Konflikty constraintów są mapowane wewnątrz endpointów ERS do domenowego
`ErsIntegrityConflict`, a adapter mapuje go na:

HTTP 409 `ers_integrity_conflict`.

Dzięki temu włączenie ERS nie zmienia semantyki błędów WVC/Knowledge/innych domen
i nie ujawnia SQL/constraint details klientowi.

## Targeted validation

L1.1 + L1.2 + L1.3 targeted suite:
**22/22 PASS**.

Sprawdzone m.in.:
- case create/read/PATCH;
- ETag / If-Match;
- stale conflict;
- lifecycle + explicit reopen;
- Asset + ECU;
- DTC, measurement, diagnostic step;
- case-detail reconstruction;
- event sequence;
- cross-case ECU rejection;
- duplicate legacy case conflict;
- ObjectStore regressions;
- ERS adapter nie instaluje globalnego SQLAlchemy handlera.

## Native PostgreSQL 18 gate

Uruchomiono tymczasowy PostgreSQL 18 pod `/tmp`,
bez kontaktu z production DB.

Wynik:
- `alembic upgrade head`: PASS;
- ERS API case create: PASS;
- Asset append: PASS;
- ETag/row_version: PASS;
- dwa równoległe writes na expected `row_version=2`:
  dokładnie 1 success + 1 `ErsCaseVersionConflict`;
- winner kończy z `row_version=3`;
- audit sequence: `[1,2,3]`;
- `alembic downgrade 0003_knowledge_canonical`: PASS;
- po downgrade: 0 tabel `ers_*`.

`NATIVE_POSTGRES_L1_3=PASS`.

## Full regression

Pełny regression suite AI Platform:
**PASS 100%**.

`compileall`: PASS.
`git diff --check`: PASS.

## Granica produkcyjna

W czasie dev gate production pozostaje:
- active runtime: `/opt/ai-platform/releases/stage-j-3b456a56343a`;
- Alembic schema: `0003_knowledge_canonical`;
- production ERS tables: `0`.

ERSAdapter jest na tym etapie opt-in w `create_app(..., domains=(ERSAdapter(),))`.
Domyślna produkcyjna kompozycja nadal instaluje tylko WVC.

## Następny gate

Po merge L1.3 nadal nie wykonujemy production migration.

Kolejność zgodna z Domain Contract v1:
1. **L1.4 — Legacy seed migration**:
   deterministic importer obecnego repo ERS, dry-run, CASE-0001 complete seed,
   CASE-0002 metadata + 11 verified originals, idempotency;
2. **L1.5 — ERS DR extension**:
   Stage K manifest dla tabel `ers_*` i ERS object-set oraz isolated restore;
3. **L1.6 — Production gate**:
   świeży backup, `0004` upgrade, rollback/re-upgrade, runtime activation,
   realny HTTP smoke i finalny backup/restore.

Do końca L1.5 production pozostaje na schema `0003_knowledge_canonical`
i Stage J pozostaje aktywnym runtime.

L1.3 dev gate sam nie zmienia produkcji.
