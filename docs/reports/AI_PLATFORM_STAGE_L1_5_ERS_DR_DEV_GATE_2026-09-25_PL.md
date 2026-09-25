# AI Platform — Stage L1.5 — ERS DR Extension Dev Gate

**Data:** 2026-09-25
**Status:** DEV GATE PASS — PRODUCTION ERS STILL INACTIVE
**Baseline main:** `649a9f9af6f19c98123e8a81e2699d2ebbc92ac7`

## Cel

Rozszerzyć działający Stage K tak, aby aktywny EcuRepairService Case Store był
odtwarzalny razem z PostgreSQL i shared ObjectStore, bez tworzenia równoległego
backup systemu oraz bez uzależnienia ERS od Qdranta.

Kontrakt L1.5:
- PostgreSQL table counts `ers_*` w spójnym Stage K snapshot;
- ERS object-set manifest;
- isolated restore case data + object integrity.

## Architektura

ERS nie dostaje osobnego dumpu PostgreSQL.

Stage K nadal tworzy jeden snapshot:
`AI_Platform/_Shared/PostgreSQL/ai_bridge/<tier>/<backup_id>/ai_bridge.dump`.

Jeżeli w snapshotowanej bazie istnieje `ers_cases`, backup automatycznie:
1. wykrywa pełny zestaw tabel `ers_*`;
2. zapisuje row count każdej tabeli;
3. pobiera dokładny zestaw `ers_artifact_versions` z `availability=available`;
4. weryfikuje lokalny shared ObjectStore SHA-256/size;
5. kopiuje wymagane obiekty do append-only DR poolu;
6. publikuje oddzielny manifest `ERSCaseStore`.

Manifest:
`AI_Platform/ERS/case-store/manifests/<tier>/<backup_id>/`.

DR object pool:
`AI_Platform/ERS/object-store/sha256/<2>/<sha256>`.

Pool ERS na NAS jest projekcją DR. Lokalny PostgreSQL + shared immutable ObjectStore
pozostają source of truth.

## Case integrity boundary

Manifest przechowuje dla każdego case:
- `case_id`;
- `row_version`;
- `event_count`;
- `min_event_seq`;
- `max_event_seq`.

Backup fail-closed wymaga:
- `event_count == row_version`;
- event sequence zaczyna się od 1;
- `max_event_seq == row_version`.

Dodatkowo zapisywane są artifact availability counts oraz liczba referencji do każdego
unikalnego object SHA-256.

## Offline verification

`verify_backup.py` obsługuje nową domenę:
`ERSCaseStore`.

Sprawdza:
- COMPLETE + manifest checksum;
- ten sam shared PostgreSQL dump;
- row counts tabel `ers_*`;
- object-set count/bytes;
- brak duplikatów digestów;
- SHA-256 i byte size każdego obiektu;
- liczbę artifact-version references;
- case event boundaries.

Plaintext secrets nadal nie są częścią tego zestawu.

## Isolated restore

`restore_validate.py` przyjmuje opcjonalnie:
`--ers <ERSCaseStore manifest-set>`.

Gdy dump Knowledge zawiera `ers_*`, brak tego argumentu jest błędem fail-closed.

Pełny restore:
1. tworzy pusty izolowany PostgreSQL;
2. przywraca wspólny dump;
3. odtwarza Knowledge canonical objects;
4. odtwarza ERS object-set do osobnego izolowanego root;
5. sprawdza wszystkie ERS table counts;
6. porównuje case boundaries;
7. porównuje availability counts;
8. porównuje DB object references z manifestem;
9. sprawdza SHA-256/size każdego restored ERS object;
10. kontynuuje pusty Qdrant -> reindex -> Search/RAG/citations/source opening.

Produkcja nie jest modyfikowana.

## K5 / retention

K5 jest kompatybilny z obiema sytuacjami.

Przed aktywacją ERS:
- `ers_set=null`;
- Knowledge/WVC backup i weekly restore działają jak wcześniej.

Po aktywacji ERS:
- daily dodatkowo wykonuje offline verify `ERSCaseStore`;
- weekly przekazuje matching ERS manifest do pełnego restore;
- status K5 zawiera `ers_case_store_verify`.

Retention:
- backup history sprzed ERS może nie mieć ERS manifestu;
- jeżeli Knowledge manifest zawiera `ers_*`, brak matching ERS manifestu blokuje prune;
- paired ERS manifest jest usuwany razem z K2 setem;
- ERS object pool pozostaje append-only, bez automatycznego GC.

## Runtime compatibility

Stage K `release_identity()` akceptuje produkcyjny stage `J` oraz `L`.

Jest to wymagane, aby backup nie przestał działać po L1.6 cutover.
Nie rozszerzono akceptacji na dowolny nieznany stage.

## Gate 1 — real current production schema 0003

Uruchomiono nowy `backup.py` przeciw bieżącej produkcyjnej bazie, ale do lokalnego
validation targetu `--allow-local`.

Backup ID:
`20260925T095810Z`.

Wynik:
- `ers_set=null`;
- Knowledge: PASS;
- WVC: PASS;
- Knowledge canonical objects: 32;
- Knowledge chunks: 566;
- PostgreSQL dump: 36 523 933 B;
- produkcyjny schema pozostaje `0003_knowledge_canonical`.

`PREPROD_0003_COMPAT=PASS`.

Tymczasowy validation target został usunięty.

## Gate 2 — native PostgreSQL 18 / real CASE-0001 + CASE-0002

Utworzono izolowany PostgreSQL 18.

Do niego:
1. przywrócono świeży read-only dump bieżącej produkcji;
2. tylko kopię podniesiono `0003 -> 0004_ers_core_persistence`;
3. skopiowano Knowledge ObjectStore do tymczasowego shared store;
4. zaimportowano realne CASE-0001 i CASE-0002 przez L1.4 deterministic importer;
5. wykonano L1.5 backup do lokalnego validation targetu.

Production PostgreSQL i production ObjectStore nie zostały zmodyfikowane.

Backup ID:
`20260925T100020Z`.

## ERS backup evidence — 0004

Offline ERS verify:
- status: PASS;
- cases: 2;
- `ers_*` tables: 23;
- case events: 61;
- artifacts: 33;
- artifact versions: 33;
- available artifact versions: 33;
- unique object-set: 33;
- object bytes: 10 556 749;
- object references: 33;
- case boundaries: PASS.

Przykładowe domain counts:
- `ers_cases=2`;
- `ers_case_events=61`;
- `ers_artifacts=33`;
- `ers_artifact_versions=33`;
- `ers_ecus=3`;
- `ers_case_ecus=3`;
- `ers_provenance_records=2`.

## Full isolated restore evidence

Evidence:
`/srv/ai-data/backups/stage-k/restore-validation/20260925T100020Z-20260925T100039Z-565014`.

Wynik:
- status: PASS;
- restored schema: `0004_ers_core_persistence`;
- ERS cases: 2;
- ERS objects verified: 33/33;
- ERS object bytes: 10 556 749;
- DB->object references: PASS;
- availability counts: PASS;
- case boundaries: PASS;
- all ERS table counts: PASS;
- Knowledge Qdrant rebuild: 566 points;
- Search results: 8;
- RAG claims: 1;
- RAG citations: 1;
- source opening SHA-256: PASS;
- production Qdrant before/after: unchanged.

Duration: 111.489 s.

## Testy

Targeted L1.5:
**8/8 PASS**.

Zakres:
- inactive schema compatibility;
- ERS metadata snapshot;
- deterministic object copy/reuse;
- incomplete ERS schema fail-closed;
- ERS manifest offline verify;
- full restore requires ERS manifest;
- K5 weekly pairing;
- retention pairing;
- Stage L release identity compatibility.

Pełny AI Platform regression suite:
**PASS 100%**.

`py_compile` / `compileall` / `git diff --check`: wymagane przed commit.

## Granica produkcyjna

L1.5 nie aktywuje ERS.

Na koniec dev gate produkcja nadal:
- runtime: `/opt/ai-platform/releases/stage-j-3b456a56343a`;
- schema: `0003_knowledge_canonical`;
- production `ers_*`: 0;
- PostgreSQL: active;
- AI Bridge: active.

Nie wykonano produkcyjnego:
- `alembic upgrade 0004`;
- importu CASE-0001/CASE-0002;
- runtime cutover do Stage L.

## L1.6 handoff

L1.6 production gate musi wykonać kolejno:
1. świeży pre-cutover Stage K backup/restore na schema 0003;
2. production `alembic upgrade 0004`;
3. deterministic import CASE-0001/0002;
4. real off-host Stage K backup na GlobalNAS z nie-null `ers_set`;
5. offline verify ERS manifest;
6. pełny isolated restore Knowledge + ERS z GlobalNAS;
7. runtime release z ERSAdapter;
8. HTTP smoke API/lifecycle;
9. planowany rollback i smoke poprzedniego Stage J;
10. reactivation Stage L;
11. final backup/restore evidence.

Dopiero ten gate może oznaczyć L1 jako production complete.
