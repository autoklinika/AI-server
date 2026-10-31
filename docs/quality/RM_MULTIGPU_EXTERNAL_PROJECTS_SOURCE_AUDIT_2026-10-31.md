# Audyt porównawczy kodu GPUStack, LocalAI i Lemonade — AI Platform Multi-GPU

**Data:** 2026-10-31  
**Status:** statyczna weryfikacja kodu źródłowego i dokumentacji upstream; bez uruchamiania programów, bez importowania kodu, bez zmian w produkcji.  
**Cel:** przed P2-A4 i P2-B ustalić, które sprawdzone wzorce poprawiają nasz *jeden* Resource Manager (RM), a które są nieodpowiednie dla mieszanego AMD UMA + niezależne RTX.

## 1. Zweryfikowane snapshoty upstream

| Projekt | Repozytorium i przypięty commit | Licencja repo | Profil |
|---|---|---|---|
| GPUStack | [gpustack/gpustack@6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e](https://github.com/gpustack/gpustack/tree/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e) | Apache-2.0 | Scheduler i pracownicy klastra GPU, szacowanie wymagań modelu, placement |
| LocalAI | [mudler/LocalAI@bec9638242be915389631532b22d7dff394a059f](https://github.com/mudler/LocalAI/tree/bec9638242be915389631532b22d7dff394a059f) | MIT | Nadzorowanie procesów backendów, load jobs, fencing, eviction |
| Lemonade | [lemonade-sdk/lemonade@d752171f99a34660943b52dec123c94be8275d00](https://github.com/lemonade-sdk/lemonade/tree/d752171f99a34660943b52dec123c94be8275d00) | Apache-2.0 | Router modeli, pamięć rezydentna, model lifecycle, LRU/VRAM pressure |

Wskazane commity zostały odczytane z gałęzi domyślnych 2026-10-31. Analiza dotyczy **konkretnie przypiętych wersji**, nie obietnicy, że ich implementacja pozostanie taka sama. Licencja repozytorium nie jest automatyczną zgodą na przenoszenie dowolnego pliku lub zależności: w tym pakiecie **nie kopiowano kodu** i nie dodano zależności.

## 2. GPUStack — co realnie robi kod

1. [`scheduler/scheduler.py`, sekcja grupowego placementu](https://github.com/gpustack/gpustack/blob/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e/gpustack/scheduler/scheduler.py#L400-L463): próbuje umieścić cały zestaw członków modelu; przy braku dopasowania nie zapisuje częściowych przydziałów. Po znalezieniu rozwiązania wykonuje zbiorczy zapis placementu. **Wniosek:** mamy stosować ofertę zasobów dla *całego bundle* oraz atomowy commit w istniejącym RM. Transakcja w bazie GPUStack **nie dowodzi**, że fizyczne GPU są już zajęte i bezpiecznie zwalniane — ten protokół musi być osobny.
2. [`policies/resource_view.py`](https://github.com/gpustack/gpustack/blob/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e/gpustack/policies/resource_view.py#L13-L152): nalicza zaalokowaną pamięć RAM i VRAM **per GPU index**, dodaje rezerwacje spoza modeli, odlicza rezerwę systemową. `ResourceView.with_model_instances` pozwala symulować ponowny przydział bez pobierania live stanu. **Wniosek:** kierunek naszego P1 jest sensowny (jedna niewykonawcza ocena), ale ostateczny commit musi ponownie sprawdzać *revision/generation*.
3. [`scheduler/calculator.py`](https://github.com/gpustack/gpustack/blob/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e/gpustack/scheduler/calculator.py#L54-L95) rozdziela szacunki RAM/VRAM (w tym UMA/non-UMA) i wykonuje kalkulacje dla GGUF. **Wniosek:** szacunki specyficzne dla backendu/modelu są lepsze od stałej rezerwy dla „LLM”; zapotrzebowanie to nie jest telemetria ani wykonanie rezerwacji.
4. [`worker/workload_cleaner.py`](https://github.com/gpustack/gpustack/blob/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e/gpustack/worker/workload_cleaner.py#L108-L167): w razie błędu odczytu listy żywych benchmarków **pomija** w tej rundzie sprzątanie; nie myli utraty telemetrii z osieroconym zadaniem. **Wniosek:** brak danych = blokada wyzwalania cleanupu, nie dowód zwolnienia.

**Ważne ograniczenie wykryte w kodzie:** [`worker/collector.py`](https://github.com/gpustack/gpustack/blob/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e/gpustack/worker/collector.py#L160-L166) ustawia flagę `is_unified_memory` dla całego hosta na podstawie **pierwszego GPU**; [`resource_view.py`](https://github.com/gpustack/gpustack/blob/6e3a42a9d3d59eb6f11407ed5cb96d5840c3f48e/gpustack/policies/resource_view.py#L99-L143) w gałęzi UMA ogranicza `allocatable.vram[0]`. **Nie należy kopiować tych założeń do naszej heterogenicznej topologii:** Radeon UMA i RTX są fizycznie różnymi domenami i nie musi być prawdą, że GPU nr 0 reprezentuje pamięć wszystkich akceleratorów. To ograniczenie modelu w analizowanym kodzie, nie formalne rozstrzygnięcie wszystkich przypadków, które GPUStack obsługuje.

## 3. LocalAI — cenne wzorce właściciela procesu i fencing

1. [`core/services/worker/process_ledger.go`](https://github.com/mudler/LocalAI/blob/bec9638242be915389631532b22d7dff394a059f/core/services/worker/process_ledger.go#L14-L115): worker zapisuje w małym dzienniku identyfikator uruchomionego backendu, PID i pole `starttime` odczytane z `/proc/PID/stat`. Po restarcie porównuje czas utworzenia PID, żeby nie pomylić procesu z innym, który otrzymał ten sam numer. Na Linuksie może sprzątać osierocone grupy procesów.
   - **Do zastosowania:** trwały rejestr *własnych* workerów, z zapisem przed uznaniem rezerwacji za aktywną, boot epoch, startticks, lease owner/generation oraz GPU UUID.
   - **Nie kopiować zachowania automatycznego SIGKILL 1:1**: ich dziennik dotyczy procesów uruchomionych przez danego workera; u nas Ollama/ComfyUI/Vision mogą posiadać niezależne procesy i uchwyty GPU. Bez niezależnego dowodu własności oraz quiescence zatrzymanie PID nie jest bezpiecznym cleanupem GPU.
2. [`core/services/nodes/load_job_runner.go`](https://github.com/mudler/LocalAI/blob/bec9638242be915389631532b22d7dff394a059f/core/services/nodes/load_job_runner.go#L128-L238): ładowanie modelu należy do **rekordu job+generation**, a nie do połączenia HTTP. Utrata lease / zmiana generacji powoduje anulowanie właściciela; zapis i stop mają osobne, ograniczone konteksty, a niepewne zdalne wykonanie jest nadal traktowane jako mogące trwać.
   - **Do zastosowania:** owner token, epoch, fencing i operacje cleanup, które przeżywają przerwanie żądania klienta.
3. [`core/services/nodes/reconciler_abandoned_load.go`](https://github.com/mudler/LocalAI/blob/bec9638242be915389631532b22d7dff394a059f/core/services/nodes/reconciler_abandoned_load.go#L29-L138): niepewne rekordy ładowania zachowują slot; brak odczytu bazy lub node nie oznacza, że zadanie bezpiecznie znikło. **Do zastosowania:** `UNCERTAIN/QUARANTINED` obciąża rezerwację do czasu wiarygodnej weryfikacji.
4. [`pkg/vrambudget/budget.go`](https://github.com/mudler/LocalAI/blob/bec9638242be915389631532b22d7dff394a059f/pkg/vrambudget/budget.go#L96-L129): operator może ustawić limit procentowy/absolutny, ale kod nie pozwala zawyżyć wykrytej wielkości VRAM — stosuje minimum z limitem. **Do zastosowania:** nieprzekraczalny konserwatywny pułap każdego fizycznego budżetu.
5. [Dokumentacja LocalAI: VRAM management](https://localai.io/docs/advanced/vram-management/): LRU, limit liczby załadowanych backendów, `concurrency_groups`, idle/busy watchdog, unikanie eksmisji aktywnych żądań. [Dokumentacja trybu rozproszonego](https://github.com/mudler/LocalAI/blob/bec9638242be915389631532b22d7dff394a059f/docs/content/features/distributed-mode.md): dla rozpoznanych *NVIDIA unified-memory SoC* VRAM jest raportowany w odniesieniu do RAM/`MemAvailable`, a RAM i VRAM raportuje się oddzielnie.
   - **Uwaga:** ich autodetekcja Jetson/GB10 **nie jest** atestacją naszej AMD 890M. Ich scheduler i globalny LRU **nie zastępują** istniejącego RM.

## 4. Lemonade — rezydencja, bezpieczne wyładowanie i ryzyko licznika AMD

1. [`src/cpp/server/router.cpp`](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/src/cpp/server/router.cpp#L295-L374): pule modeli są rozdzielone według typu i klasy rezydencji; w LRU pomija modele przypięte. Ten wzorzec można wykorzystać do przyszłej polityki `PINNED/IDLE/EVICTABLE` **dopiero po** właściwych przydziałach.
2. [`src/cpp/server/eviction_engine.cpp`](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/src/cpp/server/eviction_engine.cpp#L59-L175): ochrona sesji wyłącznej, modeli `pinned` oraz `IN_USE`, najpierw sprawdzenie bezczynności, potem *atomowe ponowne sprawdzenie* przed downsize/eviction; koszt ponownego załadowania modelu wpływa na priorytet usuwania.
3. [`router.cpp` — eviction/timeout/tombstone](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/src/cpp/server/router.cpp#L660-L710): przed zniszczeniem backendu czeka na zakończenie bieżących żądań; gdy nie można tego potwierdzić, pozostawia „tombstone” do późniejszego sprzątania. **Do zastosowania:** odroczone zwalnianie i formalny stan niepewności.
4. [`global_vram_monitor.cpp`](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/src/cpp/server/global_vram_monitor.cpp#L35-L61): globalny odczyt presji VRAM jest włączany opcjonalnie. **Nie używać** procentowego *global* VRAM jako autoryzacji na konkretną RTX ani sygnału do ubicia modelu na innej karcie. [Dokumentacja multi-model](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/docs/guide/configuration/multi-model.md) opisuje LRU i `auto_evict`.
5. **Szczególnie istotne dla naszego AMD:** [`src/cpp/server/platform/metrics_linux.cpp`](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/src/cpp/server/platform/metrics_linux.cpp#L55-L110) w przypadku wykrytego *shared* AMD raportuje `memory_total_gb` jako **`vram_total + gtt_total`** i analogicznie zużycie. W rozpatrywanym kodzie jest to telemetria, **nie zweryfikowany niezależny budżet fizycznych bajtów**. Gdy u nas DRM pokazuje 96 GiB VRAM, GTT około 15,24 GiB, a CPU tylko około 30,48 GiB `MemTotal`, kopiowanie tej sumy do RM jako „wolnej pamięci” groziłoby fikcyjną pojemnością. **Zabronić** tego w naszym accounting.
6. [`src/cpp/server/server_process.cpp`](https://github.com/lemonade-sdk/lemonade/blob/d752171f99a34660943b52dec123c94be8275d00/src/cpp/server/server_process.cpp#L23-L57): kontroluje uruchamianie i zatrzymywanie własnego procesu backendu. **Nie dowodzi** pełnej bezczynności cudzych procesów/urządzeń.

## 5. Macierz decyzji dla naszego AI Platform (AMD 890M + RTX A + planowana RTX B)

| Mechanizm | Źródło inspiracji | Decyzja dla RM |
|---|---|---|
| Fit/propozycja modelu z RAM/VRAM dla każdej GPU | GPUStack | **TAK** — P1 już istnieje; uzupełnić o zweryfikowane dane i atomowy commit |
| Wszystkie zasoby albo żaden, jednolita generacja | GPUStack | **TAK** — w jedynym RM, nie nowy scheduler |
| Trwały rejestr własnych workerów + PID birth time | LocalAI | **TAK** — rozszerzyć o owner lease/epoch, GPU UUID oraz zakres procesu |
| Lease generation/fencing, retry i niepewne zadania obciążają zasoby | LocalAI | **TAK** — do zatwierdzenia w P2-A4 |
| Model pinned / active request prevents eviction | LocalAI/Lemonade | **TAK** — późniejsza polityka rezydencji, decyzja tylko jednego RM |
| Automatyczne SIGKILL osieroconych procesów przy starcie | LocalAI | **NIE automatycznie** — tylko po dowodzie własności, w kontrolowanym cleanup |
| GPUStack „UMA z pierwszego GPU”, `vram[0]` | GPUStack | **NIE** — nie odpowiada heterogenicznej AMD+RTX topologii |
| `vram + gtt` jako rzeczywista przestrzeń do przydziału | Lemonade telemetry | **NIE** — wartości nie są rozłącznym budżetem |
| Globalny LRU i globalny VRAM pressure jako controller kart | LocalAI/Lemonade | **NIE** — potrzebne per-GPU oraz jawne fault domains |
| Nowy cluster/SmartRouter/NATS/Kubernetes na jeden serwer | GPUStack/LocalAI | **NIE** — obecny RM już jest centralnym koordynatorem |
| Dokładne skopiowanie upstream code | Wszystkie | **NIE** — wzorce implementujemy samodzielnie; w razie kopiowania osobny audyt licencji i atrybucji |

## 6. Zmiana planu po audycie

Dotychczasowe P2-A2/A3 są **sensownym odczytowym DEV**, ale nie powinny prowadzić automatycznie do P2-B. Zalecana kolejność:

**P2-A4.1 (następny mały PR, bez sprzętu):** określić zaufany kontrakt `RM lease_id + lease_generation + RM epoch + boot_id + worker/process-group id + PID/startticks + GPU UUID + GPU incarnation + backend + use_id`. Trwały, atomowo zapisywany owner journal dla workerów **kontrolowanych przez RM**, z testami stale owner, PID ABA, przerwanym żądaniem, restartem. *Nie* włączać autokillu ani alokacji.

**P2-A4.2 (osobny odczytowy raport):** zebrać nieinwazyjne dowody dotyczące rzeczywistego mapowania AMD/CPU (firmware/BIOS, kernel/DRM/HSA, RAM/GTT). Nie zamieniać bezpośrednio GPUStack/Lemonade heurystyk na pojemności RAM. Dopóki relacja pozostaje niepotwierdzona, ten obszar **UNKNOWN / BLOCKED**. Nie uruchamiać obciążeniowych stress testów na produkcyjnym serwerze bez odrębnej zgody.

**P2-A4.3 (osobna niezależna recenzja):** ocena kontraktu pod kątem lost update, fencing, zaufanych zdarzeń cleanup i multiple GPU failure domains. Tylko przy rzeczywiście trudnym concurrency/recovery można wykorzystać Codexa.

**P2-B (nadal zablokowany):** atomowe rezerwacje w **istniejącym** RM po akceptacji P2-A4. *Reserve → revalidate generation → commit all-domain bundle → start owned worker → monitor → confirmed stop/quiescence → release*, w przeciwnym razie kwarantanna zajętej domeny. Nigdy „wolna VRAM”, koniec requestu czy brak PID jako samoistny sygnał `SAFE_TO_REUSE`.

**P2-C:** odporne recovery i testy na realnych kartach dopiero po osobnej zgodzie. W żadnym etapie nie scalać automatycznie z `main` ani nie ruszać produkcji.

## 7. Granice pewności audytu

To **źródłowy audyt wybranych mechanizmów**, a nie formalna pełna analiza całych trzech repozytoriów, benchmark ani dowód braku innych zabezpieczeń w pozostałym kodzie. Nie uruchamiano systemów upstream. Oceny, co można adaptować, są rekomendacją dla naszego projektu — nie oświadczeniem autorów upstream. Istnienie funkcji rejestru/process/allocator **nie jest** gwarancją ich niezawodności we wszystkich awariach GPU.

Licencje podane są na poziomie repozytorium; brak kopiowanych fragmentów source, brak nowych bibliotek, zmian production config, modeli, `systemd` ani GPU. Raport ma charakter dokumentacyjny i pozostaje na osobnej gałęzi do przeglądu.
