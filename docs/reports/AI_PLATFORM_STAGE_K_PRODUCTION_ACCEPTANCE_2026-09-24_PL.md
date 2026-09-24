# AI Platform — Stage K Production Acceptance

Data: 2026-09-24

Status: **PRODUCTION COMPLETE — backup/DR data plane**

Świadomie odroczony hardening: wybór docelowego, niezależnego recovery key dla encrypted secrets oraz external-key decrypt drill. Nie blokuje to backupu i odtworzenia Knowledge/WVC/ERS/Hermes/Platform config.

## 1. Zakres

Stage K wdrożył realny backup poza AI Serverem na GlobalNAS, spójny PostgreSQL + canonical object recovery model, osobne domeny Knowledge/WVC/ERS/Hermes/Platform, encrypted secrets bundle bez plaintextu na NAS, realne restore validation, retencję, monitoring, user-systemd scheduling oraz Telegram transition-only alerting.

Aktywny runtime aplikacyjny pozostał: `/opt/ai-platform/releases/stage-j-3b456a56343a`.

Stage K nie przełączał ani nie przebudowywał produkcyjnego Stage J.

## 2. GlobalNAS

NAS: `GlobalNAS / globalnas.local / 192.168.1.79`

Udział: `//globalnas.local/AI_Platform`

Mount: `/mnt/AI_Platform`

Transport: CIFS / SMB 3.1.1, dedykowane konto `ai_backup`, guest denied, trwały mount przez `/etc/fstab`, credentials poza repo, marker `.ai-platform-backup-target.json`, brak lokalnego fallbacku udającego DR.

Finalny monitor raportował około 7.78 TB wolnego miejsca.

## 3. Knowledge/WVC

Źródło prawdy Knowledge: `PostgreSQL ai_bridge + canonical immutable object store`.

Qdrant pozostaje wyłącznie odbudowywalną projekcją.

Pierwszy realny NAS restore:
- backup ID `20260924T152707Z`;
- pusty PostgreSQL;
- pusty Qdrant;
- reindex 32 dokumentów;
- 566 punktów;
- Search PASS;
- RAG PASS;
- claim-level citation PASS;
- source opening/SHA-256 PASS;
- source Qdrant snapshot used: false;
- duration: 110.318 s.

## 4. ERS / Hermes / Platform config

Finalny K3 set: `20260924T165315Z`.

ERS: 65 plików, backup niezależny od GitHub; lokalne niezatwierdzone dane również objęte snapshotem.

Hermes: 367 plików durable state, 5 baz SQLite, mechanizm `SQLite Backup API -> lokalny frozen DB -> quick_check/SHA-256 -> GlobalNAS`; wszystkie 5/5 quick_check PASS.

Platform config: 16 plików lokalnej konfiguracji hosta, obejmujących AI Bridge/Gateway, Ollama, ComfyUI, Hermes, systemd i fstab; bez plaintext secrets.

K3 isolated restore: `production_modified=false`, status PASS.

## 5. Secrets

Encrypted bundle: `20260924T164644Z`, format `age-encryption.org/v1`.

Plaintext nie jest zapisywany na NAS, plaintextowy tar nie jest tworzony jako plik pośredni, private key nie znajduje się na AI Serverze ani GlobalNAS, encrypted bundle verification PASS.

Obecny recipient jest zachowany jako działające evidence. Operator odroczył decyzję o docelowym recovery identity niezależnym od laptopa. Automatyzacja secrets pozostaje wyłączona do tej decyzji.

## 6. K5 automatyzacja

User-systemd użytkownika `harrypotter`, z `Linger=yes`.

Timery produkcyjne:
- Mon..Sat 02:30 — daily backup + verify;
- Sun 02:30 — weekly backup + verify + real restore;
- hourly — backup/DR monitor.

Finalny runtime daily smoke z `main`:
- main SHA: `146804a58bde03b2b8092e2794c117215d15e6c5`;
- Knowledge ID: `20260924T175014Z`;
- domain ID: `20260924T175020Z`;
- duration: 10.994 s;
- systemd Result=success;
- status PASS.

Finalny runtime weekly smoke przez user-systemd:
- Knowledge ID: `20260924T175046Z`;
- domain ID: `20260924T175052Z`;
- duration: 125.048 s;
- systemd Result=success;
- status PASS.

Weekly Knowledge restore:
- duration: 109.877 s;
- fresh Qdrant rebuilt to 566 points;
- RAG claims: 1;
- citations: 1;
- status PASS.

Weekly domain restore:
- ERS files: 65;
- Hermes files: 367;
- Hermes SQLite: 5/5 ok;
- Platform config files: 16;
- production_modified=false;
- status PASS.

## 7. Retencja

Automatyczna retencja:
- 30 daily;
- 12 weekly;
- manual untouched;
- secrets untouched;
- canonical pool GC disabled/append-only.

Syntetyczny real delete test utworzył 3 daily + 3 weekly. Przy `keep=2` najstarsze sparowane K2/K3 zostały usunięte, a manual set pozostał. Wynik: `RETENTION_DELETE_TEST=PASS`.

## 8. Monitoring

Finalny monitor:
- mount GlobalNAS: PASS;
- marker: PASS;
- freshest backup age: 0.008 h;
- weekly age: 0.008 h;
- issues: [];
- status: PASS;
- secrets recovery key decision: DEFERRED_NON_BLOCKING.

Alarm Telegram działa transition-only: jeden komunikat przy przejściu do FAIL i jeden po recovery. Awaria notifiera nie może zmienić wyniku backupu.

Podczas K5 wykryto dokładnie taki błąd notifiera. Backup i restore były poprawne, ale notifier zmienił końcową semantykę runu. Naprawiono to w `3713b344afce167d205beb14f3aadb1bbc28a8ed`: notifier jest best-effort i działa przez interpreter Python.

## 9. CI / PR / merge

Stage K feature PR:
- PR #82;
- platform-ci PASS;
- merge commit `7d4aece148d02cf039ffae7c5cf6728df5bd6f41`;
- post-merge CI PASS.

K5 user-bus hotfix:
- PR #83;
- platform-ci PASS;
- merge commit `146804a58bde03b2b8092e2794c117215d15e6c5`;
- post-merge CI PASS.

## 10. RPO / RTO

RPO automatycznych danych: **<= 24 h**.

Zmierzony pełny Knowledge restore dla obecnego corpus: około **110 s**.

Target Knowledge data plane: **RTO <= 1 h** po przygotowaniu bazowego hosta/runtime.

Target całego replacement host: **RTO <= 4 h** — do zmierzenia przy przyszłym pełnym replacement-host drill.

## 11. Recovery i rollback

Główny runbook: `docs/runbooks/AI_PLATFORM_STAGE_K_DR_RUNBOOK_PL.md`

Secrets runbook: `docs/runbooks/AI_PLATFORM_STAGE_K_SECRETS_RECOVERY_PL.md`

Rollback automatyzacji: `deploy/stage-k/uninstall_k5_user_services.sh`

Rollback nie usuwa backupów, manifestów, evidence ani statusów.

## 12. Definition of Done

Potwierdzono:
1. backup z GlobalNAS;
2. restore PostgreSQL do pustego środowiska;
3. restore canonical objects;
4. DB ↔ object consistency;
5. pusty Qdrant i pełny reindex;
6. Knowledge Search;
7. RAG;
8. claim-level citations;
9. source opening;
10. brak zależności DR od starego Qdranta;
11. ERS/Hermes/config recovery;
12. monitoring, retencję i automatyczny scheduler.

**Stage K = PRODUCTION COMPLETE dla backup/DR data plane.**

Docelowy recovery-key lifecycle i external-key decrypt drill pozostają zapisanym, świadomie odroczonym security hardeningiem.
