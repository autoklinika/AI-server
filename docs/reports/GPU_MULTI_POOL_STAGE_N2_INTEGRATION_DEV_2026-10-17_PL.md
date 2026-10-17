# AI Platform — Stage N2: granica integracji Multi-GPU z Resource Managerem (DEV)

Data: 2026-10-17. Gałąź: feature/gpu-multipool-n2-integration-dev-20261017, bazowy commit N1: 36c1970.
Status: DEV / FAIL-CLOSED / NOT PRODUCTION READY.

## Zakres wykonany
- Rozbudowano istniejący PriorityScheduler, ResourceLeaseRegistry i Gateway o wspólną strategię admission. Nie uruchomiono drugiego schedulera ani procesu.
- Domyślne gateway_admission_strategy=legacy zachowuje dotychczasowe kolejki, WVC, media, leasing, streaming i kontrakty API.
- Jawne gateway_admission_strategy=n2-dev-blocked to wyłącznie blokada bezpieczeństwa przed uruchomieniem nowych zadań; NIE jest działającą implementacją SHARED/EXCLUSIVE na sprzęcie. W tym trybie wszystkie żądania wymagające pracy GPU otrzymują 503 / accelerator_admission_not_verified.
- Jedna blokada jest sprawdzana przez schedulera i wszystkie użycia leasingu, w tym verify_external_use (uprawnienie do wykonania, a nie tylko odczyt). Odmowa nie otwiera ścieżki fallback do legacy.
- Zablokowano także ścieżki Platform API i Knowledge Search/Ask, które mogłyby uruchomić embedding przez osobno skonfigurowany gateway_url, zanim weszłyby do wspólnego schedulera.
- W trybie N2 /status ujawnia NOT_VERIFIED, brak aktywowanego N1 i UNKNOWN dla fizycznej własności każdego GPU. Odczyty /health i /status nie potwierdzają GPU_REUSE_SAFE.
- TTL reaper w zablokowanym trybie N2 nie zwalnia odziedziczonych rezerwacji. Nie utożsamia się job completed, model unloaded, VRAM free, fences synced ani KFD queues empty z GPU_REUSE_SAFE.
- Implementacja N1 (SHARED/EXCLUSIVE, per-GPU budżety, dziennik, generacja, FIFO) pozostaje wewnętrznym komponentem DEV, bez rzeczywistego adaptera bezpieczeństwa. Nie uruchomiono jej równolegle z legacy schedulerem.

## Testy
- Uruchomiono bezpośrednio na hoście, w osobnym worktree DEV, z PYTHONPATH=src i istniejącym Python venv, bez odwołań do realnego GPU: 466 testów PASS w 18 plikach testowych (N1, N2, Gateway, leasing, media, Platform API, N0, Stage O, WVC). Exit=0. Dowód: N2_VALIDATION_OUTSIDE_CODEX_SANDBOX.log.
- 2/2 dodatkowe testy Resource API PASS poza izolacją Codexa.
- Codex sandbox: jego ograniczenia blokowały socketpair i multiprocessing spawn. Pierwotne 503 PASS + 1 test z błędem środowiska zostały rozstrzygnięte przez powtórzenie tego testu poza sandboxem, wynik PASS. Nie zmieniano mechaniki WVC w celu obejścia sandbox.
- Jeden znany StarletteDeprecationWarning dla httpx TestClient; bez wpływu na wynik.

## Kryteria, których NIE spełniamy
1. Weryfikacja fizycznego accelerator_id względem PCI/DRM/KFD, boot generation oraz wykrywanie aliasów jednej karty.
2. Zaufany adapter wykonujący atomową walidację inkarnacji i pełnego drzewa procesów, wyłączenie nowych submitów, zakończenie operacji HIP/KFD i dowód bezpieczeństwa po release.
3. Egzekwowanie rzeczywistych limitów alokacji GPU/unified RAM; obecny N1 rozlicza tylko rezerwacje logiczne.
4. Jedna produkcyjna ścieżka z poprawnym tłumaczeniem metadanych workera na Claim/Grant N1 i scheduler lifecycle (HTTP, lease, media, RAG). N2 obecnie tylko blokuje; nie wpuszcza produkcyjnych zadań do N1.
5. Uwierzytelnienie/isolation bezpośrednich klientów istniejących portów Ollama i ComfyUI na poziomie procesów/OS. Mechanizm Pythona w Gateway nie egzekwuje monopolu wobec procesów omijających Gateway.
6. Testy SIGKILL, power loss, journal corruption, rollback i prawdziwe SHARED/EXCLUSIVE E2E na każdej fizycznej karcie, w tym AMD + Intel Arc.

## Decyzja
- NIE WŁĄCZAĆ N2 na produkcji: włączenie trybu n2-dev-blocked celowo odcięłoby całe obciążenie GPU.
- NIE scalać do main w ramach tego etapu. Utrzymać osobne DEV i Draft PR.
- Następny etap: zaprojektować/prototypować zaufany adapter bezpieczeństwa, fizyczną identyfikację kart i integrację grantu N1 z istniejącym schedulerem. Dopiero po pozytywnych testach CPU/izolacji oraz kontrolowanych GPU E2E dopuszczać SHARED na konkretnych kartach.
- Nie modyfikowano sterowników, BIOS, produkcji, /opt/ai-platform/current ani konfiguracji systemd. Nie było resetu GPU i nie wykonywano testów obciążeniowych w tym etapie.
