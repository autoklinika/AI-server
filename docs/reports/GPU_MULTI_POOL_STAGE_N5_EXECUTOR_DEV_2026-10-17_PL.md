# AI Platform — N5: kontrolowany wykonawca i decyzja architektoniczna

**Data:** 17.10.2026 • **Repo:** AI-server • **Gałąź:** `feature/gpu-multipool-n5-executor-dev-20261017` • **Baza:** N4 `af44c1f`
**Stan:** DEV / CPU PILOT PASS / REAL GPU SHARED NOT VERIFIED / PRODUKCJA BEZ ZMIAN

## Decyzja: zgodność z założeniami i korekta kursu

**Architektura pozostaje właściwa**: jeden Resource Manager, jeden punkt przydziału, wiele kart, SHARED i EXCLUSIVE na jednej karcie. **Sposób realizacji N1–N4 wymaga ograniczenia**: powstały dobre kontrakty i 570 testów, ale brakowało wykonawcy rzeczywiście kontrolowanego przez RM i prawdziwego handoff na GPU. Dalsze dokładanie abstrakcyjnych warstw bez funkcji działającej na stanowisku oznaczałoby zboczenie z kursu.

W N5 wybieramy praktyczne rozdzielenie:
- **Managed one-shot jobs** (np. przyszły Vision PCB/benchmark/trening uruchamiany przez RM): RM może nadzorować start, PID inkarnacji, naturalny koniec, reaping i znacznik DIRTY.
- **Long-lived services** (Ollama, ComfyUI, ich workery/child processes): nie utożsamiać końca pojedynczego żądania HTTP z końcem procesu ani oczyszczeniem GPU. Wymagają własnych weryfikowalnych kontraktów i testów zgodności.
- **SHARED:** dla przetestowanych aplikacji i budżetów, bez wymuszania globalnego GPU idle podczas pracy innych właścicieli. **EXCLUSIVE:** blokuje nowe SHARED, oczekuje na rozliczone zakończenie poprzednich, bez preempcji.

## Kod N5

`src/ai_bridge/gateway/managed_worker_observer.py` — mały DEV-only observer; jawnie **nie** jest SafetyAdapter ani punktem wydającym GPU grants. Może uruchomić jeden z góry zdefiniowany, krótki syntetyczny proces Pythona na CPU w osobnej sesji, zapisać trwały marker próby przed startem, sprawdzić boot ID, PID, birth_ticks, session/process group, zweryfikować tę samą inkarnację i zebrać naturalny exit status oryginalnego child handle. Nie przyjmuje dowolnej komendy od klienta; nie wysyła sygnałów do procesów; nie może wywołać N1.release.

Wyjście `PROCESS_CLOSED` oznacza tylko zakończenie **nadzorowanego procesu CPU**. Wyjątek, błędna inkarnacja, cancel, timeout, niezerowy exit lub nieznane dane pozostawiają `DIRTY`. Marker nie jest kasowany. **Nie jest to dowód zamknięcia potomków ani gpu-drain dla KFD/MES.**

`tests/test_managed_worker_n5.py` — syntetyczne przypadki błędów i krótki prawdziwy CPU child, a także symulacja N1 dla 2 urządzeń (dwa SHARED na gpu-0, oczekujące EXCLUSIVE, równoległy EXCLUSIVE na gpu-1). Wykorzystanie testowego `SyntheticAdapter` ograniczone do testów. Test potwierdza, że nawet `PROCESS_CLOSED` nie odblokowuje przydziału, jeżeli verifier N1 nie potwierdził cleanup.

## Wynik i dowody

- **20/20 N5 PASS** w pierwszej serii (CPU pilot + symulacja).
- **590/590 PASS** niezależna regresja poza izolacją Codexa, 21 plików testowych: N1–N5, Gateway, Resource API/leases, N0, Stage O, WVC i Platform API. Exit 0; dowód lokalny `N5_VALIDATION_OUTSIDE_CODEX_SANDBOX.log`. 1 istniejące ostrzeżenie deprecacyjne Starlette.
- Nie uruchomiono obliczeń na prawdziwym GPU; nie dotknięto sterowników, systemd ani /opt/ai-platform/current.
- Weryfikacja runtime hosta: Radeon 890M / kernel 7.0.0-39; Gateway :11435, Ollama :11434 i ComfyUI :8188 nasłuchują na loopback. Procesy na tym samym hoście mogą potencjalnie ominąć Gateway, dlatego samo `127.0.0.1` nie jest egzekwowaniem wyłącznego RM.

## Stan wymaganych możliwości (nie mylić z testem syntetycznym)

| Możliwość | DEV | Prawdziwy GPU |
|---|---|---|
| Rejestr kart, N1 SHARED/EXCLUSIVE, FIFO, limity rezerwacji | PASS (symulacja) | NIEPRZETESTOWANE |
| Nadzór nad krótkim procesem CPU | PASS | Nie dotyczy GPU |
| Niezależne GPU równolegle | PASS (symulacja 2 urządzeń) | NIEPRZETESTOWANE (tylko jedna karta fizyczna) |
| GPU_REUSE_SAFE dla Ollama/ComfyUI | NOT_VERIFIED | NIE |
| Ochrona przed bezpośrednim lokalnym dostępem do runtime | Brak OS gate | NIE |
| Egzekwowanie twardych limitów VRAM/unified RAM | Tylko logiczne budżety | NIE |
| Włączenie produkcyjne | NIE | NO-GO |

## Następne, konkretne kroki — bez rozbudowy architektury

1. **Jedna realna karta, jeden wykonawca**: najpierw odizolować i zweryfikować krótkiego managed job (np. Vision GPU worker) pod kontrolą istniejącego RM. Rzeczywiste mapowanie PCI i tożsamość workera muszą pochodzić z hostowego obserwatora. Bez bezpośredniego bypassu.
2. **Udokumentowany start/stop/cleanup** konkretnego backendu (ROCm/HIP lub PyTorch ROCm, później Intel Level Zero). Worker powinien synchronizować własną pracę; niezależny nadzorca potwierdzać koniec scope i brak nieznanych submitterów. Brak dowodu nadal blokuje reuse.
3. **Mały pilot SHARED2 na Radeon 890M** dopiero po zweryfikowaniu powyższego i po ustaleniu jawnych limitów (RAM hosta + VRAM); 2 lekkie, kompatybilne procesy, kontrola temperatury/MES, bez prób prowokowania resetu. Potem EXCLUSIVE drain i recovery test. Przy niepewności stop/fail-closed.
4. **Następna karta** dopiero po instalacji i weryfikacji fizycznego identyfikatora; osobna pula. Bez wpisywania niepodłączonych W7900/Arc jako aktywnych urządzeń.

**Stop criteria:** nie scalać N1–N5 do main ani nie wdrażać przez systemd, dopóki pojedynczy realny pilot weryfikacji właściciela i kontrolowane przekazanie nie uzyska PASS. Nie dodawać następnej warstwy projektowej bez mierzalnej funkcji.

## Źródła techniczne
- [HIP Device Management](https://rocmdocs.amd.com/projects/HIP/en/develop/reference/hip_runtime_api/modules/device_management.html) — hipDeviceSynchronize dotyczy strumieni bieżącego urządzenia, nie globalnego freeze cudzych procesów.
- [Linux DRM scheduler](https://docs.kernel.org/gpu/drm-mm.html) — ukończenie `dma_fence` jest związane z konkretnym jobem, nie atomową blokadą nowych submitów.
- [KFD process teardown](https://github.com/RadeonOpenCompute/ROCK-Kernel-Driver/blob/master/drivers/gpu/drm/amd/amdkfd/kfd_process.c) — cleanup jest mechanizmem sterownika, a nie równoważnikiem użytkowego `release()`.
