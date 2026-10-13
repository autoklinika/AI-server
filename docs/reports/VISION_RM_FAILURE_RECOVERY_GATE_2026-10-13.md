# Vision / Resource Manager — testy awarii i recovery

Data: 2026-10-13. Zakres: PR #161, feature-gated DEV. **Nie scalamy do main.**

## Wynik

- **16/16** przypadków macierzy negatywnej (symulowane /proc, GPU VRAM i backendy HTTP) PASS.
- **4/4** testy rzeczywistego procesu systemd user scope przy symulowanym Gateway (bez obciążenia GPU): SIGKILL, timeout, utrata heartbeat, odłączony potomek po setsid(). PASS.
- Pełny suite AI Platform, istniejące Gateway/ComfyUI/WVC/benchmark tests: **EXIT 0** na hoście, bez błędów ani dodatkowych skipów. CI dla najnowszego commitu wymaga ponownego potwierdzenia.
- Produkcyjne usługi pozostają aktywne, main czysty, GPU residency bez recovery, Ollama bez modelu rezydentnego.

## Macierz negatywna — mock GPU, izolowane DEV markery

| Klasa błędu | Oczekiwane zachowanie | Wynik |
|---|---|---|
| Worker nadal żyje | nie zwalniaj GPU, marker blocked | PASS |
| PID reused | odmowa i trwała blokada po admission | PASS |
| Osierocony proces w cgroup | odmowa release, marker blocked | PASS |
| Brak evidence cgroup | fail-closed | PASS |
| Pozostawione >64 MiB VRAM ponad baseline | fail-closed | PASS |
| Niedostępny licznik VRAM | fail-closed | PASS |
| Ollama załadowała model podczas Vision | fail-closed | PASS |
| Zajęte ComfyUI po Vision | fail-closed | PASS |
| ComfyUI loaded_models > 0 | fail-closed | PASS |
| Zajęte ComfyUI przed admission | blokada + marker po rozpoczęciu przejęcia | PASS |
| Błędny ComfyUI residency inventory przed admission | fail-closed | PASS |
| Worker nie istnieje **przed** admission | odmowa przed pin, zwolnienie rezerwacji, bez fałszywego markera | PASS |
| PID zmienia tożsamość w trakcie admission | fail-closed + marker | PASS |
| Utrata heartbeat w fazie aktywnej | lease nie wygasa automatycznie; trzeba potwierdzić cleanup | PASS |
| PID znika po preflight, ale po przypięciu ownership | trwale zapisany marker i aktywny slot | PASS |
| Restart Gateway przy markerze po nieudanym cleanup | WVC i Vision pozostają queued, brak admission | PASS |

## Testy prawdziwego cgroup, bez fizycznego obciążenia GPU

1. **SIGKILL** procesu zaparkowanego/uruchomionego z tokenem: brak fałszywego SUCCESS; dziecko reaped; cleanup i release lease: PASS.
2. **Timeout**: systemctl --user stop scope; brak w żywym cgroup; cleanup/release: PASS.
3. **Heartbeat loss**: kontrolowane HTTP 503 podczas aktywnej fazy, executor zamyka scope; cleanup/release: PASS.
4. **Detached descendant**, proces potomny z `setsid()`: nie może uniknąć cgroup. W razie zagrożenia parent executor zatrzymuje **cały** scope, również kiedy oryginalny PID już zakończył działanie: PASS.

## Rzeczywiste błędy znalezione podczas testów i poprawki

**BUG 1 — early worker exit leaves pinned lease without persistent marker.**
Poprzednia implementacja przypinała external use ID przed sprawdzeniem, że proces Vision jeszcze istnieje. Jeśli probe natychmiast zwracała `None`, scheduler przechodził w `admission_blocked`, lecz `GPUResidency.state=llm`, a marker nie istniał: restart mógł błędnie otworzyć GPU.

Naprawa:
- Weryfikacja PID / starttime / cgroup scope i członkostwa cgroup **przed** przypięciem ownership w ResourceLeaseRegistry.
- Jeśli tożsamość zmieni się już **po** pin, synchronizowany `GPUResidency.fail_closed()` zapisuje trwały marker i ustawia blocked.
- Test regresji dla wyścigu zniknięcia PID przed markowaniem recovery.

**BUG 2 — detached cgroup child after main PID exit.**
Cleanup executora wcześniej zatrzymywał scope tylko, gdy proces nadrzędny `systemd-run` nadal pracował. Nowa ścieżka sprawdza cgroup także po jego zakończeniu i próbuje zatrzymać cały scope. Nie uznaje ukończenia dopóki cgroup nie jest pusty; w przeciwnym przypadku fail-closed.

## Bezpieczeństwo i niezbadany zakres

- Wszystkie testy awaryjne uruchomiono w osobnych tmp dirs, fake HTTP / mock GPU evidence; trwałe markery awarii były **wyłącznie DEV**.
- Wynik nie jest testem fizycznego SIGKILL podczas aktywnych jąder ROCm. Nie wykonano destrukcyjnego GPU fault injection na wspólnym hoście produkcyjnym z powodu historycznych incydentów GPU i braku zatwierdzonego produkcyjnego protokołu przejmowania w przypadku DEV marker.
- Rzeczywista poprawna inferencja GPU przez ten sam RM ma odrębny PASS: `docs/reports/VISION_RM_REAL_ROCM_GPU_SMOKE_2026-10-13.md`.
- Ostatnie testy crash/restart/RM należy odtworzyć podczas niezależnego przeglądu DEV, a **dopiero potem** wykonać kontrolowany cutover za zgodą właściciela.
- Feature flag `AI_BRIDGE_GATEWAY_VISION_EXTERNAL_ENABLED` pozostaje OFF na produkcji. Main, Qwen3.8 i adaptery nietknięte.

**Gate: DEV mock fault/recovery PASS; physical GPU fault/recovery destructive gate NOT RUN; production promotion NOT AUTHORIZED.**
