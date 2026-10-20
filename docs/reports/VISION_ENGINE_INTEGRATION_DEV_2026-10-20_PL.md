# Vision → istniejący Resource Manager: etap DEV

Data: 20.10.2026. Baza: `9664cf6`, produkcyjny overlay RM V1.
Gałąź: `feature/vision-engine-integration-20261020`.

**Aktualizacja:** poniżej zachowano stan historyczny etapu `ee28746`. Rzeczywisty executor RADIO został następnie zaimplementowany; aktualny status i komenda pilotażu: [VISION_RADIO_EXECUTOR_READY_2026-10-20_PL.md](VISION_RADIO_EXECUTOR_READY_2026-10-20_PL.md). Instalacja/GPU nadal oczekują na operatora.

## Wynik i granice odbioru

| Etap | Wynik | Zakres dowodu |
|---|---|---|
| Adapter, lease, API i diagnostyka DEV | `DEV_PASS` | 786 testów CPU; kontrakty GPU mają testowe odpowiedzi |
| Rzeczywisty proces CPU | PASS | Krótki proces potomny wykonuje obliczenie CPU; nie analizuje PCB |
| Inferencja RADIO przez RM na GPU | `BLOCKED / NOT_RUN` | Brak dopuszczonego lokalnego wykonawcy RADIO i zweryfikowanego handoff/cleanup |
| Wdrożenie tej integracji | `BLOCKED / NOT_INSTALLED` | Nie wolno instalować nieukończonej integracji |
| Rollback tej integracji | NOT_TESTED | Brak wdrożenia; nie wykonywano cutover ani rollbacku |
| Obecna produkcja | Bez zmian | Gateway IDLE, aktywne/oczekujące zadania i lease = 0; Vision nadal wyłączone |

**To nie jest pełna integracja produkcyjna ani odbiór AnomalyVFM RADIO.** `GPU_PILOT_PASS` i `PRODUCTION_PASS` nie zostały uzyskane. Nie wykonano rzeczywistego przełączenia GPU do RADIO. Wyniki CPU, umowne potwierdzenia w fixture oraz historyczne GPU matmul nie zastępują tego testu.

## Architektura rzeczywista

- Minisforum `harrypotter-AI-Series`: wspólny Radeon 890M, Gateway :11435, Ollama :11434, ComfyUI :8188. Tutaj pozostają checkpoint i runtime **AnomalyVFM RADIO**.
- Runtime: `/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-rocm714-py311`.
- Checkpoint: `anomalyvfm-radio-pilot-20261016/hf_cache/models--MaticFuc--anomalyvfm_radio/snapshots/17654e763c8fae5ae1c44e2ec421a427783d6196/model.safetensors` pod tym samym katalogiem `vision-pcb-envs`.
- Zweryfikowane SHA256 checkpointu: `50a219ba436ed656ad3c0405f9e81df8ad00b2e715c98be66d7e2edb62a83a37`.
- VENTUNO Q `vision`: osobny host pozyskiwania zdjęć i sterowania stanowiskiem, `/srv/vision-data/projects/Vision`. W chwili audytu offline zarówno w Desktop Commander, jak i Tailscale. Nie zbadano jego aktualnego systemu plików ani aktualnie zainstalowanych programów.
- Offline VENTUNO nie blokuje lokalnego pilota RADIO na wcześniej zachowanym obrazie VisA. Blokadą pilota jest lokalna ścieżka wykonania/cleanup.
- Nie dodano adaptera zdalnego: nie ma dowodu, że inferencja tej integracji ma działać na niezależnym GPU VENTUNO. Próba przypięcia zdalnego resource ID do lokalnego adaptera jest odrzucana. Przyszła inferencja zdalna wymaga własnej tożsamości zasobu i odrębnego odbioru; nie należy rezerwować dla niej Radeona Minisforum.

## Zmiany DEV

`VisionLifecycleAdapter` realizuje `prepare()`, `verify_active()`, `release()` oraz jedno `execute()` na użycie istniejącego lease. Kontekst zawiera `lease_id`, `use_id`, `job_id`, a sesja wykonawcy generację, identyfikator workera i `local-primary`.

1. Istniejący `ResourceLeaseRegistry` przyznaje i przypina użycie przed I/O. Weryfikacja wymaga aktywnego ticketu, zgodnego workload i właściciela.
2. `GPUResidency.enter_media()` zachowuje dotychczasowy mechanizm opróżniania runtime. Nie udziela nowego grantu N1 ani nie dowodzi `GPU_REUSE_SAFE`.
3. Zaufany wykonawca musi sam odmówić uruchomienia bez wymaganej autoryzacji. `VisionExecutor` jest wyłącznie zależnością wewnętrzną; nie można go włączyć przez HTTP, nagłówek ani nową zmienną środowiskową.
4. `execute()` dopuszcza jeden zarejestrowany `image_id`. API nie przyjmuje komendy, URL, ścieżki pliku ani wyboru dowolnego modelu. Mapowanie ID na obraz musi dostarczyć przyszły dopuszczony executor.
5. `release()` wymaga zgodnych tożsamości i wszystkich potwierdzeń zaufanego nadzorcy: koniec zadania, wyładowanie modelu, zamknięcie wykonania i autoryzacja release. Nie wolno budować tego potwierdzenia z JSON workera, pustej kolejki, samego exit procesu czy `empty_cache()`.
6. Timeout, anulowanie, utrata sesji lub niepewny cleanup zachowują lease i ustawiają `BLOCKED` oraz trwały marker. Marker blokuje nowy Gateway po restarcie. Również anulowanie po cleanup, przed finalizacją lease, ponownie utrwala blokadę.

Pozostał jeden `PriorityScheduler`, jeden `ResourceLeaseRegistry` i dokładnie cztery stany widoku RM: `IDLE`, `RUNNING`, `SWITCHING`, `BLOCKED`. Widok aktywności adaptera jest dopasowany do właściciela ticketu; nie nadaje prawa wykonania. Istniejące wewnętrzne stany legacy residency pozostały dla kompatybilności.

Rejestry provider/capability i accelerator mają opcjonalne powiązanie `vision-local` / `pcb-inspection` / `local-primary`. Domyślna fabryka Gateway zachowuje poprzedni rejestr i wyłączone Vision. Samo dodanie deskryptora nie dopuszcza wykonania.

## API DEV

API dziedziczy istniejącą granicę lokalnego Gateway/lease. Nie dodano portu, listenera LAN ani zdalnego interfejsu wykonawczego. Identyfikatory lease/use są uprawnieniami dostępu w ramach istniejącego protokołu; nie należy ich logować ani udostępniać innym klientom.

- `POST /resource/leases`, `workload=vision-inspection` — tylko w serwerowo skonfigurowanym wariancie DEV.
- `POST /resource/leases/{lease_id}/uses`, provider `vision-local`, capability `pcb-inspection` — przygotowanie.
- `GET /resource/leases/{lease_id}/uses/{use_id}` — weryfikacja tego samego wykonawcy.
- `POST /resource/leases/{lease_id}/uses/{use_id}/inspect`, jedyne pole JSON `image_id` — jedno wykonanie.
- `DELETE /resource/leases/{lease_id}/uses/{use_id}` — cleanup i rozliczenie użycia.
- `DELETE /resource/leases/{lease_id}` podczas użycia oznacza odroczone zwolnienie; nie zwalnia pracującego GPU. Anulowanie żądania wykonania kończy się blokadą.

Nie ma produkcyjnej implementacji `VisionExecutor` dla RADIO. Implementacja CPU jest wyłącznie fixture w testach i zwraca jawne `execution_kind=CPU_CONTRACT`, `gpu_inference=NOT_RUN`. Nie kopiować jej do runtime jako adaptera GPU.

## Walidacja

Uruchomiono na AI Platform w istniejącym środowisku `/home/harrypotter/AI-server/.venv`, bez importowania modelu ani uruchamiania GPU:

- Końcowa regresja: **786 passed**, exit 0, 6,77 s. Obejmuje 24 moduły testowe: Vision/host preflight, lifecycle, widok RM, Gateway API, leases, kolejkę, residency, priorytety, deskryptory, N0–N5, managed worker, ROCm adapter, Stage O oraz operator cutover/rollback z mockami.
- Testy samej nowej ścieżki: **43 passed**, exit 0; jeden rzeczywisty krótki child CPU, reszta kontrakty i kontrolowane błędy.
- Testy przejść Ollama → Vision → Ollama i ComfyUI → Vision → ComfyUI używają mocków HTTP dostawców oraz fixture CPU. Nie są odbiorem GPU.
- Negatywne przypadki obejmują brak lease, zły owner/workload/use, kolejkę, równoczesne execute, duplikat wykonania, timeout, cancel, awarię prepare/execute/cleanup, stale generation, restart Gateway, niepełne i obce potwierdzenie cleanup, przedwczesny release oraz niewłaściwy resource ID.
- 1 istniejące ostrzeżenie deprecacyjne Starlette/httpx. Brak błędów testów.
- `git diff --check` PASS. Sumy źródeł i testów w `VISION_ENGINE_SOURCE_SHA256_2026-10-20.json`; dowód CPU w `VISION_ENGINE_CPU_TESTS_2026-10-20.log`.

## Kontrola hosta i wdrożenia

`tools/vision_integration_preflight.py` jest narzędziem odczytowym. Nie uruchamia procesów GPU, nie zmienia usług, nie usuwa markerów i nie ma opcji `--apply`. Ta wersja kandydata zawsze zwraca kod 2 z `BLOCKED`, ponieważ nie zawiera dopuszczonego wykonawcy GPU. Nie traktować go jako instalatora ani pełnego verifiera bezpieczeństwa GPU.

Audyt 09:53 CEST: Gateway IDLE, zero lease, `GPU_REUSE_SAFE=NOT_VERIFIED`, produkcyjne Vision niedostępne, runtime i SHA wag RADIO poprawne. Manifest aktywnego overlay oraz identyczność drop-in istniejącego rollbacku potwierdzono odczytowo. Pełny wynik: `VISION_ENGINE_PREFLIGHT_2026-10-20.json`.

Nie zmieniono `/opt/ai-platform/current`, overlay, systemd, grup render/video, uprawnień urządzeń ani sterownika. Nie zatrzymano aktywnych zadań lub usług. Nie instalowano dodatkowych modeli i nie zmieniano zamrożonych danych benchmarku RADIO.

Przyszły pakiet wdrożeniowy musi powstać z aktywnego produkcyjnego overlay i zawierać wyłącznie odebrane zmiany tej integracji; nie należy instalować całej gałęzi ani stosować starego instalatora RM V1 do Vision. Dopiero po prawdziwym pilocie należy przygotować osobny wersjonowany overlay, SHA całej paczki, sprawdzić zgodność zależności, idle preflight, smoke i automatyczny powrót do obecnego overlay przy porażce. Nie przedstawiać tych planowanych kroków jako wykonanych.

Dla niezmienionej produkcji istnieje poprzednio odebrana procedura rollback RM V1 z raportu `RM_ENGINE_PRODUCTION_CUTOVER_ACCEPTANCE_2026-10-20_PL.md`. Nie uruchamiano jej podczas tych prac, nie zaleca się teraz rollbacku działającej produkcji.

## Konkretna pozostała praca

1. Zaimplementować i odebrać zaufany **lokalny** executor RADIO: stały runtime i program, mapowanie obrazu ID do przypiętych danych, rzeczywista inkarnacja workera i pełna kontrola wykonania. Wykorzystać istniejącą granicę bezpieczeństwa/obserwatora; nie dodawać nowej kolejki.
2. Potwierdzić dopuszczalny start i cleanup przy rzeczywistych kontekstach KFD/DRM Ollamy/ComfyUI. Domyślny N3 `NonApprovingSafetyAdapter` oraz `NOT_ADMITTED` pozostają w mocy. Nie zastępować brakującego dowodu bool-em z fixture.
3. Dopiero potem jeden nowy obraz testowy RADIO, kontrola mapy/wyniku, logów sterownika i realne przejścia do Ollamy/ComfyUI przez ten sam RM.
4. Dopiero po PASS przygotować i przetestować wdrożenie oraz rollback tej integracji. Bez scalania do `main` bez akceptacji.

**Nie potrzeba teraz interwencji fizycznej ani samego `sudo`. Blokada jest techniczna: implementacja i sprzętowy odbiór zaufanego wykonawcy/cleanup pozostają nieukończone.** Włączenie VENTUNO nie usuwa tej lokalnej blokady. Zgodnie ze zleceniem nie wdrażamy nieukończonej integracji.
