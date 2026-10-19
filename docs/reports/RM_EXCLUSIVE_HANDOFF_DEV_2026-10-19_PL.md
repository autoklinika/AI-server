# RM EXCLUSIVE — DEV, 2026-10-19

Raport utworzony przed implementacją. Zakres: wyłącznie offline CPU, pojedynczy
Gateway RM, bez zmian N1–N5, usług, uprawnień urządzeń, SHARED ani multi-GPU.
GPU_REUSE_SAFE: NOT_VERIFIED. REAL_GPU_HANDOFF_NOT_RUN.

## Minimalne blokery rzeczywistego przekazania

| Silnik | Kto blokuje nowe żądania i co trzeba zakończyć | Brakujący kontrakt |
| --- | --- | --- |
| Ollama | Gateway zamyka admission; trzeba również wykluczyć bezpośrednie wywołania API i ponowne uruchomienie runnerów. Drain obejmuje streaming i wszystkie runnery. Unload modeli nie dowodzi zwolnienia GPU. | Dedykowana jednostka system managera, pełne drzewo cgroup wraz z runnerami, tożsamość każdej inkarnacji procesu i jednostki. |
| ComfyUI | Gateway blokuje nowe zadania; bezpośredni `/prompt`, kolejka i rozszerzenia również muszą respektować blokadę. Samo opróżnienie kolejki/free modeli nie usuwa kontekstów procesu i dzieci. | Dedykowana jednostka, wszystkie dzieci/rozszerzenia w jej cgroup, potwierdzenie zakończenia lub kontrolowanego quiesce całego drzewa. |
| Vision | Gateway/N1 zatrzymuje admission; worker pozostaje zaparkowany przed inicjalizacją GPU. Lokalny sync i wyjście jednego PID nie zastępują kontroli dzieci i niezależnej weryfikacji drivera. | Jednostka per próba, PID + boot_id + start ticks, cgroup + InvocationID/identyfikator jej życia; brak GO bez prawdziwego grantu. |

Wspólne minimum: Gateway pozostaje jedynym RM. Blokada ingress musi obowiązywać
przez cały handoff, także dla klientów omijających Gateway. Jednostki systemowe
muszą mieć dedykowane UID, kontrolę całego cgroup, brak automatycznego restartu
podczas przekazania, ograniczony czas zatrzymania i zakaz przenoszenia dzieci
poza cgroup. Tożsamość ścieżki cgroup/PID nie wystarcza: trzeba wiązać ją z boot,
inkarnacją jednostki i czasem narodzin procesów, zachowując pełny manifest dzieci.

DevicePolicy/DeviceAllow musi wymuszać system manager dla KFD i właściwych
węzłów DRM, od początku życia procesu. Deny nowych open nie dowodzi zamknięcia
istniejących deskryptorów, kontekstów DRM/KFD, kolejek ani pracy drivera.
Niekooperujące procesy z grupy render i inne jednostki są nadal blokadą EXCLUSIVE;
samo ograniczenie UID994 nie obejmuje ich. Potrzebna jest negatywna próba dostępu
dla wszystkich dopuszczonych ścieżek uruchomienia oraz niezależny dowód zwolnienia
kontekstów i zakończenia pracy GPU. Puste KFD/fuser to tylko chwilowa obserwacja,
nie E_safe. Brak takiego dowodu oznacza trwałe DIRTY/BLOCKED, bez hot handoff.

## Plan i implementacja DEV

Mały checker sekwencji: BLOCK_NEW → QUIESCE → INVENTORY → RELEASE → NEXT.
Wejścia to wyłącznie stałe dane symulacji; brak I/O, adaptera SafetyAdapter,
schedulera, startowania procesów lub integracji z produkcyjną ścieżką admission.
RELEASE wymaga osobnej symulacji zewnętrznego dowodu związanego z próbą,
urządzeniem CPU i inkarnacją cgroup. Żaden wynik nie jest grantem GPU.
Brak, sprzeczność, zła kolejność i deadline zatrzaskują DIRTY bez resetu.

## Wyniki

Zaimplementowano `src/ai_bridge/gateway/exclusive_handoff_dev.py` oraz
`tests/test_exclusive_handoff_dev.py`. Końcowy wynik: **37 testów PASS** (CPU mock),
exit 0, około 0,5 s. Polecenie:

```sh
PYTHONPATH=src timeout 30s /home/harrypotter/AI-server/.venv/bin/python -m pytest -q tests/test_exclusive_handoff_dev.py
```

Zakres testów: poprawna sekwencja, brak dziecka, obcy właściciel, mieszane cgroup,
ponowne użycie PID, niepełne/błędne inventory, brak fence, odmowa approval,
KFD/fuser jako fałszywe E_safe, stary dowód/inne urządzenie, timeout, cofnięcie
zegara, zła kolejność, denied start, double release i ponowne użycie próby.
Checker jest jednorazowy; deadline opiera się na wstrzykniętym czasie, więc
zatrzymany ślad wymaga jawnego tick/event przy deadline. Nie jest watchdogiem.
Manifest dotyczy członków inkarnacji objętych quiesce, a nie listy żywych PID po
zatrzymaniu. Osobny mock release modeluje zakończenie ich pracy i kontekstów.

Brak błędu sandbox/socketpair. Jedno istniejące ostrzeżenie deprecacji
Starlette/httpx z konfiguracji testów; nie zmieniano zależności. Pierwsza próba
skryptu edycji przez `python` nie wykonała się (brak aliasu); edycję wykonano
wskazanym interpreterem venv, następnie ponowiono testy. Nie wykonywano testów
GPU, probe hosta, zmian usług, commit/push/merge. Nowe pliki nie są importowane
przez produkcyjną ścieżkę Gateway.

Dane o wcześniejszych 4/4 N5
pochodzą z opisu zadania; w tej sesji nie były ponownie weryfikowane.
NonApprovingSafetyAdapter pozostaje niezmieniony. Rzeczywiste E_safe nie istnieje
w tym checkerze, a pozytywna symulacja nie uwierzytelnia żadnego źródła fizycznego.

## Plan wyłącznie dla operatora — NIE WYKONANO

1. W osobnym zatwierdzonym oknie utrzymania potwierdzić stan usług i wykluczenie
   wszystkich niezależnych klientów render; pozostawić ingress zablokowany.
2. Zweryfikować systemowy kontrakt jednostek, inkarnacje cgroup/PID oraz negatywne
   próby otwarcia KFD/DRM także dla klientów poza UID994. Nie przechodzić dalej
   przy obejściu polityki lub niepełnym inventory.
3. Dla Ollama → ComfyUI → Vision zebrać pełny manifest przed quiesce i po nim,
   obejmujący dzieci, deskryptory i konteksty DRM/KFD; przetestować timeout,
   obcego właściciela, restart i niekooperujące dziecko.
4. Wymagać niezależnego, zaufanego dowodu driver/OS związanego z konkretnym
   urządzeniem, grantem i inkarnacją właściciela. Dopóki brak implementacji tego
   dowodu, zakończyć próbę BLOCKED; nie zastępować NonApprovingSafetyAdapter
   atrapą ani nie uruchamiać następnego silnika na podstawie KFD/fuser.

## Niezależna walidacja po zakończeniu zadania Codexa

Uruchomiono bezpośrednio na hoście, poza izolacją Codexa,
21 wybranych modułów testowych: nowy checker EXCLUSIVE, N1–N5,
Gateway, leasing, OS boundary, ROCm pilot oraz regresje residency.
**595/595 PASS, exit 0**. Log:
`/tmp/rm-exclusive-codex-full-regression-20261019.log`.
Zapis nie jest dowodem fizycznego hot handoff; ten pozostaje NOT_RUN.

Stan aktualnych usług po teście: bez start/stop Ollama, ComfyUI,
Gateway i Bridge; brak zmian `/opt/ai-platform/current`.
