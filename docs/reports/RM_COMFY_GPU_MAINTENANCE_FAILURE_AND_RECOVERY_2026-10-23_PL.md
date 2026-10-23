# AI Platform — ComfyUI on-demand GPU: błąd pierwszej próby i naprawa DEV

Data: 23.10.2026. Host: harrypotter-AI-Series.
**REAL_GPU_DEV_TEST=FAIL_CLOSED. PRODUCTION_ROLLBACK=PASS.**
**RETRY_PREPARED_NOT_EXECUTED. GPU_REUSE_SAFE=NOT_VERIFIED.**

## Faktyczny wynik testu operatorskiego

Operator wykonał:
    sudo bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh --run

Wynik: MAINTENANCE_PREFLIGHT_PASS, ROLLBACK_WATCHDOG_ARMED,
GPU_OWNER_FREE_WINDOW_PASS, REAL_COMFY_DEV_FAIL_CLOSED RuntimeError,
PRODUCTION_RESTORE_PASS i MAINTENANCE_EXIT_CODE=19.

Testowe ComfyUI uruchomiono w osobnym transient systemd --system
jako użytkownik harrypotter, lecz zakończyło się jeszcze przed inferencją.
Potwierdzony przez dziennik systemd dokładny błąd:

    main.py: error: argument --user-directory: You do not have read permissions
    for '/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/user'.

Inspekcja katalogów:
- Bazowy katalog staging: harrypotter:harrypotter, tryb 775;
- DEV input/output/temp/user: root:root, tryb 700;
- Backup root:root, tryb 700 — prawidłowy, pozostaje root-only;
- Wynik błędu i recovery marker: root:root, tryb 600 — zachowane.

Harness uruchamiano przez sudo z umask 077, więc katalogi stworzył
dla roota. Proces systemd pracował jako harrypotter i nie mógł ich
otworzyć. To konkretny błąd praw dostępu w skrypcie pilota, a nie
potwierdzona awaria AMD GPU ani konflikt dwóch modeli.

## Audyt po skutecznym rollbacku

- Produkcyjny Gateway, ComfyUI, Ollama, ai-bridge, ai-platform-radio,
  ai-egpu-gen3-ha: active.
- Produkcyjny ComfyUI został uruchomiony ponownie pod PID 77504.
- RM: IDLE, recovery_required=false, active/queued=0/0.
- ComfyUI: modele=0, kolejki=0, cleanup_pending=false.
- DEV systemd unit i rollback watchdog: inactive/not-found, MainPID=0.
- RTX: P8, VRAM 2 MiB, PCIe Gen3x4.
- W sprawdzonym okresie jądra nie wykryto Xid, PCIe AER ani
  nowych błędów reset/timeout/fault AMDGPU.
- Znacznik recovery środowiska DEV pozostał zachowany. Nie nadajemy
  E_safe ani pozytywnego N1 grantu z samego zatrzymania procesu.

## Przygotowana poprawka DEV (NIE WYKONANA jako root)

Nowy recover-after-failure-dev.sh obsługuje:
- Nieinwazyjny --check: odczyt stanu produkcji, GPU, artefaktów.
- Operator-only --repair (sudo):
  1. Weryfikuje dokładny historyczny INCOMPLETE z RuntimeError,
     statusy produkcyjne i brak aktywnego procesu DEV/watchdoga.
  2. Wymaga zgodnego wpisu w journald aktualnego bootu,
     wskazującego na ten konkretny błąd --user-directory.
  3. Kontroluje, że jedynym widocznym właścicielem AMD KFD/renderD128
     jest oryginalny, aktywny ComfyUI produkcyjny.
  4. Odrzuca symlinki, nietypowe typy i niepuste katalogi DEV.
  5. Przywraca WŁAŚNIE cztery katalogi input/output/temp/user
     jako harrypotter:harrypotter, 0700. Backup i dane modeli
     pozostają nietknięte.
  6. Weryfikuje read/write/execute jako użytkownik ComfyUI.
  7. Archiwizuje root-only nieudany wynik, marker i logi
     z SHA256. Dopiero po potwierdzeniu pełnego audytu
     przenosi aktywny marker DEV do archiwum.

Główny pilot --run oraz jego --check zostały rozszerzone o
obowiązkową weryfikację prawa dostępu do czterech katalogów
PRZED rozpoczęciem przerwy w usługach. Harness nie tworzy
ich więcej jako root, tylko odmawia bez prawidłowego właściciela,
trybu i UID/GID.

Walidacja read-only recover --check na serwerze: PASS.
Próba --repair bez sudo: prawidłowa odmowa.
Rzeczywista naprawa root: NOT EXECUTED.
Ponowny test ComfyUI GPU: NOT EXECUTED.

## Kolejność operatorska

Jednorazowe przywrócenie katalogów DEV i archiwizacja błędu:

    sudo bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/recover-after-failure-dev.sh --repair

Odczytowy preflight po naprawie:

    bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh --check

Dopiero potem osobno autoryzowany ponowny test GPU, z kontrolowaną
przerwą w działaniu Gateway/Hermes:

    sudo bash /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh --run

Rollback jest niezależnym timerem w systemd i nie próbuje
uruchamiać produkcyjnego ComfyUI obok niezwolnionego procesu DEV.
Nie gwarantuje dostępności Gateway, gdy nie da się potwierdzić
zwolnienia GPU.

PRODUKCJA BEZ TRWAŁYCH ZMIAN. PR #178 Draft.
GPU_REUSE_SAFE=NOT_VERIFIED. N1_GPU_GRANTS=NOT_ADMITTED.
