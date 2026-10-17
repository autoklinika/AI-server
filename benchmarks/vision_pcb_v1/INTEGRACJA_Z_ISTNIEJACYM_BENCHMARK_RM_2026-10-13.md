# Vision PCB — integracja z istniejącymi Benchmark Runner i Resource Manager

**Status:** projekt rozwiązania na gałęzi PR #160. Bez wdrożenia do produkcji. 2026-10-13.

## Zasada

**Jeden Resource Manager, jeden scheduler i jeden benchmark framework AI Platform.**
Nie budować drugiego Vision GPU scheduler/pool ani równoległego niezależnego "benchmark managera".
Dodajemy obsługę wizyjnego zadania uruchamianego przez istniejący benchmark framework, przydział zasobów i trwałość dowodów przez wspólne kontrakty.

## Co istnieje w obecnym repo

| Komponent | Weryfikacja w źródle | Faktyczna funkcja |
|---|---|---|
| PriorityScheduler | src/ai_bridge/gateway/scheduler.py | jedna kolejka priorytetowa i sloty |
| ResourceLeaseRegistry | src/ai_bridge/gateway/resource_leases.py | rezerwacja + heartbeat + external use |
| GPUResidency | src/ai_bridge/gateway/residency.py | obecnie przełączanie Ollama ↔ ComfyUI i ich kontrola |
| Benchmark CLI/runner | src/ai_bridge/benchmarks/{cli,runner,platform_client}.py | benchmark LLM/RAG/router; LLM idzie przez Platform API/RM |
| BenchmarkCatalog | src/ai_bridge/benchmarks/service.py | **tylko odczyt historii i katalog**; Vision = planned, run_count=0 |
| Platform API | src/ai_bridge/platform/api.py | /benchmarks (GET), /benchmarks/{suite}/runs (GET), /benchmarks/ai (POST do LLM przez RM) |
| Registry | src/ai_bridge/providers/registry.py | istniejące wyłącznie ollama-local, comfyui-local, hermes-local, strict validate_local_gateway |
| Existing external uses | src/ai_bridge/gateway/app.py | **wyłącznie comfyui-local** dla operacji media; Vision/PyTorch nie jest dopuszczony |

Wynik: nie wolno uznać istniejącego benchmark runnera ani rezerwacji `workload=external` za gotową i autoryzowaną ścieżkę inferencji PyTorch na GPU. Krótkie testy GPU przeprowadzono jako **manualne okna** przy pustej Ollamie i kontrolowanej rezerwacji kolejki, ale to nie zastępuje produkcyjnego protokołu residency.

## Docelowy przepływ

1. Benchmark Runner (wspólny) przyjmuje `suite=vision-pcb-v1`, `model=winclip`, `track=B1` i zamrożony manifest/konfigurację/kody.
2. Jedno zadanie benchmarkowe posiada istniejącą klasę `background` albo `maintenance`; nie powstaje osobny scheduler ani nowy priorytet tylko dla Vision.
3. RM wyznacza przydział **dla wykonawcy GPU Vision** (rozszerzony, wąsko dozwolony binding/capability dla PyTorch, nie podszywa się pod ComfyUI).
4. Przed wydaniem autoryzacji GPU RM sprawdza brak rezydentnych modeli Ollama oraz pusty ComfyUI i zarezerwowany pool.
5. Wykonawca WinCLIP/MiniCPM otrzymuje jednorazowy, ograniczony token; heartbeat podtrzymuje ownership. Runner startuje proces potomny jedynie po potwierdzeniu autoryzacji.
6. Zakończenie: przerwanie/kill i reap procesu, potwierdzenie zwolnienia obiektów/modeli PyTorch i braku procesów wykonawcy, memory evidence (HIP/ROCm); **dopiero potem** zwalniany GPU ownership w RM. Brak lub błąd dowodu => fail closed/blocked, nie zwalniać do Ollamy.
7. Tylko po potwierdzonym cleanup runner finalizuje run: cały dataset, brak leakage, checksumy, image AUROC/AP, opcjonalne AUPRO256 i sprzęt/VRAM/latencja.
8. Read-only BenchmarkCatalog pokazuje stan i historyczne wyniki suite Vision. Publikacja wyników nie oznacza promocji modelu.

## Minimalny zakres implementacji

**Zachowujemy:** istniejący PriorityScheduler, JobState, priorytety, RM, benchmark runner, postęp, schemat dowodów i fail-closed.

**Rozszerzamy kontrolowanie:**
- Zarejestrowanie legalnego wykonawcy/zdolności Vision przez addytywną, wersjonowaną migrację provider registry + strict schema (nie edytować produkcyjnego inventory ad hoc).
- Obecne `ResourceLeaseRegistry` + `GPUResidency`: wyspecjalizowana ścieżka external GPU use o preflight i cleanup niezależnym od ComfyUI.
- Benchmark Runner: `vision-pcb-v1` jako kolejny adapter, zapis predykcji na NVMe; GUI catalog/runs odczytuje raporty.
- Wpięcie w istniejące telemetry/resource sampler z rozróżnieniem system UMA vs peak procesu. Brak fałszywej deklaracji dokładnego dedykowanego VRAM na UMA.

**Nie robimy:** osobnego Vision GPU Manager, drugiej kolejki, ingerencji w bazowy Qwen3.8, adaptery WVC/automotive, nie dopuszczamy direct GPU wywołań bez RM, nie zmieniamy permanentnie domyślnego modelu.

## Bramka DEV i regresje przed jakimkolwiek cutover

- Zero dodatkowych slotów: pojedynczy Vision job wyklucza Ollama i ComfyUI GPU; kolejka/priorytety zachowane.
- Przypadki: 2 równoczesne joby Vision, kolejka WVC i Vision, rozłączenie klienta, crash PID, SIGKILL, timeout, utrata heartbeat, niepoprawny token, brak cleanup evidence, obcy proces GPU, restart Gateway, pusty/aktywny GPU.
- Każdej ścieżce ERROR towarzyszy terminalny job albo blocked RM (bez "orphan lease").
- Sprawdzenie recovery/rollback bez auto-odblokowywania GPU.
- Test realny na WinCLIP, porównanie CPU ↔ ROCm, ścieżka AUPRO256; CI wszystkich istniejących testów resource lease, residency, gateway oraz benchmark.
- Zmiany najpierw na osobnej gałęzi/PR DEV. **Merge i produkcja po decyzji właściciela.**

## Wynik audytu

**REUSE CONFIRMED** — obecny framework benchmarków i RM jest właściwą bazą.
**GAP CONFIRMED** — nie istnieje wspierana produkcyjna trasa dla external Vision/PyTorch GPU: `begin_external_use()` i HTTP `/resource/leases/{lease_id}/uses` dopuszczają obecnie jedynie ComfyUI, a `GPUResidency.leave_media()` sprawdza pamięć ComfyUI, nie PyTorch.

Ten ADR nie potwierdza gotowości do wielogodzinnego uruchomienia GPU. Do tego potrzebna jest minimalna, wspólna ścieżka admission + cleanup.
