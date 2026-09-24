# ADR-008 — PostgreSQL production data na niezależnym dysku AI_DATA

**Status:** ACCEPTED / STORAGE PREREQUISITE FOR L1
**Data:** 2026-09-24
**Zakres:** AI Platform / PostgreSQL / ERS durable state / Stage K DR

## Kontekst

AI Server ma dwa fizyczne NVMe 4 TB:

- system: `/dev/nvme1n1p2` -> `/`;
- data: `/dev/nvme0n1p1`, label `AI_DATA_4TB` -> `/srv/ai-data`.

Obecny PostgreSQL 18 `main` używa katalogu
`/var/lib/postgresql/18/main`, czyli dysku systemowego.

Stage L ma dodać trwały Case Store do PostgreSQL. Pozostawienie całego klastra na
dysku systemowym oznaczałoby utratę lokalnego source of truth przy awarii/reinstalacji OS,
mimo że Stage K umożliwia odtworzenie z NAS.

## Decyzja

Przed utworzeniem tabel `ers_*` cały production PostgreSQL cluster zostaje
przeniesiony na:

`/srv/ai-data/platform/postgresql/18/main`

Nie tworzymy osobnej bazy SQLite ani drugiego prywatnego PostgreSQL tylko dla ERS.
WVC, Knowledge i ERS nadal używają jednego zarządzanego PostgreSQL AI Platform.

Konfiguracja Debian PostgreSQL używa drop-in:

`/etc/postgresql/18/main/conf.d/99-ai-platform-data-directory.conf`

z:

`data_directory = '/srv/ai-data/platform/postgresql/18/main'`

Dzięki temu systemowy config może zostać odtworzony po reinstalacji, a właściwe
dane pozostają na niezależnym NVMe.

## DR i backup

Drugi dysk nie zastępuje Stage K.

Warstwy ochrony:
1. lokalny production PostgreSQL na `AI_DATA_4TB`;
2. spójny `pg_dump` Stage K na GlobalNAS;
3. isolated restore validation;
4. config drop-in jest objęty Platform config backup po migracji.

Nie wykonujemy file-level tar backup aktywnego katalogu PostgreSQL.
Stage K pozostaje oparty na spójnym dumpie logicznym i manifestach.

## Migration safety

Migracja wymaga:
- świeżego zweryfikowanego Stage K backup ID;
- zatrzymania AI Bridge przed PostgreSQL;
- zatrzymania klastra;
- `rsync` z zachowaniem ownership/ACL/xattrs;
- checksum dry verification;
- fail-closed rollback do starego katalogu przy błędzie;
- potwierdzenia przez PostgreSQL rzeczywistego `data_directory`;
- pozostawienia starej kopii jako jawnego krótkoterminowego rollback point.

Aktywny Stage J release nie jest przebudowywany przez tę operację.
