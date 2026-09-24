# AI Platform — Stage K K3 Recovery Acceptance

Data: 2026-09-24
Status: K3 DATA PASS / ENCRYPTED SECRETS BACKUP PASS

## Zakres

K3 zabezpiecza dane i konfigurację poza głównym recovery setem Knowledge/WVC:
- EcuRepairService (ERS);
- Hermes durable state;
- lokalną konfigurację hosta potrzebną do recovery;
- sekrety w osobnym zaszyfrowanym bundle.

GitHub ani żadne zewnętrzne repozytorium nie jest elementem backupu lub restore ERS.

## ERS

Źródło lokalne: `/srv/ai-data/knowledge/source-cache/EcuRepairService`

Backup ID: `20260924T165315Z`

Manifest: `/mnt/AI_Platform/ERS/manifests/manual/20260924T165315Z`

Snapshot: 65 plików, archive 34 291 644 B. `.git`, cache i środowiska wykonawcze są wykluczone; secrets nie są dołączane.

Backup zawiera również lokalny, niezatwierdzony jeszcze plik:
`cases/CASE-0002-SCANIA-EMS-S6-DC1210-ECU-CLONE/first_block_analysis.md`

Jego SHA-256 w manifeście: `64f1a25a6a4a2477ae71ca7d213a18db99fbbf0411aae4a05cff37ebf9ed25d8`.

ERS restore validation: PASS.

Finalne manifesty ERS/Hermes/Platform wskazują implementację Stage K: `12b27ba1e8f77e0acefeccbe82ea8cd582ac7c87`.

## Hermes

Ten sam backup ID: `20260924T165315Z`

Manifest: `/mnt/AI_Platform/Hermes/manifests/manual/20260924T165315Z`

Jawny durable snapshot: 367 plików, archive 2 771 797 B. Obejmuje memories, skills, pending messages, hooks/plugins/scripts, gateway/session state oraz konfigurację bez sekretów.

Pięć aktywnych baz SQLite jest backupowanych przez SQLite Backup API, a nie przez surowe kopiowanie aktywnych plików/WAL:
- state.db;
- kanban.db;
- response_store.db;
- runs_idempotency.db;
- cron/executions.db.

Każda kopia SQLite przeszła `PRAGMA quick_check = ok`.

Pierwsza próba K3 zatrzymała się fail-closed przed publikacją COMPLETE, ponieważ SQLite Backup API pisał bezpośrednio do CIFS. Nieukończone evidence pozostawiono pod `.incomplete`.

Mechanizm poprawiono na: `SQLite Backup API -> lokalny frozen DB -> quick_check/SHA-256 -> GlobalNAS`.

Końcowy Hermes restore validation: PASS dla wszystkich pięciu SQLite.

## Platform config

Manifest: `/mnt/AI_Platform/Platform/manifests/manual/20260924T165315Z`

Snapshot obejmuje 16 lokalnych plików konfiguracyjnych hosta, w tym systemd units i drop-ins dla AI Bridge, AI Gateway, ComfyUI, Ollama, Hermes oraz `/etc/fstab`.

Jawny config snapshot nie zawiera `.env`, `auth.json`, kluczy ani credentials.

Izolowany K3 restore evidence: `/srv/ai-data/backups/stage-k/k3-restore-validation/20260924T165315Z-20260924T165332Z-435131`

Wynik: ERS 65 plików; Hermes 367 plików; Hermes SQLite 5/5 quick_check ok; Platform config 16 plików; production_modified=false; status PASS.

## Encrypted secrets recovery bundle

Backup ID: `20260924T164644Z`

Bundle: `/mnt/AI_Platform/Platform/secrets/manual/20260924T164644Z/secrets.tar.gz.age`

Format: `age-encryption.org/v1`

Bundle: 8 914 B; SHA-256 `cd15b951a2d1ad71f89669fa12317f60f1f682445261d0d09247d93a0743e01a`.

Źródła secrets obejmują AI Bridge env, AI Gateway env, Hermes env, Hermes auth state, GlobalNAS backup credential oraz Hermes pairing directory, jeżeli zawiera dane.

Szyfrowanie odbywa się strumieniowo: `tar -> age -> GlobalNAS`. Nie jest tworzony plaintextowy tar ani plaintextowy plik pośredni na NAS.

Recipient to istniejący klucz SSH Ed25519 `x1carbon-ai-server`.
Fingerprint: `SHA256:BVPwRUzB0IbP/6QVNsy9/XbIxs8MxHxbvFJ6soFNUPM`.

AI Server oraz GlobalNAS przechowują wyłącznie publiczny recipient. Prywatny klucz recovery pozostaje poza AI Serverem i poza NAS.

Offline encrypted bundle verification: PASS.

## Granica testu secrets

K3 celowo nie kopiuje prywatnego klucza SSH na AI Server tylko po to, aby wykonać self-decrypt. Byłoby to osłabieniem DR security model.

Dlatego K3 dowodzi poprawnego szyfrowania do właściwego publicznego recipienta, integralności encrypted bundle, kompletności listy źródeł, braku plaintext secrets na NAS oraz braku private key na AI Serverze/NAS.

Rzeczywisty decrypt/restore secrets należy wykonać z zewnętrznego recovery workstation posiadającego prywatny klucz podczas K5 replacement-host drill.

## Wniosek

K3 durable data/config = PASS.
K3 encrypted secrets backup = PASS.
K3 external-key decrypt drill = wymagany w K5, nie na produkcyjnym AI Serverze.

Stage K pozostaje otwarty dla K5: scheduling, retencja, monitoring, runbook całego hosta i finalny replacement-host/recovery drill.
