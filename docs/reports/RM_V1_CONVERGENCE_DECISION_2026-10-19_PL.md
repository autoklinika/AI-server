# RM V1 — decyzja konwergencji, 2026-10-19

**GO: zakończenie minimalnego zakresu DEV z blokadą wykonania. NO-GO:
automatyczny rzeczywisty grant N1, automatyczny handoff i produkcyjne GPU_REUSE_SAFE.**
Nie ma bezpiecznej flagi konfiguracji, która kończy wdrożenie live. Brakujący
element to zaufana kontrola uruchamiania i dostępu do GPU oraz niezależny dowód
bezpieczeństwa sterownika, a nie kolejny scheduler ani kolejny pilot sprzętowy.

## DONE — rzeczywisty sprzęt (wcześniejsze dowody)

[Raport sprzętowy](RM_SYSTEMD_EXCLUSIVE_HARDWARE_REPORT_2026-10-19_PL.md)
potwierdza LOCAL_SYSTEMD_HANDOFF_PASS_3_OF_3 na Radeon 890M:
Ollama Vulkan bge-m3 (embedding 1024), inicjalizacja ComfyUI ROCm,
Vision ROCm 64×64. Jednostki systemowego systemd miały DevicePolicy=closed
i allowlistę /dev/kfd oraz /dev/dri/renderD128; procesy zakończono,
obserwacje KFD/fuser po etapach były puste. ComfyUI nie generowało obrazu.
To wynik wykonania operatorskiego, nie N1.release ani globalna izolacja hosta.
W tej sesji nie powtarzano pomiarów ani nie sprawdzano aktywnie stanu GPU/usług.

## DONE — kod DEV i rzeczywiste połączenia

Inspekcja wykazała, że istniejący Gateway już ma `n2-dev-blocked`:
Settings → create_gateway_app → jedyny PriorityScheduler →
N2IntegrationBoundary.require_execution. Domyślna strategia pozostaje `legacy`;
N1 jest domyślnie wyłączony. Legacy nie zapewnia ochrony N1.
Boundary blokuje acquire/reserve, użycie i zwolnienie lease, wykonanie platformy
oraz retrieval mogący wywołać embeddings. Nie tworzy drugiej kolejki ani N1.

Minimalna zmiana w `src/ai_bridge/gateway/app.py`:

- proxy_scheduled wywołuje istniejącą bramkę przed odczytem body, parsowaniem
  priorytetu i rozwiązywaniem lease. W trybie blocked również błędne metadane
  klienta otrzymują 503 NOT_VERIFIED, bez próby wykonania;
- startup trybu blocked zapisuje jawny WARNING: wykonanie wyłączone,
  physical N1 grants NOT_ADMITTED, OS isolation i driver reuse NOT_VERIFIED.

Testy przechodzą przez prawdziwy lifespan i routing ASGI Gateway; zastępczy
transport upstream jest pułapką wykrywającą niedozwolone wywołanie, nie nowym
modelem handoff. Dziewięć nowych przypadków zabrania nawet odczytu body.
Istniejące testy sprawdzają restart, niemożność odblokowania przez residency,
stare/fałszywe leases, reaper i zgodność domyślnego legacy.

`AcceleratorAdmission` pozostaje osobnym rdzeniem DEV, nie uruchomiono go obok
PriorityScheduler. `n1_n5_cpu_bridge.py` dopuszcza tylko syntetyczne CPU.
`NonApprovingSafetyAdapter.can_start/verify` nadal zawsze zwracają False.
Nie dodano atrap adaptera, pliku „protected=true”, flagi ręcznego grantu ani
menedżera usług. Obecna blokada jest bezwarunkowa: nawet poprawna konfiguracja
silnika nie wystarcza do jej zdjęcia.

## BLOCKED — precyzyjne zależności produkcyjne

1. **OS / uruchamianie:** root-owned, zatwierdzone profile wszystkich trzech
   silników, niezmienne executable/argumenty i ograniczona delegacja do system
   managera pod istniejącym RM. Trzeba zamknąć bypass przez render/ACL,
   sesje użytkowników, alternatywne API i autonomiczne starty usług. Sam
   DevicePolicy=closed jednej jednostki nie ogranicza reszty hosta.
2. **Tożsamość i sterownik:** zaufany, świeży dowód związany z boot ID,
   fizycznym urządzeniem i aliasami, PID/birth/cgroup/InvocationID, generacją
   grantu, nonce/epoch i dziennikiem N1. Musi dowodzić zakazu ponownego submit
   oraz zakończenia kolejek i asynchronicznego cleanup AMDGPU/KFD/MES.
   Nie istnieje tutaj zatwierdzony pozytywny verifier tego warunku.
3. **Wpięcie wykonania:** dopiero na tej podstawie adapter pod jednym Gateway
   może powiązać rezerwację, chroniony start, trwałe przekazanie grantu,
   stop/release i recovery. PriorityScheduler pozostaje jedyną kolejką;
   nie wolno uruchomić drugiego niezależnego arbitra N1 dla tego samego GPU.
   HTTP success, TTL lease lub odładowanie modelu nie zwalnia fizycznej własności.

Przeczytano skrypt pilota systemd, `os_gpu_boundary.py`, N1/N3/N5 oraz źródło
obserwatora i jego unit w sąsiednim `vision-rm-system-security-worktree`
(tylko odczyt). Obserwator ma uwierzytelnianie peerów AF_UNIX i odczyt
cross-UID /proc; nie odbiera uprawnień do GPU. Jego obserwacje oraz protokół
terminalny nie stanowią pozytywnego dowodu E_safe. Nie zmieniano instalacji
root-owned ani nie odpytywano działającego obserwatora.

## Jeden runbook operatorski — wdrożenie, boot i rollback

To lista warunków i kolejności dla późniejszego zatwierdzonego okna wdrożenia,
nie polecenie uruchomienia usług teraz. Nie wykonywać kolejnych pilotów obliczeń.

1. **Minimalny następny krok:** operator zatwierdza profil EXCLUSIVE dla
   jednego Gateway: zestaw root-owned profili silników, zamknięcie bypassów
   i źródło dowodu driver safety. Jeżeli nie można wskazać wiarygodnego źródła
   tego dowodu, decyzja pozostaje NO-GO; nie zastępować go podpisem operatora.
   Możliwa praca ręczna pozostaje odrębną operacją serwisową z jawnie
   niezweryfikowanym reuse, nie gotowym produkcyjnym N1.
2. Zachować bieżącą wersję i konfigurację do rollback. Zweryfikować faktycznie
   wdrożony release: według zadania produkcja to stage-o-28e3ea214660, nie ten
   DEV. Nie zakładać, że samo ustawienie strategii działa w starym release.
3. Przygotować i przejrzeć poza wykonaniem komplet root-owned profili oraz
   minimalne uprawnienia start/stop. Gateway nie może przekazywać arbitralnego
   polecenia roota ani uruchamiać kodu root z zapisywalnego checkoutu.
   Ustalić egzekwowanie odmowy dla wszystkich niezarządzanych ról/aliasów GPU;
   odebrać autonomicznym usługom i endpointom możliwość ominięcia admission.
4. **Boot/autostart:** najpierw polityka OS i zależności chronionych profili,
   potem istniejący obserwator read-only, potem jedyny Gateway w
   `gateway_admission_strategy=n2-dev-blocked`, `gateway_max_concurrency=1`.
   Silniki, Bridge, producenci zadań i timer analizy nie mogą wystartować
   samodzielnie przed bramką. Nie zmieniać obecnie GDM ani konfiguracji boot.
5. Przed dopuszczeniem ruchu sprawdzić startup WARNING i `/status`:
   admission_blocked=true, execution_enabled=false, n1_core_started=false,
   ownership=UNKNOWN; inference i lease mają zwracać 503. Odczyty inventory
   mogą działać; `/health` nie jest dowodem bezpieczeństwa GPU. Restart musi
   zachować blokadę, również przy pustym dzienniku i braku widocznych PID.
6. **Warunek dalszego wdrożenia:** dostarczyć zależności 1–3 powyżej i ich
   odbiór integracyjny, obejmujący błędy, crash/restart, utratę obserwacji,
   odmowę bypassu i zachowanie własności przy niepewnym release. Obecny kod
   nie ma trybu dodatniego grantu. Dopiero kolejna, przejrzana implementacja
   może uruchamiać jeden chroniony silnik EXCLUSIVE; brak/nieświeży dowód
   zatrzymuje następny grant. Producenci i timery wracają na końcu.
7. **Rollback:** zatrzymać przyjmowanie nowych zadań; utrzymać BLOCKED i
   dziennik/własność niepewnego zadania. Operator kończy chronioną jednostkę
   według zatwierdzonego profilu, zachowuje dowody, przywraca zapisany release
   i konfigurację przy wyłączonym ruchu GPU. Nie kasować dirty markerów ani
   nie przełączać na legacy jako sposobu zdjęcia blokady. Nie wznawiać
   automatycznie silników/timerów po rollback; ponowny start wymaga odbioru.

## Walidacja tej zmiany

CPU, limit 120 s, interpreter wymagany w zadaniu:

```bash
PYTHONPATH=src timeout 120 /home/harrypotter/AI-server/.venv/bin/python -m pytest -q tests/test_gateway_n2_integration.py tests/test_gateway_scheduler.py tests/test_gateway_unified_admission.py tests/test_gateway_api.py tests/test_accelerator_admission_n1.py tests/test_os_gpu_boundary.py tests/test_rm_systemd_exclusive_three_engine_dev.py
```

Wynik: **201/201 PASS**, exit 0; ostrzeżenie deprecacji Starlette/httpx.
Test skryptu systemd sprawdza tekst i składnię bash, nie uruchamia usług.
`git diff --check`: PASS. Bez sudo, start/stop usług, pracy GPU, zmian produkcji,
merge, deploy lub push. Nie twierdzimy REAL_N1_GPU_GRANT ani GPU_REUSE_SAFE.

## Niezależna kontrola po zakończeniu Codexa

Sprawdzono pełny, rozszerzony zestaw 23 modułów regresyjnych:
Gateway, N1–N5, CPU/ROCm, OS GPU boundary, leasing, residency,
przejścia i uruchamianie systemd. Wynik **626/626 PASS**, exit 0.
Log lokalny: /tmp/rm-v1-convergence-full-regression-20261019.log.
Jedyny warning: deprecacja Starlette/httpx. Bez GPU, bez działań systemd
i bez zmian produkcji. Nowa bramka nie wystawia faktycznego grantu GPU.

Decyzja operacyjna: V1 systemd EXCLUSIVE = zaliczony jako ręcznie
nadzorowany tryb serwisowy, nie jako automatyczny RM handoff.
