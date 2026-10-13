# Vision GPU — integracja z istniejącym Resource Managerem (DEV)

Status: feature-gated DEVELOPMENT, nie dla produkcji ani automatycznego cutover.

## Architektura

Jeden PriorityScheduler, ResourceLeaseRegistry, GPUResidency oraz wspólny Benchmark Runner. Brak drugiej kolejki i drugiego GPU Managera.

AI_BRIDGE_GATEWAY_VISION_EXTERNAL_ENABLED domyślnie ma wartość false. Przy OFF provider registry i legacy HTTP routes pozostają bez zmian. Przy ON (tylko na odizolowanym DEV Gateway) dostępne są vision-local/image-analysis i workload vision-benchmark z istniejącym priority_class=background.

## Kontrakt wykonania

1. Benchmark Runner uruchamia vision_worker_gate.py jako proces, który **nie importuje PyTorch/ROCm i czeka na potoku**.
2. Runner rezerwuje wspólny Resource Lease. Jeśli slot zajęty przez WVC/Ollama/ComfyUI, pozostaje w kolejce; heartbeat utrzymuje reservation.
3. HTTP POST /resource/leases/{lease_id}/uses z provider=vision-local, capability=image-analysis i worker_pid. Gateway weryfikuje PID + /proc starttime, pustą kolejkę Comfy, Comfy idle i opróżnienie Ollamy.
4. Marker trwały GPU recovery zapisuje się przed zmianą właściciela. Po przyznaniu use_id dziecko potwierdza token przez GET i wywołuje execv właściwego skryptu, bez zmiany PID.
5. Runner nadzoruje limity i heartbeat oraz czeka na zakończenie procesu i jego process group. Po zakończeniu Gateway sam sprawdza zniknięcie PID, pusty /api/ps, Comfy idle i DRM GPU VRAM used <= baseline + 64 MiB.
6. Brak weryfikowalnego dowodu => fail-closed: state blocked, marker na restart, bez oddawania GPU Ollamie. Normalna ścieżka usuwa marker i oddaje GPU do wspólnego RM.
7. Wyniki benchmarku przechowywane są przez dotychczasowy scorer/manifest i storage na NVMe. Żadna promocja modelu nie wynika z samego zakończenia joba.

## Zakres zrealizowany w DEV

- Rozszerzenie istniejącego provider registry i strict inventory validation wyłącznie przy feature flag.
- Workload vision-benchmark, admission, heartbeat i external-use w istniejących trasach Gateway.
- GPUResidency: osobne enter_vision/leave_vision z kontrolą realnego procesu i globalnego pamięciowego baseline odczytanego **po** unload Ollamy.
- Benchmark Runner: lokalny proces zaparkowany do chwili potwierdzenia autoryzacji, ścisłe limity i cleanup.
- Testy: brak zmiany legacy OFF, wspólna kolejka, brak worker_pid, memory leak, worker still alive, marker persisted, autoryzacja procesu i release.

## Istotne ograniczenia przed produkcją

DEV używa process group i globalnego /sys/class/drm/card*/device/mem_info_vram_used. Taki pomiar jest przybliżony na UMA i **nie potwierdza** braku odłączonego procesu, który zmienił session/group. Konieczny cgroup v2/systemd-scope owner i udokumentowana walidacja wszystkich potomków oraz rzeczywistego HIP cleanup.

Testy in-memory i loopback NIE są fizycznym testem produkcyjnym. Nie ustawiać feature flag na produkcji, nie restartować usług, nie kasować GPU marker. Przed cutover wymagane: niezależny review, regresja Stage D/F/G, SIGKILL/timeout/heartbeat-loss/GPU-memory-dirty/restart/recovery/rollback i test prawdziwego WinCLIP z RM.

Merge i produkcja wyłącznie po decyzji właściciela.
