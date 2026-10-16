# Vision PCB — rzeczywisty GPU test przez wspólny Resource Manager

Data: 2026-10-13 (ok. 13:09 CEST). Status: **DEV physical E2E PASS**, nie wdrożenie produkcyjne, nie pełny benchmark jakości.

## Weryfikowany przepływ

- Produkcyjny Gateway (port 11435) działał; preflight: zero aktywnych/oczekujących zadań, zero leases, stan gpu_residency=llm, 0 modeli rezydentnych Ollamy, ComfyUI queue pusta i 0 loaded_models.
- Przed uruchomieniem izolowanego Gatewaya DEV produkcyjna kolejka została zablokowana **czasową rezerwacją** existing ResourceLease API z profilem external/maintenance i heartbeat. Dzięki temu nie było równoległej pracy przez oba Gatewaye.
- Gateway DEV na localhost:11575 uruchomiono z kodu PR #161, feature flag vision_external_enabled=True, osobnym markerem DEV; realne interfejsy lokalnej Ollamy i ComfyUI, a nie ich symulacja.
- ScopedVisionExecutor uruchomił wykonawcę WinCLIP w **dedykowanym systemd user cgroup v2 scope**: vision-bench-486626465694.scope. Proces zaczął pracę dopiero po admission, wydaniu external-use token oraz weryfikacji PID+cgroup przez Gateway.
- Fizyczna inferencja na Radeon 890M gfx1150 poprzez PyTorch 2.12.0+rocm7.14.1 oraz WinCLIP ViT-B-16-plus-240/laion400m_e31, checkpoint SHA256 8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba.
- Dane VisA fold0, holdout PCB3: **2 normal i 2 anomaly**. Są to realne obrazy, ale zbyt mało dla miarodajnej jakości.
- Po wykonaniu: worker i wszystkie procesy w scope zakończone; Gateway DEV potwierdził pusty cgroup, brak Ollama residents, Comfy idle i powrót globalnego VRAM <= baseline + 64 MiB. Rezerwacje obu Gatewayów zwolnione. Gateway DEV zatrzymany. Marker DEV usunięty po walidacji cleanup.
- Produkcja przez cały test: bez deploy, restartów, zmian drivera, Qwen3.8, adapterów, main.

## Rzeczywiste pomiary

| Obraz | Etykieta VisA tylko do ewaluacji | Image score | Czas forward |
|---|---|---:|---:|
| visa-pcb3-normal-0000 | normal | 0.4125345 | 1.092582 s |
| visa-pcb3-normal-0001 | normal | 0.4081132 | 0.703301 s |
| visa-pcb3-anomaly-000 | anomaly | 0.4200236 | 0.705894 s |
| visa-pcb3-anomaly-001 | anomaly | 0.3989162 | 0.718490 s |

- Czas całego nadzorowanego eksperymentu z Gateway DEV: **17.3 s**.
- Czas wykonania przez ScopedVisionExecutor: **16.691 s**.
- Szczytowa zaalokowana pamięć PyTorch GPU: **948 349 440 B** (~949 MB dziesiętnie).
- Ponowne porównanie tych samych 4 obrazów z wersją CPU: warm-median CPU 2.361839 s, warm-median GPU 0.705894 s, **3.3459x speedup**; maks. |delta score| **6.5565e-7**.
- Brak komunikatów amdgpu GPU fault/reset/ring timeout w logu jądra weryfikowanego okresu.
- Po teście: prod Gateway gpu_residency=llm, recovery_required=false, leases=0, active=0, queued=0; Ollama=0 modeli; Ollama i ai-gateway active; DEV port zamknięty.

## Proweniencja i granice

- Surowe predykcje CPU/GPU, logi wykonania i porównanie zapisano wyłącznie na NVMe: /srv/ai-data/evaluation/vision-rm-dev-gate; źródłowy checkpoint jest w osobnym cache.
- Ten test **potwierdza sprzętową ścieżkę RM + GPU, autoryzację i prawidłowe czyszczenie po udanym przebiegu**. Nie potwierdza wszystkich scenariuszy katastrofalnych (SIGKILL/heartbeat-loss podczas rzeczywistego GPU, odłączone procesy o obcym cgroup), a 4 zdjęcia nie pozwalają na rzetelny benchmark jakości.
- Integracja w PR #161 pozostaje feature-gated i **nie została** przeniesiona do produkcyjnego main. Do wielogodzinnego unattended B1 należy domknąć recovery/cancellation testy, review i zgodę na merge/cutover.
- Dotychczasowe 72 predykcje B1 GPU i 319 CPU nie zostały zmieszane ani ponownie obliczone w tym smoke.

**Gate:** PHYSICAL_DEV_RM_ROCM_SMOKE = PASS, PRODUCTION_CUTOVER = NOT AUTHORIZED.
