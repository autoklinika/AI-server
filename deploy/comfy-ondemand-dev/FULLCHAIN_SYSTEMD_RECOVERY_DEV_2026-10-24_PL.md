# AI Platform — kontroler systemd i niezależny rollback /foto (DEV)

**Data:** 24.10.2026. **Host:** harrypotter-AI-Series. **Repo:** PR #178 / gałąź feature/rm-two-gpu-routing-dev-20261023.

**Podstawowa zasada:** jeden PriorityScheduler/Resource Manager; brak dodatkowego schedulera, koordynatora lub nowego daemona GPU. ComfyUI uruchamiane jedynie na czas aktywnej rezerwacji RM.

## 1. Zakres wykonania

- tools/local_image/fullchain_systemd_controller_dev.py: kandydat jednokrotnego, stałego polecenia systemd-run --system dla jednostki ai-rm-comfy-ondemand-dev.service i jednej określonej instancji ComfyUI. Parametry startu, port, urządzenia i katalogi są zakodowane, a nie przyjmowane od klienta.
- Kontrola: recovery marker, istniejący globalny ticket RM, zamknięte porty, brak produkcyjnego właściciela AMD, uzbrojony watchdog, pusty poprzedni cgroup oraz wystarczający RAM fizyczny. Sprawdza PID, process start ticks, Boot ID, Invocation ID, User, DevicePolicy, KillMode, ControlGroup, argv i każdego właściciela deskryptorów AMD.
- tools/local_image/fullchain_independent_rollback_dev.py: kandydat jednorazowej procedury sterowanej niezależnym timerem systemd --system. Wyłącznie dwa zatwierdzalne targety restore: comfyui.service i ai-gateway.service.
- Logiczna kolejność: snapshot dowodów → stop zidentyfikowanego workera → stop DEV Gateway → stop dokładnie jednej jednostki DEV ComfyUI → potwierdzenie procesów/cgroup/portów → wyładowanie tylko zatwierdzonego Qwen → kontrola descriptorów AMD → kontrola sterownika (DRM/KFD/MES/AER, bez zmian boot) → archiwizacja dowodów → restore produkcji → smoke test → wyłączenie watchdoga.
- Awaria dowolnej kontroli **przed** restore oznacza brak uruchomienia ComfyUI. Po błędzie w trakcie restore stan oznaczany PARTIAL_OR_UNVERIFIED, a watchdog i marker wymagają osobnej kontroli operatora. Żaden kod nie przyznaje automatycznie GPU_REUSE_SAFE=PASS.

**Nie jest to jeszcze wdrożony kontroler ani działający niezależny watchdog.** CLI obu nowych plików udostępnia wyłącznie read-only --check; metody build/symulacja są odseparowane i nie wywołują rzeczywistych operacji systemd. Nie wykonywać wygenerowanego planu systemd-run. Ścieżka /run/ai-rm-fullchain-recovery/rollback.py jest przyszłym miejscem zaufanego, root-owned runnera; obecnie nie istnieje i w DEV nie ma wykonywalnego --execute. To **BLOCKED**, nie dopuszczenie do okna GPU.

## 2. Zidentyfikowane fizyczne blokady przed startem

| Kontrola | Stan | Dowód |
|---|---|---|
| Jedna docelowa jednostka i jeden GPU AMD | PASS — statyczny plan | stałe systemd-run --system, DevicePolicy=closed, DeviceAllow tylko KFD/renderD128 |
| Jeden zaufany PID/boot/cgroup, odmowa obcych właścicieli | PASS — testy CPU/mock | weryfikacja proc/stat, cgroup i cmdline |
| Watchdog na host-cgroup niezależny od sesji | NOT_TESTED | istniejące starsze realne rollbacki nie obejmowały pełnego Qwen |
| Prawdziwy rollback po Qwen | NOT_TESTED | testy CPU kontraktu, brak wykonania callbacku na realnym GPU |
| GPU driver E_SAFE / reuse | BLOCKED | E_SAFE = NOT_VERIFIED |
| Pamięć FLUX2 Klein na AMD | BLOCKED | 11,597 GiB samych wag; MemoryMax 12G w nieinstalowanej jednostce DEV |
| Konto dedykowane tylko dla ComfyUI | BLOCKED | obecny kandydat DEV korzysta z harrypotter; osobne konto usługowe nieutworzone |
| Wykonywalne środowisko niemodyfikowalne przez użytkownika runtime | BLOCKED | /opt/comfyui i ComfyUI/main.py należą do harrypotter; katalog ComfyUI 0775, plik main.py 0664 |
| Odmowa GPU-bypass przez pozostałe UID i inne nody | BLOCKED | produkcyjne urządzenia/grupy GPU poza globalną kontrolą RM |
| Wpływ na produkcję | BRAK ZMIAN | żadne start/stop, systemd-run, install, chown, chmod ani Telegram nie były wykonane |

## 3. Testy i komendy bezpieczne do powtórzenia

W worktree DEV:
- python3 tools/local_image/fullchain_systemd_controller_dev.py --check
- python3 tools/local_image/fullchain_independent_rollback_dev.py --check
- PYTHONPATH=src python -m pytest -q tests/test_fullchain_systemd_controller_dev.py tests/test_fullchain_independent_rollback_dev.py
- systemd-analyze verify deploy/comfy-ondemand-dev/ai-rm-comfy-ondemand-dev.service (weryfikacja oryginalnej jednostki tylko na rzeczywistym hoście)

Te polecenia nie obciążają AMD GPU. Testy obejmują pozytywny kontrakt i odmowy startu, zmian tożsamości procesu, obcych właścicieli AMD, naruszenia limitów pamięci, brak watchdoga i błędy każdego kroku rollbacku.

## 4. Bramka następnego okna

Przed osobną zgodą operatora:
1. Zamrozić i zainstalować *root-owned* zaufany kod w niezapisywalnej przez konto modelu lokalizacji; potwierdzić SHA256, katalogi źródłowe, unit allowlist oraz dokładną politykę sudo/polkit.
2. Utworzyć dedykowane konto wykonawcze i izolować runtime oraz wszystkie device nodes, bez zmiany globalnych praw GPU w sposób niekontrolowany.
3. Przygotować kompletny, operator-only runner start/rollback, który faktycznie można uruchomić i odtworzyć z timerem system-manager; przetestować CPU-only w systemd --system, a potem symulowaną awarię bez GPU.
4. Ustalić docelowe MemoryHigh/MemoryMax na podstawie pomiarów i wymagań ROCm. Nie podnosić obecnego limitu produkcyjnego arbitralnie i nie uruchamiać OOM/SIGKILL podczas kernela GPU.
5. Potwierdzić, że operacja ma niezależny watchdog, lock, snapshot, no-owner check po stop, obsługę modelu Qwen35, restart tylko oryginalnych usług, archiwizację dowodów i fail-closed.
6. Dopiero po tych testach i osobnej zgodzie można zatrzymać produkcyjnego właściciela AMD w ograniczonym oknie i wykonać jeden rzeczywisty /foto 256×256.

**Werdykt:** przygotowanie architektury i testów statycznych PASS; hardware acceptance i przygotowanie fizycznego recovery BLOCKED. PR Draft bez merge/cutover.
