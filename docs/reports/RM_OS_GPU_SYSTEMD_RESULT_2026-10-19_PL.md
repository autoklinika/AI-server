# AI Platform — test systemowego DevicePolicy: wynik 19.10.2026

## Ustalenie
Operator uruchomił:
`tools/run_rm_os_gpu_systemd_probe.sh` (pierwotna wersja z commita 53e5477),
w katalogu dowodów:
`/srv/ai-data/evaluation/os-gpu-gate-20261019-182354-209705/`.

Pierwsza próba podania hasła do sudo nie powiodła się, późniejsza
autoryzacja przebiegła pomyślnie. Obie transient units zostały
wykonane przez systemowy systemd jako `ai-vision` (UID 994).

- `ai-rm-os-deny-209705.service`, invocation
  `0136f644c9f641f8837961c460144057`: DevicePolicy=strict,
  bez DeviceAllow, `DENIED_AS_REQUIRED` dla /dev/kfd i
  /dev/dri/renderD128, status `SUCCESS`.
- `ai-rm-os-allow-209705.service`, invocation
  `094f6ac586f343fdb529a673ecb360ed`: DevicePolicy=strict,
  DeviceAllow tylko dla /dev/kfd i /dev/dri/renderD128,
  `ALLOWED_AS_REQUIRED` dla obu, status `SUCCESS`.
- Dziennik managera (2026-10-19 20:24:06 CEST) potwierdza
  `Deactivated successfully` dla obu jednostek.
- Początkowy końcowy odczyt KFD z pierwotnego skryptu był niepusty,
  przez co cała procedura zwróciła FAIL. Skrypt nie zapisał PID
  pozostałej pozycji — nie da się ustalić, czy była to resztka
  teardown drugiej usługi czy inny proces.
- O 20:24:46 ponowny odczyt KFD/fuser był pusty. Kolejne 5 próbek
  w interwale ok. 0,4 s (20:25:53–20:25:55) również były puste.
  Nie dowodzi to atomowej globalnej synchronizacji sterownika.

## Decyzja techniczna
`SYSTEM_MANAGER_DEVICE_DENY=PASS`
`SYSTEM_MANAGER_DEVICE_ALLOW=PASS`
`ORIGINAL_IMMEDIATE_KFD_POSTFLIGHT=FAIL_NONEMPTY`
`LATER_KFD_FUSER_SNAPSHOTS=EMPTY_OBSERVED`
`KFD_TEARDOWN_DELAY_CAUSE=NOT_VERIFIED`
`GLOBAL_OS_EXCLUSIVITY=NOT_VERIFIED`
`GPU_REUSE_SAFE=NOT_VERIFIED`
`N1_REAL_GPU_ADMISSION=BLOCKED`

Nie modyfikowano uprawnień grup `render`, ACL, polityk systemd produkcji
ani runtime. Dwie transient jednostki usunięte przez --collect,
nie zostały zainstalowane. Usługi AI nadal zatrzymane.

## Korekta skryptu
Końcową jednorazową kontrolę zastąpiono ograniczonym do 40 próbek
(po 0,25 s) odczytem KFD: raportuje identyfikatory PID, wymaga trzech
kolejnych pustych obserwacji i odmawia po niepowodzeniu lub braku odczytu.
Nie ma restartu, resetu, usuwania kontekstu ani automatycznego release.
Wynik może poświadczyć wyłącznie brak widocznych wpisów w oknie obserwacji,
nigdy pełne GPU_REUSE_SAFE. Kod ma testy syntetycznego krótkiego opóźnienia,
trwale obecnego PID oraz błędu odczytu.

Ponowny test wymagający sudo nie jest potrzebny do uznania dwóch
wykonanych kontroli DevicePolicy; ale nowa obserwacja KFD nie została
jeszcze sprawdzona w tym samym uruchomieniu root systemd. W razie
kontynuacji pełnej sprzętowej bramki trzeba uruchomić zaktualizowany
skrypt i ocenić nowy zapis KFD, bez automatycznej autoryzacji N1.
