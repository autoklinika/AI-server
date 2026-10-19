# AI Platform — sprzętowy test trzech silników EXCLUSIVE (DEV)
Data: 2026-10-19. Host: harrypotter-AI-Series; GPU: AMD Radeon 890M, PCI 0000:c6:00.0.

## Wynik
**LOCAL_SEQUENTIAL_GPU_ENGINES=PASS_3_OF_3**
**REAL_N1_GPU_GRANT=NOT_ADMITTED**
**REAL_N1_AUTOMATIC_HANDOFF=NOT_RUN**
**GPU_REUSE_SAFE=NOT_VERIFIED**

Użytkownik zatwierdził rzeczywisty test w oknie serwisowym. Uruchomiono trzy osobne, kontrolowane procesy operatora, z jednocześnie najwyżej jednym silnikiem GPU. Są to testy rzeczywistych silników, ale nie zaufany przydział przez N1. Produkcyjny Gateway, Bridge, Ollama, ComfyUI były zatrzymane; GDM został wyłączony wcześniej. Obserwator GPU pozostał aktywny.

## Sekwencja faktyczna
1. Ollama: tymczasowy serwer na 127.0.0.1:11590, model bge-m3 (około 1,16 GB). API embed zwróciło wektor 1024 elementów. Log potwierdził RADV Vulkan na Radeonie 890M oraz GPU offload 25/25 warstw. Podczas przetwarzania Vulkan runner PID 225816 miał widoczny uchwyt DRM. Lider PID 225706. Po wyłączeniu wyłącznie własnej grupy procesów trzy kolejne próbki KFD i fuser były puste. Status OBSERVED_LOCAL_LIFECYCLE_PASS.
2. ComfyUI: osobny serwer na 127.0.0.1:8189, odrębne katalogi DEV i custom nodes wyłączone. System stats potwierdziły urządzenie CUDA:0 AMD Radeon 890M Graphics (PyTorch ROCm). Lider i widoczny klient KFD/DRM PID 226116. Po wyłączeniu trzy kolejne próbki KFD/fuser puste. **Tylko inicjalizacja backendu ROCm, bez generowania obrazu.** Status OBSERVED_LOCAL_LIFECYCLE_PASS.
3. Vision: istniejący sprzętowy worker N5 z ustalonym programem ROCm matrix multiplication 64x64. PID 226387 obserwowany w KFD/fuser podczas działania. Po local HIP sync i naturalnym zakończeniu KFD/fuser nie pokazały aktywnych klientów. Status WORKER_LOCAL_SYNC_AND_CLOSED.

Każde przejście zostało poprzedzone odrębną kontrolą usług, KFD i DRM. Po ostatnim etapie porty testowe nie nasłuchują. W journalctl sprawdzonym od 22:10 CEST brak nowych dopasowanych błędów AMDGPU/MES fault/hang/reset/timeout.

## Material dowodowy i reprodukcja
- hardware-smoke/ollama-bge3-20261019-01/result.json i engine.log (lokalnie)
- hardware-smoke/comfyui-init-20261019-01/result.json i engine.log (lokalnie)
- /srv/ai-data/evaluation/rm-rocm-hardware-pilot/handoff-vision-20261019-01/result.json
- RM_THREE_ENGINE_HARDWARE_SMOKE_EVIDENCE_2026-10-19.json: potwierdzone klasy wyników, PID, ścieżki i SHA256 oryginalnych trzech JSON.
- tools/rm_engine_transition_smoke_dev.py: z góry ustalone porty i silniki, kontrola usług przed testem, pojedynczy lock, zakończenie własnej grupy procesów, trzy kolejne puste próbki KFD/fuser, trwały raport DIRTY w przypadku błędu.
- tests/test_rm_engine_transition_smoke_dev.py: testy negatywne CPU. Nie uruchamiają żadnych serwerów ani GPU.

Nie commitować surowych engine.log — mogą zawierać informacje środowiskowe.

## Ograniczenia i granice bezpieczeństwa
W próbie nie wystawiono prawdziwego grantu N1, nie obchodzono N3 NonApprovingSafetyAdapter ani nie autoryzowano automatycznego release. Kontrolowane kolejno silniki nie były izolowanymi, zaufanymi usługami systemowego systemd. Puste KFD/fuser to jedynie próbki lokalnego stanu, a nie atomowe potwierdzenie driver E_safe ani brak możliwości otwarcia przez inne procesy render.

Nie przetestowano pełnego Qwen3.8 27B ani procesu generowania w ComfyUI; obciążenie było celowo niewielkie ze względu na znane incydenty sterownika MES. Weryfikacja realnej izolacji innych UID, aktywnego PID/cgroup oraz cleanup całego sterownika pozostaje osobnym wymaganiem.

## Kolejne konkretne zadanie
Przenieść istniejące silniki do kontroli jednej, zweryfikowanej ścieżki uruchamiania systemd i RM EXCLUSIVE. Ustalić zaufany kontrakt procesu, cgroup oraz rzeczywistego driver teardown, bez nowego schedulera i bez deklarowania HOT HANDOFF na podstawie lokalnych obserwacji. SHARED nadal poza zakresem.

## Niezależna regresja
Po utworzeniu harnessu operatora i jego siedmiu negatywnych/pozytywnych
testów uruchomiono 22 wybrane moduły N1–N5, Gateway, scheduler, lease,
residency, ROCm, OS boundary oraz EXCLUSIVE checker.
**602/602 PASS**, exit 0. Pełny log na hoście:
 /tmp/rm-three-engine-hardware-regression-20261019.log

Wszystkie trzy silniki mają osobne raporty i zachowano lokalne pełne logi.
Żaden z wyników nie upoważnia do automatycznego N1.recover/release.
