# AI Platform — Stage K Disaster Recovery Runbook

Data: 2026-09-24

## 1. Cel

Runbook opisuje backup, monitoring i recovery AI Platform po utracie danych lub
całego AI Servera. Priorytetem pozostaje Knowledge Service.

Źródło prawdy Knowledge:
`PostgreSQL ai_bridge + canonical immutable object store`.

Qdrant jest odbudowywalną projekcją i nie jest wymagany do DR.

## 2. GlobalNAS

Udział:
`//globalnas.local/AI_Platform`

Mount:
`/mnt/AI_Platform`

Backup jest fail-closed: brak poprawnego CIFS mountu/markera powoduje FAIL,
a nie lokalny fallback.

## 3. Automatyczny harmonogram

User systemd użytkownika `harrypotter`, z `Linger=yes`:
- poniedziałek–sobota 02:30 — daily backup + integrity verification;
- niedziela 02:30 — weekly backup + integrity + real restore validation;
- co godzinę — monitor backup/DR.

Daily i weekly nie automatyzują obecnie secrets bundle. Decyzja o docelowym
recovery key jest odroczona i nie blokuje backupów danych.
## 4. Retencja

- 30 daily;
- 12 weekly;
- manual: bez automatycznego kasowania;
- encrypted secrets: bez automatycznego kasowania;
- canonical object pool: append-only, automatyczny GC wyłączony;
- weekly Knowledge restore evidence: 12 ostatnich automatycznych PASS.

Retencja usuwa sparowane manifesty/snapshoty/DB dopiero po sprawdzeniu kompletności.
Brak pary oznacza FAIL retencji.

## 5. Status i monitoring

Status:
`/srv/ai-data/platform/backup-status/stage-k/`

Najważniejsze pliki:
- `daily.json`;
- `weekly.json`;
- `monitor.json`;
- `monitor-alert-state.json`.

Monitor kontroluje:
- prawidłowy CIFS mount GlobalNAS;
- marker Stage K;
- ostatni successful automatic backup <= 36 h;
- weekly restore <= 8 dni;
- minimum 50 GiB wolnego miejsca.

Alarm Telegram jest transition-only: jeden komunikat przy nowym FAIL i jeden po
powrocie do PASS. Awaria Telegrama nigdy nie zmienia wyniku backupu.
## 6. Manual backup

Knowledge/WVC:

```bash
cd ~/AI-server
PY=/opt/ai-platform/current/services/ai-bridge/.venv/bin/python
$PY deploy/stage-k/backup.py --target-root /mnt/AI_Platform --tier manual
```

ERS/Hermes/Platform config:

```bash
$PY deploy/stage-k/k3_domains.py backup \
  --target-root /mnt/AI_Platform --tier manual
```

Secrets pozostają osobnym, ręcznym workflow do czasu decyzji o recovery key.

## 7. Knowledge restore validation

Wybierz manifest Knowledge z NAS:

```bash
$PY deploy/stage-k/verify_backup.py \
  /mnt/AI_Platform/Knowledge/manifests/<tier>/<backup_id>

$PY deploy/stage-k/restore_validate.py \
  /mnt/AI_Platform/Knowledge/manifests/<tier>/<backup_id>
```

Test nie modyfikuje produkcji. Odtwarza pusty PostgreSQL, canonical objects,
uruchamia pusty Qdrant, wykonuje reindex, Search, RAG, citations i source opening.
## 8. ERS / Hermes / Platform restore validation

```bash
$PY deploy/stage-k/k3_domains.py restore-validate \
  --ers /mnt/AI_Platform/ERS/manifests/<tier>/<backup_id> \
  --hermes /mnt/AI_Platform/Hermes/manifests/<tier>/<backup_id> \
  --platform /mnt/AI_Platform/Platform/manifests/<tier>/<backup_id>
```

Hermes SQLite musi przejść `PRAGMA quick_check=ok`.

## 9. Recovery po utracie hosta

Kolejność:
1. przygotuj bazowy Ubuntu i storage;
2. przywróć konfigurację sieci/mount GlobalNAS;
3. pobierz kod AI Platform i odtwórz runtime zgodnie z repo;
4. odtwórz PostgreSQL z wybranego recovery setu;
5. odtwórz canonical objects;
6. odtwórz ERS/Hermes/Platform config;
7. przywróć secrets zgodnie z osobnym secrets runbookiem;
8. uruchom świeży Qdrant i pełny reindex;
9. uruchom Search/RAG/source opening;
10. sprawdź WVC, Hermes i messaging boundary;
11. dopiero po smoke uznaj host za odzyskany.
## 10. RPO / RTO

RPO danych automatycznych: <= 24 h.

Zmierzony weekly K5 dla obecnego corpus:
- cały weekly pipeline: około 124 s;
- sam pełny Knowledge restore: około 109 s.

Operacyjny target Knowledge data plane pozostaje <= 1 h po przygotowaniu bazowego
hosta/runtime. Target pełnego replacement-host recovery pozostaje <= 4 h i będzie
mierzony przy przyszłym replacement-host drill.

## 11. Rollback automatyzacji

Wyłączenie schedulerów/monitoringu bez usuwania danych:

```bash
cd ~/AI-server
bash deploy/stage-k/uninstall_k5_user_services.sh
```

Backupy, manifesty, evidence i statusy pozostają zachowane.

Ponowna instalacja:

```bash
bash deploy/stage-k/install_k5_user_services.sh
```

## 12. Secrets — decyzja odroczona

Obecny encrypted bundle jest zachowany jako evidence. Docelowy model recovery key
nie jest zamrożony. Automatyczny secrets backup i finalny external-key decrypt drill
pozostają wyłączone do podjęcia decyzji o niezależnym recovery identity.
