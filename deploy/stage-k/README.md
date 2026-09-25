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

`backup.py` tworzy spójny backup o wspólnym `backup_id`. Dla produkcyjnego targetu
wymaga network filesystem oraz markera `.ai-platform-backup-target.json`. Lokalny
target jest dozwolony tylko z `--allow-local` i nigdy nie jest dowodem DR.

Jedna fizyczna kopia PostgreSQL trafia do `_Shared/PostgreSQL/ai_bridge/`. Knowledge
i WVC publikują osobne manifesty wskazujące ten sam snapshot DB. Canonical objects
trafiają do przyrostowego, content-addressed poolu `Knowledge/canonical-objects/`;
już istniejące obiekty są weryfikowane i używane ponownie zamiast ponownego kopiowania.
Manifest, jego checksum i marker `COMPLETE` są publikowane dopiero po weryfikacji.
Backup używa eksportowanego snapshotu `REPEATABLE READ READ ONLY`.

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

Docelowy NAS to `GlobalNAS` / `globalnas.local` (`192.168.1.79`).
SMB 445/139 odpowiada. Na AI Serverze nie ma jeszcze mountu NAS ani `cifs-utils`.
Anonimowa sesja SMB jest możliwa, ale enumeracja udziałów jest zabroniona przez NAS,
dlatego nazwa udziału i credentials muszą pochodzić z rzeczywistej konfiguracji.

Na wybranym udziale powstaje root `AI_Platform/`, a backupy są rozdzielane według
źródeł: `Knowledge/`, `WVC/`, `ERS/`, `Hermes/`, `Platform/`, `CRT/`.
Wspólna baza `ai_bridge` jest przechowywana tylko raz w
`AI_Platform/_Shared/PostgreSQL/ai_bridge/`; manifesty domen wskazują właściwy
snapshot DB.

System backupu Stage K nie używa GitHub jako elementu DR.
Lokalne recovery sety w `/srv/ai-data/backups/stage-k` są wyłącznie walidacją.

## Secrets

Zwykły recovery set ma `secrets_included=false`. Sekrety nie mogą trafiać do
manifestu, logów ani repo. K3 użyje osobnego zaszyfrowanego recovery bundle;
klucz deszyfrujący musi być przechowywany poza AI Serverem i poza NAS.

## K1/K2/K4 — NAS acceptance

2026-09-24 pierwszy rzeczywisty recovery set na `//globalnas.local/AI_Platform` przeszedł offline verification i pełny izolowany restore Knowledge. Backup `20260924T152707Z` odbudował pusty PostgreSQL i pusty Qdrant do 566 punktów oraz przeszedł Search/RAG/citations/source opening bez snapshotu produkcyjnego Qdranta.

Evidence: `docs/reports/AI_PLATFORM_STAGE_K_NAS_RECOVERY_ACCEPTANCE_2026-09-24_PL.md`.

K1 = PASS, K2 Knowledge/WVC = PASS, K4 Knowledge = PASS. Stage K pozostaje otwarty dla K3 i K5.

## K3 — ERS / Hermes / Platform config / secrets

`k3_domains.py` tworzy osobne backupy domenowe pod `AI_Platform/ERS/`, `AI_Platform/Hermes/` i `AI_Platform/Platform/config/`. ERS jest snapshotem lokalnych danych bez `.git`; GitHub nie jest elementem backupu. Hermes SQLite jest kopiowany przez SQLite Backup API do lokalnego frozen DB, weryfikowany `quick_check`/SHA-256 i dopiero wtedy publikowany na GlobalNAS.

`k3_secrets_backup.sh` tworzy osobny encrypted bundle `age` pod `AI_Platform/Platform/secrets/`. Plaintext nie jest zapisywany na NAS ani do pliku tymczasowego. Nowe bundle są szyfrowane do zaakceptowanych recipientów `age-plugin-yubikey`; prywatny klucz PIV pozostaje sprzętowo w YubiKey, a do automatycznego szyfrowania potrzebny jest wyłącznie publiczny recipient. Polityka recipientów jest fail-closed i obsługuje wiele YubiKeyów.

`k3_secrets_verify.py` weryfikuje manifest, SHA-256, nagłówek `age`, listę źródeł i recipientów oraz brak nieoczekiwanych plików w secrets set. Zachowana jest kompatybilność weryfikacji z historycznymi bundle `ssh-ed25519`. Prywatny materiał recovery nie jest zapisywany na AI Serverze ani GlobalNAS.

Runbook: `docs/runbooks/AI_PLATFORM_STAGE_K_SECRETS_RECOVERY_PL.md`.

## K3 acceptance

Finalny K3 recovery set `20260924T165315Z` na GlobalNAS przeszedł weryfikację ERS/Hermes/Platform config oraz izolowany restore. ERS: 65 plików; Hermes: 367 plików + 5 spójnych SQLite; Platform config: 16 plików.

Encrypted secrets bundle `20260924T164644Z` przeszedł offline verification. Nie zawiera plaintext secrets, a private recovery key nie znajduje się na AI Serverze ani GlobalNAS.

K3 data/config = PASS. K3 encrypted secrets backup = PASS. Rzeczywisty external-key decrypt drill pozostaje elementem K5.

## K5 — scheduling / retention / monitoring

Automatyczny backup jest rozdzielony na dwa poziomy:
- `daily`: poniedziałek–sobota o 02:30; backup + pełna weryfikacja integralności;
- `weekly`: niedziela o 02:30; backup + pełna weryfikacja + izolowany restore Knowledge oraz ERS/Hermes/Platform config.

Retencja: 30 daily + 12 weekly. Zestawy `manual` i encrypted secrets nie są usuwane automatycznie. Canonical object pool pozostaje append-only; automatyczny GC jest celowo wyłączony, żeby retencja nie mogła usunąć obiektu potrzebnego do recovery.

`k5_run.py` zapisuje stan do `/srv/ai-data/platform/backup-status/stage-k/{daily,weekly}.json`. `k5_monitor.py` działa co godzinę, kontroluje mount/marker GlobalNAS, świeżość backupu, świeżość weekly restore i wolne miejsce. Telegram alarm jest wysyłany tylko przy zmianie stanu na FAIL oraz jednokrotnie po recovery.

Timery są user-systemd użytkownika `harrypotter`; host ma `Linger=yes`, więc nie wymagają otwartego terminala ani aktywnej sesji. Instalacja: `install_k5_user_services.sh`; rollback scheduler/monitoringu: `uninstall_k5_user_services.sh` — bez usuwania backupów, evidence i statusów.

Automatyzacja secrets pozostaje `DEFERRED` do decyzji o docelowym recovery key i nie blokuje backupów danych K5.

## Stage K production completion

2026-09-24 Stage K przeszedł finalny production gate. Daily i weekly user-systemd services uruchomione z `main` zakończyły się `Result=success`; weekly wykonał pełny Knowledge restore i K3 domain restore. Hourly monitor jest aktywny, wszystkie trzy timery są enabled, a monitor raportuje `status=PASS`.

Raport: `docs/reports/AI_PLATFORM_STAGE_K_PRODUCTION_ACCEPTANCE_2026-09-24_PL.md`.

**Stage K = PRODUCTION COMPLETE dla backup/DR data plane.** Docelowy recovery-key lifecycle pozostaje świadomie odroczonym hardeningiem.


## L1.5 — ERS Case Store DR extension

Stage K obsługuje aktywny ERS Case Store bez tworzenia drugiego dumpu PostgreSQL.
Gdy schema produkcyjna zawiera `ers_cases`, `backup.py` automatycznie dodaje:

- pełne row counts wszystkich tabel `ers_*` do wspólnego snapshotu PostgreSQL;
- manifest `ERSCaseStore` pod
  `AI_Platform/ERS/case-store/manifests/<tier>/<backup_id>/`;
- dokładny object-set wszystkich `ers_artifact_versions` o
  `availability=available`;
- case boundaries: UUID, `row_version`, liczba eventów oraz min/max `event_seq`;
- availability counts dla artifact versions.

Obiekty ERS są kopiowane do append-only DR poolu:
`AI_Platform/ERS/object-store/sha256/<2>/<sha256>`.
Jest to projekcja DR wspólnego lokalnego ObjectStore; PostgreSQL + lokalny shared
ObjectStore pozostają źródłem prawdy.

Przed migracją produkcji do schema `0004` mechanizm jest kompatybilny wstecz:
`ers_set=null`, a dotychczasowy Knowledge/WVC backup działa bez zmian.

`verify_backup.py` dla `ERSCaseStore` sprawdza wspólny dump PostgreSQL,
domain table counts, manifest object-set, byte size, SHA-256, liczbę referencji
oraz case event boundaries.

`restore_validate.py --ers <manifest-set>` odtwarza ten sam wspólny dump do
izolowanego PostgreSQL, odtwarza ERS object-set do izolowanego katalogu i sprawdza:
table counts, case boundaries, availability counts, DB->object references oraz
SHA-256/size każdego obiektu. Następnie ten sam restore kontynuuje normalny
Knowledge reindex/Search/RAG/source-opening gate.

Jeżeli dump Knowledge zawiera jakiekolwiek `ers_*`, pełny restore bez odpowiadającego
manifestu `ERSCaseStore` kończy się fail-closed.

K5:
- daily: backup + offline verify ERS, jeżeli ERS jest aktywny;
- weekly: dodatkowo pełny isolated Knowledge + ERS restore;
- retention usuwa sparowany manifest ERS razem z K2 setem, ale object pool pozostaje
  append-only i nie ma automatycznego GC.
