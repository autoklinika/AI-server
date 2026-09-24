# AI Platform — Stage K K5 Pre-Merge Acceptance

Data: 2026-09-24
Status: PRE-MERGE ACCEPTANCE PASS

## Zakres

K5 dodaje automatyczny harmonogram, retencję, monitoring i okresowy real restore
validation. Secrets key lifecycle pozostaje świadomie odroczony zgodnie z decyzją
operatora; nie blokuje automatyzacji backupów danych.

## Implementacja

Kod K5:
- `k5_run.py` — daily/weekly orchestration;
- `k5_retention.py` — 30 daily / 12 weekly;
- `k5_monitor.py` — hourly health monitor;
- user-systemd daily/weekly/monitor units;
- install/uninstall scripts bez sudo.

Host ma `Linger=yes`, więc user timers działają bez aktywnego terminala.

Harmonogram:
- Mon..Sat 02:30 daily;
- Sun 02:30 weekly;
- monitor hourly.

## Daily dev gate

Daily pipeline wykonał:
- Knowledge/WVC backup;
- ERS/Hermes/Platform config backup;
- wszystkie offline verification;
- retencję.

Wynik: PASS.
Czas: 11.256 s.

Daily Knowledge ID:
`20260924T172327Z`

Daily domain ID:
`20260924T172333Z`.
## Weekly gate i wykryty błąd notifiera

Pierwszy weekly run wykonał poprawny backup i realny restore, ale końcowy status
został błędnie zmieniony na FAIL przez `PermissionError` notifiera Telegram
uruchamianego bezpośrednio z nie-executable pliku worktree.

Dane i restore tej próby były PASS:
- weekly Knowledge ID `20260924T172434Z`;
- Qdrant rebuilt: 566;
- source snapshot used: false.

Błąd naprawiono w commit:
`3713b344afce167d205beb14f3aadb1bbc28a8ed`.

Notifier jest uruchamiany przez interpreter Python oraz działa best-effort.
Awaria kanału alarmowego nie może już zmienić semantyki wyniku backupu.

## Finalny weekly gate

Finalny pipeline na commit `3713b344afce167d205beb14f3aadb1bbc28a8ed`:
- Knowledge backup ID: `20260924T172733Z`;
- domain backup ID: `20260924T172739Z`;
- czas całego pipeline: 123.984 s;
- status: PASS.
Knowledge/WVC:
- PostgreSQL dump: 36 523 933 B;
- Knowledge versions: 32;
- Knowledge chunks: 566;
- WVC ingest batches: 42 447;
- WVC telemetry raw: 96 563;
- WVC analysis runs: 2 730;
- verify: PASS.

Knowledge restore:
- duration: 108.78 s;
- fresh empty Qdrant;
- rebuilt points: 566;
- RAG claims: 1;
- citations: 1;
- status: PASS.

Evidence:
`/srv/ai-data/backups/stage-k/restore-validation/20260924T172733Z-20260924T172746Z-439149`

ERS/Hermes/Platform restore:
- ERS files: 65;
- Hermes files: 367;
- Hermes SQLite: 5/5 quick_check ok;
- Platform config files: 16;
- production_modified: false;
- status: PASS.

Evidence:
`/srv/ai-data/backups/stage-k/k3-restore-validation/20260924T172739Z-20260924T172937Z-439810`
## Retencja

Realny syntetyczny delete test utworzył trzy daily i trzy weekly zestawy w izolowanym
lokalnym katalogu. Przy `keep=2` najstarszy K2 i K3 został usunięty, pary
manifest/snapshot/DB zachowały spójność, a manual set pozostał nietknięty.

Wynik:
`RETENTION_DELETE_TEST=PASS`.

Canonical pool GC pozostaje wyłączony; pool jest append-only.

## Monitoring

Monitor po finalnym weekly gate:
- GlobalNAS mount: PASS;
- marker: PASS;
- freshest backup age: 0.008 h;
- weekly age: 0.008 h;
- wolne miejsce: 7 785 609 687 040 B;
- issues: [];
- secrets recovery key decision: DEFERRED_NON_BLOCKING;
- status: PASS.

Monitoring alarmuje tylko przy zmianie stanu na FAIL i jednokrotnie po recovery.

## Pre-merge wniosek

K5 functional gate = PASS.
K5 scheduler activation pozostaje do wykonania po merge do `main`, ponieważ
production user-systemd units celowo wskazują stabilny kod z `~/AI-server`,
a nie developerski worktree.

Po merge wymagany jest:
1. install user-systemd units z main;
2. kontrola timerów i next-run;
3. ręczny start monitor service;
4. finalny runtime status PASS;
5. closure report.
