# AI Platform — Stage L storage prerequisite

**Data:** 2026-09-24
**Status:** POSTGRESQL DATA-DISK MIGRATION COMPLETE; CASE-0002 RAW IMPORT PENDING

## Cel

Przed utworzeniem aktywnego ERS Case Store usunąć zależność source of truth od
dysku systemowego oraz zamknąć wykryte luki trwałego storage.

## Fizyczny layout

- system: `/dev/nvme1n1p2` -> `/`;
- data: `/dev/nvme0n1p1` -> `/srv/ai-data`, label `AI_DATA_4TB`;
- GlobalNAS: off-host Stage K DR.

PostgreSQL 18/main został przełączony z:
`/var/lib/postgresql/18/main`

na:
`/srv/ai-data/platform/postgresql/18/main`.

Migration script zakończył się `POSTGRES_RELOCATE=PASS`.

## Rollback point

Stary cluster nie został usunięty.

Retired source:
`/var/lib/postgresql/18/main.pre-ai-data-20260924T202938Z`

Systemowy `/var/lib/postgresql/18/main` jest obecnie tylko stubem z markerem,
aby przypadkowe uruchomienie starego katalogu fail-closed.

Jawny rollback pozostaje dostępny przez:
`deploy/stage-l/storage/rollback_postgresql_to_system_disk.sh`.

## Runtime verification

Po migracji:
- `postgresql@18-main.service=active`;
- `ai-bridge.service=active`;
- AI Bridge health: `status=ok`, `database=ok`;
- AI Gateway: `status=ok`, `ollama=ok`;
- Resource Manager: active=0, queued=0;
- baza `ai_bridge`: 452 MB;
- Knowledge: 32 documents / 566 chunks.

`pg_lsclusters` wskazuje data directory:
`/srv/ai-data/platform/postgresql/18/main`.

## Stage K po migracji

Manual K2 backup:
`20260924T203146Z`

Offline verification:
- PostgreSQL dump: 36 523 933 B;
- canonical objects: 32;
- Knowledge versions: 32;
- Knowledge chunks: 566;
- status: `PASS`.

Pełny isolated restore z tego backupu:
- empty isolated PostgreSQL;
- empty isolated Qdrant;
- restore counts zgodne z produkcją;
- reindex: 32 completed / 0 failed;
- Qdrant: 566 points;
- Search: 8 results;
- RAG: 1 claim / 1 citation;
- source opening SHA-256 verified;
- production Qdrant: 566 before / 566 after;
- status: `PASS`.

Evidence:
`/srv/ai-data/backups/stage-k/restore-validation/20260924T203146Z-20260924T203212Z-468700`.

## K3 po migracji

Manual K3 backup:
`20260924T203444Z`

Wynik:
- ERS: 75 files;
- Platform config: 17 files;
- corpus v0 package: 33 041 109 B, SHA-256 verified;
- PostgreSQL data-directory drop-in: included and SHA-256 verified;
- Hermes durable state: included;
- isolated K3 restore: `PASS`;
- `production_modified=false`.

## Automotive Semiconductor Corpus v0

22 OEM PDF-y nie są już zależne od `/tmp`.

Trwały lokalny pakiet:
`/srv/ai-data/knowledge/source-cache/EcuRepairService/sources/automotive-semiconductor-corpus-v0/local/corpus-v0-source-package.tar.gz`

SHA-256:
`8d657eaf510e264004a806e9973b8684af846024ebe10ffe680334a5f46650ba`

Pakiet jest lokalnie wykluczony z Git i objęty Stage K/GlobalNAS.

## CASE-0002 originals

W Bibliotece ChatGPT odzyskano:
- 2 pełne Flash MPC555;
- 2 EEPROM 25C256;
- read-back `po klonie.bin`;
- 6 oryginalnych zdjęć ECU/MCU.

Łącznie: 11 plików.

Pakiet recovery ma SHA-256:
`36d42e2899b10914c35db9de86fe0012becd2a4ce6d57b1718f9d8981e6d7bba`.

Na drugim NVMe przygotowano intake:
`.../CASE-0002-SCANIA-EMS-S6-DC1210-ECU-CLONE/local-originals/`

z serwerowym `EXPECTED_SHA256SUMS.txt`.
Surowe pliki nie są commitowane do GitHub.

Pozostający warunek przed L1:
- skopiować recovery ZIP na AI Server;
- uruchomić fail-closed importer;
- uzyskać 11/11 SHA-256 PASS;
- wykonać K3 backup + restore validation obejmujący te 11 originals.

Do tego momentu L1 pozostaje zablokowane.
