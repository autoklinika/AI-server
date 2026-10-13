# Vision GPU — integracja z istniejącym Resource Managerem (DEV)

Status: feature-gated DEVELOPMENT, nie dla produkcji ani automatycznego cutover.

## Architektura

Jeden PriorityScheduler, ResourceLeaseRegistry, GPUResidency oraz wspólny Benchmark Runner. Brak drugiej kolejki i drugiego GPU Managera. Scheduler traktuje **comfyui-local i vision-local jako ten sam wyłączny GPU pool** także gdy max_concurrency>1: najpierw drain wszystkich dotychczasowych jobów, potem brak dopuszczenia innych aż do zwolnienia Vision.

AI_BRIDGE_GATEWAY_VISION_EXTERNAL_ENABLED domyślnie ma wartość false. Przy OFF provider registry i legacy HTTP routes pozostają bez zmian. Przy ON (tylko na odizolowanym DEV Gateway) dostępne są vision-local/image-analysis i workload vision-benchmark z istniejącym priority_class=background.

## Kontrakt wykonania

1. Benchmark Runner uruchamia vision_worker_gate.py w **oddzielnym systemd --user --scope (cgroup v2)**. Proces nie importuje PyTorch/ROCm i czeka na autoryzację w prywatnym katalogu z uprawnieniami 0700.
2. Runner rezerwuje wspólny Resource Lease. Jeśli slot zajęty przez WVC/Ollama/ComfyUI, pozostaje w kolejce; heartbeat utrzymuje reservation.
3. HTTP POST /resource/leases/{lease_id}/uses z provider=vision-local, capability=image-analysis, worker_pid i scope_path. Gateway weryfikuje PID, /proc starttime, zgodność z autoryzowanym cgroup scope, obecność PID w cgroup.procs, pustą kolejkę Comfy, Comfy idle i opróżnienie Ollamy.
4. Marker trwały GPU recovery zapisuje się przed zmianą właściciela. Po przyznaniu use_id dziecko potwierdza token przez GET i wywołuje execv właściwego skryptu, bez zmiany PID.
5. Runner nadzoruje limity i heartbeat oraz czeka na zakończenie procesu i **całego systemd cgroup scope**; na timeout zatrzymuje scope przez systemctl. Po zakończeniu Gateway sam sprawdza zniknięcie PID, pusty cgroup.procs (także potomków), pusty /api/ps, Comfy idle i DRM GPU VRAM used <= baseline + 64 MiB.
6. Brak weryfikowalnego dowodu => fail-closed: state blocked, marker na restart, bez oddawania GPU Ollamie. Normalna ścieżka usuwa marker i oddaje GPU do wspólnego RM.
7. Wyniki benchmarku przechowywane są przez dotychczasowy scorer/manifest i storage na NVMe. Żadna promocja modelu nie wynika z samego zakończenia joba.

## Zakres zrealizowany w DEV

- Rozszerzenie istniejącego provider registry i strict inventory validation wyłącznie przy feature flag.
- Workload vision-benchmark, admission, heartbeat i external-use w istniejących trasach Gateway.
- GPUResidency: osobne enter_vision/leave_vision z kontrolą realnego procesu i globalnego pamięciowego baseline odczytanego **po** unload Ollamy.
- Benchmark Runner: ScopedVisionExecutor z systemd-run user scope, proces zaparkowany do autoryzacji, token przekazywany przez prywatny plik, limity i cleanup. Nie ma już nieweryfikowanego wykonawcy unscoped; wspólny vision_rm_executor.py dostarcza wyłącznie klienta HTTP i wyjątek.
- Testy: brak zmiany legacy OFF, wspólna kolejka, wyłączność Vision/ComfyUI względem Qwen/WVC nawet przy 4 slotach, dwa równoczesne Vision, brak worker_pid/scope_path, memory leak, worker still alive, marker persisted, autoryzacja procesu i release.

## Istotne ograniczenia przed produkcją

DEV wymaga już systemd user scope oraz kontroli cgroup.procs. Proces potomny nie może ominąć własności GPU przez zmianę session/group. Nadal globalny /sys/class/drm/card*/device/mem_info_vram_used jest przybliżony na UMA i nie daje doskonałego dowodu zwolnienia wszystkich kontekstów HIP ani nie wykrywa niezarejestrowanych procesów spoza RM.

Testy in-memory i loopback obejmują rzeczywiste systemd-run scope oraz **prawdziwy odizolowany DEV Gateway z fałszywymi backendami**, ale NIE obejmują fizycznej inferencji GPU przez nową trasę. Nie ustawiać feature flag na produkcji, nie restartować usług, nie kasować GPU marker. Przed cutover wymagane: niezależny review, regresja Stage D/F/G, SIGKILL/timeout/heartbeat-loss/GPU-memory-dirty/restart/recovery/rollback i test prawdziwego WinCLIP z RM. Wciąż nie włączono feature flag na produkcji.

Merge i produkcja wyłącznie po decyzji właściciela.
