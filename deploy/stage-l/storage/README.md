# Stage L storage prerequisite

Cel: przed L1 przenieść production PostgreSQL z dysku systemowego na niezależny
`AI_DATA_4TB`, bez tworzenia drugiego systemu bazodanowego.

Docelowy katalog:

`/srv/ai-data/platform/postgresql/18/main`

Wymagany jest świeży, zweryfikowany manualny backup Stage K. Dla audytu z
2026-09-24 przygotowano backup `20260924T194340Z`.

## Migracja

Z aktualnego `main`:

```bash
sudo bash deploy/stage-l/storage/relocate_postgresql_to_ai_data.sh 20260924T194340Z
sudo bash deploy/stage-l/storage/verify_postgresql_data_disk.sh
```

Skrypt zatrzymuje tylko AI Bridge i PostgreSQL na czas kopiowania, a przy błędzie
próbuje automatycznie wrócić do starego katalogu.

Po PASS należy wykonać nowy manualny Stage K K3 backup, aby drop-in PostgreSQL
znalazł się w backupie Platform config.

Stary katalog jest zachowany jako:

`/var/lib/postgresql/18/main.pre-ai-data-<timestamp>`

i służy jako krótki rollback point. Nie jest już production source of truth.

## Jawny rollback po udanej migracji

```bash
sudo bash deploy/stage-l/storage/rollback_postgresql_to_system_disk.sh \
  /var/lib/postgresql/18/main.pre-ai-data-<timestamp>
```

Kopia na drugim dysku nie jest kasowana przez rollback.

## Granica

GitHub przechowuje tylko skrypty, migracje i dokumentację. PostgreSQL data directory,
raw ECU artifacts i runtime Case Store nigdy nie są commitowane do repo.

## CASE-0002 — import odzyskanych oryginałów

Zweryfikowany pakiet `CASE-0002_originals_verified.zip` zawiera 5 binarek i 6 zdjęć.
Nie trafia do GitHub.

Po skopiowaniu ZIP-a na AI Server uruchom:

```bash
bash deploy/stage-l/storage/import_case0002_originals.sh /sciezka/do/CASE-0002_originals_verified.zip
```

Importer fail-closed sprawdza SHA-256 całego ZIP-a, a następnie każdy z 11 plików
względem serwerowego `EXPECTED_SHA256SUMS.txt`. Dopiero zweryfikowane pliki trafiają do
`local-originals/` na `AI_DATA_4TB`.

Po `CASE0002_IMPORT=PASS` należy wykonać nowy K3 backup i isolated restore validation.
Dopiero po tym źródłowy ZIP można usunąć.
