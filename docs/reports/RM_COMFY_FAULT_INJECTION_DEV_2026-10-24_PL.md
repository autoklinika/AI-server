# AI Platform — ComfyUI on-demand: testy awaryjne RM i systemd (DEV)

Data: 24.10.2026. Host: harrypotter-AI-Series.
**CPU/ASGI FAULT-INJECTION PASS. RZECZYWISTE AWARIE ROCm NA AMD 890M: NOT PERFORMED.**
**PRODUKCJA BEZ ZMIAN. GPU_REUSE_SAFE=NOT_VERIFIED. N1_GPU_GRANTS=NOT_ADMITTED.**

## Założenie

Zachowujemy **jeden istniejący PriorityScheduler Resource Managera**:
Hermes/Telegram/media-image rezerwuje miejsce, ComfyUI startuje w fazie
/uses i kończy poprzez /free, zamknięcie procesu/cgroup, dopiero potem
release. Testy negatywne muszą utrzymać oryginalny ticket i trwały
marker recovery, nawet gdy klient zamknie połączenie albo sam wyśle
DELETE lease. RM może kolejkować kolejne zadania, ale nie wolno
ich uruchamiać na niezweryfikowanym GPU.

## 1. Niezależne testy integracyjne RM (bez GPU, na prawdziwym Gateway DEV)

W nowym tests/test_rm_comfy_fault_injection_dev.py, przy użyciu
ASGI, symulowanego kontrolera systemd i istniejących klas RM:
- nieoczekiwany koniec procesu podczas media — FAIL CLOSED PASS;
- utrata cgroup przez limit RAM — symulacja warstwy RM, PASS;
- proces nieodpowiadający/zmiana PID — PASS;
- rozjazd boot-ID — PASS;
- wykorzystanie tego samego PID przy innym proc birth — PASS;
- timeout startu procesu — PASS;
- timeout weryfikacji zatrzymania po /free — PASS.

- kontrola aktywnej inkarnacji procesu uruchamiana samodzielnie przez
  **istniejący RM**, bez GET /uses od Hermesa — PASS;
- automatyczny reaper istniejącego Gateway sprawdza ComfyUI co około
  2 s w trybie DEV (z dodatkowym limitem 4 s na odczyt tożsamości),
  blokuje przydziały i zachowuje marker — PASS; brak gwarancji
  twardego 2-sekundowego SLA wykrycia.

W każdym przypadku niezweryfikowane zakończenie *nie zwalnia*
dotychczasowego slotu RM, kolejny klient dostaje jedynie queued,
scheduler zostaje admission_blocked, a recovery marker pozostaje
na dysku i uniemożliwia automatyczne odblokowanie po restarcie
Gateway. **9/9 scenariuszy PASS.**

## 2. Rzeczywiste krótkie procesy systemd --user (CPU-only)

W oddzielnych, nieuprzywilejowanych procesach Linux, pod systemd
--user, przeprowadzono:

| Negatywny test | Limit | Wynik systemd |
|---|---|---|
| OOM procesu | MemoryMax=48 MiB, jednorazowa alokacja 128 MiB | oom-kill, status=9/KILL |
| Timeout | RuntimeMaxSec=2s, proces śpiący 30s | timeout, status=15/TERM |
| Wymuszone przerwanie | SIGTERM do testowego procesu, bez GPU | code=killed, status=15/TERM |

**Wszystkie trzy procesy zakończyły się**, ich MainPID=0,
jednostki transient inactive/not-found. Należy pamiętać, że systemd
może pokazywać Finished with result: success dla procesu zakończonego
SIGTERM zgodnie z oczekiwaną semantyką usługi. Dlatego test odróżnia
faktyczny code=killed/status=15/TERM od samego kodu wyjścia narzędzia.

Pierwsza próba symulacji sygnału użyła błędnego os.raise_signal i
zakończyła się błędem aplikacji; nie została zaliczona. Prawidłowy
test zakończenia wykonano oddzielnie przez signal.raise_signal.
To nie był sygnał wysłany do procesu produkcyjnego.

Nie uruchomiono żadnego modelu/akceleratora w tych trzech testach,
nie zatrzymano ani nie restartowano Gateway, ComfyUI, Ollama,
Hermes, eGPU boot gate ani sterownika GPU.

Maszynowy plik:
RM_COMFY_CPU_FAULTS_SYSTEMD_2026-10-24.json
Oryginalne wyniki:
 /srv/ai-data/staging/comfy-ondemand-faults-dev-20261024/

## 3. Co przetestowano wcześniej na prawdziwym Radeonie

23.10.2026 operator przeprowadził **jeden pozytywny cykl**:
real ComfyUI AMD Radeon 890M, Flux2 VAE 64x64, PNG 7922 B,
start/finalizację jednej kolejki RM i rollback usług produkcyjnych PASS.
To nie obejmowało wymuszonego abort, GPU timeout ani OOM podczas
prawdziwej inferencji.

## 4. Bramka następnego testu GPU

Realne wymuszenie awarii podczas ROCm work może skutkować
zawieszeniem AMDGPU/KFD/MES. Nie wolno wykonywać takich prób
wspólnie z produkcyjnym ComfyUI trzymającym deskryptory GPU.

Przed testem GPU potrzebne są:
1. Niezależny watchdog, oryginalny backup stanu systemd, preflight
   RM=IDLE, brak obcych właścicieli GPU i weryfikowany rollback.
2. Przydzielona root-owned usługa GPU w systemd --system; test w
   osobnym oknie serwisowym, nie w systemd użytkownika.
3. **Jeden scenariusz awarii na jedno okno**. Przy braku dowodu
   czystego sterownika nie wykonywać kolejnych prób w tej samej
   sesji i nie przywracać równolegle dwóch właścicieli Radeon 890M.
4. Weryfikacja GPU PID, cgroup, boot-ID, InvocationID, właścicieli
   DRM/KFD i pełnego procesu cleanup, a nie tylko RM IDLE.
5. Później faktyczne Hermes /foto (bez wysyłania testowych
   wiadomości na prywatne konta), współpraca z RTX i zgodność WVC.

**Stan końcowy:** RM fail-closed logic PASS, real systemd CPU
fault reactions PASS, real AMD GPU fault acceptance NOT_EXECUTED.
Nie scalać Draft PR #178 ani nie przełączać produkcji z tych
dowodów. GPU_REUSE_SAFE / E_safe nadal NOT_VERIFIED.


## 5. Pierwsza próba fizycznej awarii — etap STAGED, NIE URUCHOMIONY

Dla prawdziwego Radeona 890M przygotowano osobną procedurę DEV
pojedynczego negatywnego przypadku:

- Oryginalny Gateway/ComfyUI są zatrzymywane wyłącznie w kontrolowanym
  oknie z systemd watchdog rollback.
- Rzeczywisty ComfyUI działa jako tymczasowy, nieuprzywilejowany
  proces w system-manager cgroup z kontrolą dostępu do AMD KFD/DRM.
- Dotychczasowy RM rezerwuje jeden slot i wykonuje rzeczywisty
  dekoder VAE 64×64 na Radeonie, zgodnie z zaliczoną próbką.
- Po poprawnej generacji testowo **odmawiamy potwierdzenia zatrzymania**
  silnika. Oczekujemy odmowy zwolnienia lease, utrzymania markera
  recovery DEV i braku dopuszczenia kolejnego zadania.
- Niezależny rollback zatrzymuje sprawdzoną jednostkę testową,
  dopiero potem uruchamia produkcyjne ComfyUI i Gateway.

To bezpieczniejszy pierwszy test nieprawidłowej finalizacji niż
natychmiastowy SIGKILL lub GPU OOM podczas aktywnej pracy jądra
ROCm. **Nie wolno mylić go z wymuszonym driver crash**, a w
szczególności nie przyznaje automatycznie GPU_REUSE_SAFE.

Źródło i dowody gotowości procedury:
deploy/comfy-ondemand-dev/fault-stop-dev-20261024/
Wykonano bash -n, Python AST, sześć statycznych testów ochrony,
weryfikację workdirów użytkownika i rzeczywisty read-only
preflight na AI Platform: PASS.
Operator --run: **NOT_EXECUTED**. Produkcja nietknięta.


## 6. Wynik rzeczywistej próby odmowy stop — 24.10.2026, 07:52 CEST

Po przygotowaniu powyższej procedury operator wykonał jednorazowe
sudo --run. **Wynik kontrolowanego testu negatywnego PASS, rollback PASS,
MAINTENANCE_EXIT_CODE=0.** ComfyUI użył prawdziwego Radeona 890M do
dekodowania Flux2 VAE (0,66s) i zapisania PNG 64×64 (7922 B).
Kontroler DEV następnie celowo odmówił potwierdzenia stop. RM
zachował oryginalną rezerwację i znacznik recovery; osobny
rollback zatrzymał tymczasową jednostkę GPU i przywrócił ComfyUI
i Gateway. Wszystkie usługi produkcyjne są zdrowe, RM IDLE 0/0,
testowy port zamknięty, watchdog nieaktywny, Xid/AER=0.

**Znacznik recovery środowiska DEV NADAL ISTNIEJE** — ten fakt jest
prawidłowy po negatywnym teście. Przygotowano audyt i osobny,
operator-only proces archiwizacji (nie wykonany). Nie nadano
GPU_REUSE_SAFE, E_safe ani zgody na produkcyjne zmiany.
Odmowa stop była symulowana PO pracy GPU, nie podczas aktywnego
kernela ROCm.

Szczegóły i ocena dowodów:
RM_COMFY_STOP_REFUSAL_REAL_GPU_DEV_2026-10-24_PL.md
RM_COMFY_REAL_GPU_STOP_FAULT_DEV_2026-10-24.json
