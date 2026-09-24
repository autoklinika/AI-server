# Stage K — Backup / Disaster Recovery / Recovery Validation

Stage K ma zapewnić odtworzenie danych produkcyjnych AI Platform po utracie AI Servera.
Priorytetem jest Knowledge Service, ale backup PostgreSQL obejmuje całą bazę `ai_bridge`,
w tym trwałą historię WVC.

## Niezmienny kontrakt

Źródło prawdy Knowledge Service to:
`PostgreSQL + canonical immutable object store`.

Qdrant pozostaje wyłącznie odbudowywalną projekcją. Snapshot Qdrant może kiedyś
przyspieszać recovery, ale nie może być wymagany do DR.

Aktywny runtime Stage J pozostaje nietknięty:
`/opt/ai-platform/releases/stage-j-3b456a56343a`.

## Gate'y

- K0 — inventory/recovery baseline i klasyfikacja danych.
- K1 — fail-closed transport na dedykowany udział NAS.
- K2 — spójny backup PostgreSQL + canonical objects + manifest + integrity.
- K3 — recovery config oraz szyfrowany bundle sekretów.
- K4 — izolowany realny restore, reindex od zera i Search/RAG/source opening.
- K5 — scheduling, retencja, monitoring, production acceptance i runbook.

## K2 — recovery set

`backup.py` tworzy atomowy recovery set. Dla produkcyjnego targetu wymaga
network filesystem oraz markera `.ai-platform-backup-target.json`.
Lokalny target jest dozwolony tylko z `--allow-local` i nigdy nie jest dowodem DR.

Recovery set zawiera custom-format dump PostgreSQL, canonical objects wskazane
przez snapshot DB, manifest, checksum manifestu i marker `COMPLETE` tworzony na końcu.
Backup używa eksportowanego snapshotu `REPEATABLE READ READ ONLY` i weryfikuje
SHA-256 canonical objects przed i po kopiowaniu.

## Verification

`verify_backup.py` fail-closed sprawdza `COMPLETE`, checksum manifestu, integralność
dumpu przez `pg_restore -l`, rozmiar i SHA-256 każdego canonical object oraz
zgodność liczby i sumy bajtów obiektów.

## K4 — restore validation

`restore_validate.py` nie modyfikuje produkcji. Tworzy pusty izolowany PostgreSQL,
odtwarza canonical object store, uruchamia świeży pusty Qdrant, wykonuje pełny
reindex, Knowledge Search, RAG z claim-level citations i source opening z kontrolą SHA-256.
Production Qdrant jest obserwowany przed/po teście i nie może ulec zmianie.

## K1 — aktualny blocker

NAS `nas-klinika.local` jest osiągalny w LAN jako `192.168.1.15`.
SMB 445/139 odpowiada; NFS i SSH nie są wystawione. Na AI Serverze nie ma jeszcze
mountu NAS, `cifs-utils`, udziału Stage K ani bezpiecznie skonfigurowanych credentials.
Lokalne recovery sety w `/srv/ai-data/backups/stage-k` są wyłącznie walidacją.

## Secrets

Zwykły recovery set ma `secrets_included=false`. Sekrety nie mogą trafiać do
manifestu, logów ani repo. K3 użyje osobnego zaszyfrowanego recovery bundle;
klucz deszyfrujący musi być przechowywany poza AI Serverem i poza NAS.
