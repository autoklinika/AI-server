# Multi-GPU Resource Manager — Stage N4: protokół zwolnienia zasobu (DEV)
**Data:** 2026-10-17, **gałąź:** feature/gpu-multipool-n4-quiescence-dev-20261017, baza N3 316fce3.
**Status:** DEV; diagnostyka strukturalna PASS, zaufana atestacja GPU_REUSE_SAFE nadal **NOT_VERIFIED**; GPU w produkcji **bez zmian**.

## Co powstało

1. `src/ai_bridge/gateway/accelerator_quiescence.py` — wyłącznie w pamięci, bez I/O, bez GPU i bez nowego schedulera. Typowany `QuiescenceAssessor` z jednorazowym nonce, epoką RM, tożsamością urządzenia (boot ID, PCI), generacją urządzenia, tożsamością workera/PID starttime/scope, lease generacją, rewizją ownership i pełną listą pozostałych SHARED owners. Dane są zawsze klasyfikowane jako **UNTRUSTED**, nawet gdy deklarują „kernel” jako źródło.
2. Sekwencja wymaganych działań: (a) zablokowanie nowych submitów wykonawcy, (b) pełny zakres potomków i przekazanych FD, (c) synchronizacja wszystkich strumieni runtime, (d) zakończenie in-flight prac przypisanych do konkretnego GPU, (e) zamknięcie kontekstów i deferred cleanup, (f) izolacja pozostających właścicieli SHARED. Odrzuca zmianę właściciela/rewizji, inne GPU, brak etapu, replay, zmianę epoki, niezgodność identyfikacji, opóźnienie, czas nieważny lub niepełne/nieznane statystyki.
3. Wynik `ready_for_trusted_verification` oznacza **jedynie kompletność strukturalną**, **NIE pozwala na release ani admission**; `Assessment.decision` zawsze ma wartość `DENY`, a konwersja do bool jest zabroniona. Brak produkcyjnego adaptera E_safe i jego przywilejów.
4. Minimalna poprawka `src/ai_bridge/gateway/accelerator_admission.py` (N1 DEV): limit czasu weryfikacji (domyślnie 5 s) oraz blokada „sukcesu” po czasie i po stłumieniu anulowania taska. Błąd/cancel/timeout nie zwalnia przypiętego grantu, zachowuje blokadę GPU. Nie zmieniono produkcyjnego Resource Managera ani API/HTTP.

## Czego NIE można dowieść obecnymi interfejsami

- `hipDeviceSynchronize()` obejmuje operacje bieżącego urządzenia widziane przez dany runtime; nie poświadcza zamknięcia wszystkich cudzych procesów ani nie blokuje przyszłych submitów.
- `amdgpu_fence_info` / `dma_fence` dotyczą konkretnych kolejek i jobów; nawet gdy wszystkie 15 ringów są chwilowo zsynchronizowane, nie jest to globalna atomowa bariera między procesami.
- Proces terminalny, model unloaded, pusta VRAM, brak aktywnych KFD queues, brak otwartych FD w jednym /proc, albo punktowe GPU busy=0, **nie są** GPU_REUSE_SAFE.
- KFD jest wspólnym uchwytem AMD, nie wolno przypisywać go wyłącznie do jednego GPU. Przy aktywnych SHARED owners nie można wymagać całkowitej bezczynności GPU; wymagana jest izolacja i udokumentowane zakończenie pracy *wycofywanego* właściciela.
- Sam podpis/HMAC danych od workera nie dowodzi stanu sprzętowego. Wszystkie zebrane dowody zewnętrzne N4 pozostają UNTRUSTED; nie ma sposobu zmiany tego statusu samym parametrem konfiguracyjnym.

Źródła dokumentacji: [ROCm HIP — Device management](https://rocmdocs.amd.com/projects/HIP/en/develop/reference/hip_runtime_api/modules/device_management.html), [Linux DRM scheduler — sched_entity](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/scheduler/sched_entity.c), [Linux DRM memory management](https://docs.kernel.org/gpu/drm-mm.html).

## Testy

- Po końcowych zmianach wykonano niezależnie na serwerze, **poza izolacją Codexa**, w izolowanym worktree: **570/570 PASS**, 20 zestawów testowych (N1–N4, Gateway, leasing, Resource API, Stage O, N0, WVC, Platform API, Media). Testy korzystały z mocków/CPU, bez obciążania GPU.
- Dowód: `N4_VALIDATION_OUTSIDE_CODEX_SANDBOX.log`, EXIT 0. Jedno istniejące ostrzeżenie Starlette/FastAPI `httpx`.
- W izolacji Codexa 477 PASS dla dostępnej podgrupy; dwa testy Resource API zawieszały się z powodu ograniczenia `socketpair.send` EPERM, nie z powodu regresji produktu. Niezależna seria 570 PASS obejmuje Resource API.
- Nie wykonywano testów SHARED/EXCLUSIVE na sprzęcie, sygnałów procesom ani resetów GPU.

## N5 — konkretna bramka

Aby N1/N2 kiedykolwiek przyznały rzeczywisty grant, należy osobno dowieść na każdym backendzie / karcie:
1. **Jeden punkt egzekwowania:** wszystkie rzeczywiste ścieżki wysyłania do GPU (Ollama, ComfyUI, Vision, RAG, przyszłe procesy) muszą przechodzić przez ten sam RM lub być OS-owo zablokowane przed ominięciem. Tożsamość konkretnego sprzętu i procesu/pidfd/scope stabilna podczas przydziału.
2. **Weryfikowany release:** niezależny od procesu przekazującego kontroler uniemożliwia dalsze nowe submit-y dla jego inkarnacji/potomków, uzyskuje zakończenie operacji na właściwym urządzeniu i potwierdza zakończenie kontekstu/cleanup przez udokumentowane ABI sterownika/runtime. Należy określić dowód dla każdej wersji AMDGPU/ROCm, Intel Level Zero i innych backendów. Bez tego **fail closed**.
3. **SHARED/EXCLUSIVE:** osobna certyfikacja kompatybilności profili, limity pamięci z uwzględnieniem unified host RAM oraz niezależność aktywnych właścicieli SHARED; nie mylić odczytu pamięci z jej twardym limitem.
4. **Próby negatywne:** replay, zmiana PID/boot/device-generation, dziecko z przekazanym FD, klient spoza RM, crash, SIGKILL, reboot, zniknięcie sterownika i błąd timeout; przy braku pełnego potwierdzenia zawsze BLOCKED.
5. **Akceptacja:** odrębny test na Radeon 890M, następnie przyszłe karty, bez indukowania awarii MES; rollback. Do czasu zaliczenia bramki działający produkcyjny tryb pozostaje bez zmian.

**Decyzja na 17 października:** N4 jest elementem testowalnego kontraktu, **nie jest zaufanym sterownikiem/adaptatorem** i nie umożliwia bezpiecznego fizycznego przekazania GPU. PR wyłącznie Draft, bez merge do main.
