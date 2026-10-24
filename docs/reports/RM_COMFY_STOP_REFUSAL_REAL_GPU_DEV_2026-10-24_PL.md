# AI Platform — kontrolowana odmowa zatrzymania ComfyUI po pracy GPU (DEV)

Data: 24.10.2026, ok. 07:52 CEST. Host: harrypotter-AI-Series.

**Wynik: KONTROLOWANY TEST NEGATYWNY PASS. ROLLBACK PRODUKCJI PASS.**
**PRODUCTION_CUTOVER=NOT_DEPLOYED; GPU_REUSE_SAFE/E_safe=NOT_VERIFIED;
N1/SHARED_GPU_GRANTS=NOT_ADMITTED.**

## Zakres operatora

Uruchomiona została jedna próba serwisowa z tego katalogu:
 /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/

Operator uruchomił run-fault-window-dev.sh --run z sudo.
Test miał potwierdzić reakcję istniejącego Resource Managera w
**jednym konkretnym scenariuszu**: prawdziwy ComfyUI wykonuje
obraz na Radeonie, a następnie kontroler procesu celowo odmawia
potwierdzenia operacji stop_and_verify, po czym kod RM zostaje
zmuszony do odmowy zwolnienia lease. Nie wykonano SIGKILL
ani GPU OOM w trakcie pracy jądra ROCm.

Operator potwierdził:
- DEV_COMFY_UID_DIRECTORY_RW_PASS
- MAINTENANCE_PREFLIGHT_PASS_RM_AND_PHYSICAL_GPU
- ROLLBACK_WATCHDOG_ARMED
- GPU_OWNER_FREE_WINDOW_PASS
- REAL_GPU_DEV_START
- DEV_EXPECTED_STOP_FAILURE_PENDING_ROLLBACK
- PRODUCTION_RESTORE_PASS
- MAINTENANCE_EXIT_CODE=0

Tryb NEGATIVE jest PASS tylko wtedy, kiedy skrypt rozpoznaje
oczekiwany błąd po obliczeniu obrazu, sprawdza negatywny wynik
RM (INCOMPLETE, RuntimeError), występowanie PNG i **wciąż
aktywny znacznik recovery**. Przerwanie potwierdzenia stop nie
jest automatycznie zamieniane na pozytywną zgodę RM na GPU.

## Niezależne dowody read-only na prawdziwym serwerze

| Własność | Weryfikacja |
|---|---|
| Prawdziwy GPU | Log: cuda:0 AMD Radeon 890M Graphics : native (PyTorch ROCm) |
| Realny VAE | Flux2, VAE load device: cuda:0, offload cpu, torch.bfloat16 |
| Przetworzenie promptu | 0,66 s |
| Wyjście | PNG 64×64, 7922 bajty |
| SHA256 obrazu | 16e0117ddd83e8d051956f3e70cfccf1e9ac81e091f19527383b13fe0d44f205 |
| Tymczasowa jednostka systemd | Start 07:51:55, stop 07:52:00, ~5,095s wall |
| RAM peak jednostki | 1,3 GB RAM hosta (nie limit VRAM) |
| Oryginalny negatywny wynik / znacznik DEV | Zachowane, root:root, 0600 |
| Testowa usługa / port 11657 | Usługa not-found/inactive, MainPID=0, port zamknięty |
| Watchdog po rollback | Nieaktywny |
| Produkcyjny ComfyUI | COMFYUI_READY=PASS, aktywny (nowy PID 103731), kolejka=0, modele=0 |
| Produkcyjny Gateway | status ok, RM IDLE, active=0, queued=0, recovery_required=false |
| Ollama, ai-bridge, eGPU boot gate | active |
| NVIDIA RTX 5060 Ti | P8, 2 MiB, PCIe Gen3 ×4 |
| Xid, PCIe AER, nowe ostrzeżenia jądra w tym oknie | Nie wykryto |

Po rollbacku produkcyjny ComfyUI **ponownie trzyma KFD/renderD128**.
Jest to zgodne z dotychczasowym stałym autostartem, którego w DEV
nie zmieniono. W samym oknie próby brak równoległego ownera AMD był
warunkiem preflight.

Maszynowy zbiór faktów (bez publikacji root-owned logów):
RM_COMFY_REAL_GPU_STOP_FAULT_DEV_2026-10-24.json

Dowód PNG i oryginalne logi procesu oraz rollbacku są na NVMe:
 /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/

Root-only wynik procesu RM i logger nie były bezpośrednio
odczytywane przez nieuprzywilejowany collector — interpretacja
dokładnej odmowy RM opiera się na warunkach źródłowego scenariusza
i wyniku operatorskim, zaś GUI/VM/GPU postflight na niezależnych
odczytach HTTP, journald i sysfs.

## Granice wyniku

- Jest to **symulowana odmowa potwierdzenia zatrzymania kontrolera**,
  nie przypadkowy crash ComfyUI i nie test kernel-level
  E_safe/teardown po SIGKILL podczas obliczeń.
- Ostatecznie proces zatrzymał rollback; nie został zamknięty
  przez normalną ścieżkę RM stop_and_verify.
- DEV znacznik recovery jest prawidłowo utrzymany, dopóki operator
  osobno nie zarchiwizuje negatywnego wyniku i nie dokona audytu
  stanu sterownika oraz właścicieli GPU.
- Brak akceptacji produkcyjnego automatycznego on-demand; nadal
  Requires=comfyui.service i Restart=always w systemd.
- Brak dowodu globalnej blokady bypassów i automatycznych
  ponownych grantów Radeon/RTX.

**Werdykt: FAIL-CLOSED NEGATIVE CASE PASS, PRODUCTION ROLLBACK PASS;
PHYSICAL GPU CRASH/OOM NOT TESTED; PRODUCTION NO-GO.**
