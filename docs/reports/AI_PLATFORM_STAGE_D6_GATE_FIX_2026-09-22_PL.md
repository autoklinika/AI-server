# D.6 production-gate correction — D6GATEFIX

**Data:** 2026-09-22  
**Status:** READY FOR SUPERVISOR VALIDATION — implementation ready for supervisor validation  
**Production validation:** NOT RUN. Stage D nie jest COMPLETE.

## Zmiana

Realne inventory wymaga przełączenia dokładnie pięciu aktywnych plików klienta,
nie historycznych generatorów libexec. Helper jest cache'owany przez patch Hermesa
jako `_ai_server_resource_queue`; podmiana pliku wymaga celowego restartu Hermesa.

Nowe [d6_client_bundle.py](../../deploy/stage-d/d6_client_bundle.py) ma polecenia
`apply` i `restore`. Mapa jest stałą allowlist pięciu zatwierdzonych destination /
repo source. Nie modyfikuje wrappera `generate-video-ltx23`, trzech historycznych
kopii `generate_ltx23*`, patcha Hermesa ani konfiguracji produktów/modeli/GPU.

Przed mutacją weryfikuje:

- D.6 RELEASE/manifest i pełne checksums, źródła klientów pokryte checksums
  w obu usługach oraz zgodne bytes tych źródeł;
- oryginalny manifest TSV i wszystkie pięć wymaganych backupów;
- bytes backupu według `installed_sha256`, mode/uid/gid według backup stat;
- brak symlinków w źródłach klientów, backupach i installed destinations;
- kompletny znany installed bundle (old albo new); unknown/mixed odrzuca;
- aktywny D.6 release i cwd działającego Gateway wskazujące na ten sam release;
- zdrowy Gateway, Resource Manager 0/0/0, puste kolejki ComfyUI, aktywne usługi.

CLI używa stałego oryginalnego snapshotu
`/srv/ai-data/platform/recovery/stage-d6-resource-manager-v2-20260922-r1-clients`.
Jawny `--manifest` wskazuje faktyczny oryginalny manifest wewnątrz snapshotu.
Nie wymyślono nazwy pliku manifestu ani nowego schematu recovery. Manifest r1
`candidate_sha256`/`candidate_path` pozostaje historycznym porównaniem, nie bramką
r2. Sanitized handoff służył wyłącznie implementacji: odczytano pięć backupów,
porównano ich SHA z `recovery-contract.tsv`, potwierdzono observed 0755/0644 i 0:0.
Nie odczytywano oryginalnego snapshotu ani credential/token files.

Instalacja: per-file temporary + fsync + atomic replace + directory fsync;
apply mode 0755 dla dispatcherów, 0644 dla helpera/compilerów, root:root;
restore zachowuje oryginalne metadata. Snapshot nigdy nie jest zapisywany.
Executor lock odrzuca równoległe bundle commands. Operator utrzymuje ingress i
analysis quiesced przez całe okno (`--quiesced`); idle checks nie blokują admission.

Po zmianie restartuje tylko `hermes-gateway.service` w istniejącym user managerze
(`--hermes-user`, kontrolowany privileged executor, bez sudo). Czeka na nową
service identity i świeży `gateway_state.json`: running, Telegram connected,
API connected. Nie wypisuje surowego state, status/queue, promptów ani błędów
backendów. Sprawdza unchanged Gateway/ComfyUI PID+InvocationID, health/idle i
zainstalowane bytes/metadata; zwraca nowy Hermes PID baseline.

Caught failure próbuje odtworzyć entry bundle, wykonać kolejny celowy Hermes
restart i zweryfikować recovery. Nie zmienia FAIL na PASS. Zajęte kolejki lub zmiana
Gateway/ComfyUI blokują dalszą automatyczną mutację. SIGINT/SIGTERM obsługiwane;
SIGKILL/power loss może pozostawić partial bundle. Wtedy zachować D.6 i evidence,
wstrzymać ruch, przekazać controlled recovery executorowi. Brak nowego protokołu
crash/resume. Nie usuwa recovery artifacts.

## Kolejność i dokumentacja

[Runbook](../../deploy/stage-d/D6_VALIDATION_RUNBOOK.md) definiuje:

1. D.6 + new clients -> idle -> restore old clients pod D.6 -> intentional
   Hermes restart/health -> rollback release do D.0 -> D.0 validation.
2. D.0 + old clients -> activate D.6 release -> Gateway health/idle -> apply
   D.6 clients -> intentional Hermes restart/health -> pełna D.6 validation.

D.6 Gateway zachowuje compatibility ze starymi klientami. Nigdy new clients przed
D.0 Gateway. Historyczne release scripts pozostają niezmienione i samodzielnie nie
zarządzają client bundle; supervisor musi zachować powyższą kolejność.
Hermes PID baseline odnawia się po każdej celowej zmianie bundle; PID musi być
stabilny w każdej fazie smoke. ComfyUI pozostaje bez restartu przez cały cykl.
Zaktualizowano Stage D README, D.6 preparation report i architecture/contracts.

## Testy lokalne

Interpreter: `/home/harrypotter/AI-server/.venv/bin/python`, `PYTHONPATH=src`.
Nowe testy używają tymczasowych plików i mocków runtime; nie kontaktują usług.

| Gate | Wynik |
|---|---|
| Nowe `test_stage_d6_client_bundle.py` | 38 PASS |
| Suite poza czterema znanymi modułami TestClient | 659 PASS |
| Niezależne corestate tests | 3 PASS (w focused run) |
| Focused D6GATEFIX + D6 preparation + D foundation + corestate | 85 PASS, 1 deselected |
| Python compile / git diff --check | PASS |
| Pełny pytest, timeout 45 s | NIEUKOŃCZONY, exit 124 |
| Clean committed release build / CI | NOT RUN — supervisor |
| Production install/restart/smoke/rollback | NOT RUN |

Łącznie 662 różne lokalne testy PASS; focused run jest podzbiorem.
Pełny pytest utknął przy `TestClient.__enter__` -> `start_task_soon` ->
`run_sync_from_thread` w `tests/conftest.py`, przed requestem. Trace po 15 s;
timeout po 45 s. To znane ograniczenie wcześniejszych etapów. 18 istniejących
przypadków wymaga rerun supervisora; nie zmieniano zależności/harnessu.

Coverage korekty: dokładna mapa i legacy exclusions, schema/missing/duplicate/
tampered backup, stat metadata i symlink rejection, r1/r2 independence, release
metadata/checksum/source coverage/drift, kompletność bundle, idle każdego licznika,
D.6-before-clients guard, atomic failure, apply/restore byte+mode fidelity,
write/restart failure recovery (w obu kierunkach), blocked recovery, ComfyUI
identity guard, fresh connectivity/new Hermes identity, PID i rollback ordering.

Nie wykonano sudo, gh, commit/push/PR/merge, production install/cutover/rollback,
service start/stop/restart ani zmian /opt, /usr/local, /var/lib, secrets, networking,
workflows lub .gitmodules. Stage E nie rozpoczęto. Supervisor posiada końcowy
review, pełny test/build/CI i osobną autoryzację production validation.
