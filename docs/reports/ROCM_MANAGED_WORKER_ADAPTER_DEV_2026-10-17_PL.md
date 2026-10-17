# AI Platform — adapter wykonawczy ROCm V1 (DEV)

**Data:** 17.10.2026 | **Host:** Minisforum Radeon 890M gfx1150, Linux 7.0.0-39, PyTorch 2.13.0+rocm10.0.0 / HIP 7.15.
**Gałąź:** feature/rocm-managed-worker-adapter-dev-20261017, bazuje na Gateway ManagedWorker DEV e215026.
**Decyzja:** GO dla kodu i CPU testów; NO-GO dla aktywnego ROCm workera w produkcji, dopóki nie wdrożymy zaufanej autoryzacji i zwalniania sprzętu.

## Wykonano

1. Stały workload `src/ai_bridge/gateway/rocm_test_worker.py`: bez przyjmowania komend od klienta; tylko 64 × 64 float32 matmul (~kilkadziesiąt KiB), kontrola wyniku, `torch.cuda.synchronize(0)`, uwolnienie tensorów/cache i ponowna synchronizacja. Nie importuje PyTorch przy importowaniu pakietu Gateway. Odmawia, jeśli HIP niedostępne, wiele widocznych urządzeń, nieodpowiednia architektura `gfx1150` lub rozbieżna tożsamość PCI. Wynik programu ma `WORKER_LOCAL_SYNC`, **nie** GPU_REUSE_SAFE.
2. PCI binding: kontrola AMD vendor=0x1002, device=0x150e i BDF=0000:c6:00.0 z sysfs. Jeśli opcjonalna właściwość `torch.cuda.get_device_properties(0).pci_bus_id` nie istnieje, kod korzysta z udokumentowanej funkcji HIP `hipDeviceGetPCIBusId` z bibliotek ROCm zainstalowanych razem z PyTorch. Odpowiedź niepoprawna lub brak ABI powodują odmowę. Na serwerze read-only potwierdzono istnienie symbolu eksportowanego z `libamdhip64.so.7`; nie wywoływano go na GPU w tym etapie.
3. `src/ai_bridge/gateway/rocm_managed_adapter.py`: nadzorowany identyfikator workera (N5), stała specyfikacja komendy oraz read-only diagnostyka PCI, /proc, KFD, uchwytów DRM i znanych właścicieli. Brak nowego koordynatora, niezależnego schedulera lub serwisu. Supervisor nie udostępnia metody release/grant ani publicznego HTTP. Bez wstrzykniętego testowego runtime stan `BLOCKED_BY_POLICY` i `gpu_admission=NOT_ADMITTED`. Iniekcja runtime jest **wyłącznie dla CPU testów**; nie ma uruchomienia rzeczywistego GPU.
4. Wykrycie błędu PID birth/boot, niewłaściwego BDF, nieznanych właścicieli, aktywnego KFD lub DRM, procesów potomnych, timeout/crash/cancel, zbyt długiej lub fałszywej odpowiedzi workera utrzymuje `DIRTY`. Nawet pełny zestaw syntetycznych danych przyznaje co najwyżej `GPU_REUSE_SAFE_NOT_VERIFIED`; **nigdy nie jest autoryzacją przydziału następnego GPU joba**. KFD jest wspólne dla urządzeń AMD, nie jest dowodem konkretnego GPU.
5. Domyślny Gateway i konfiguracja runtime pozostają bez zmian. Odrębny użytkownik nie może aktywować workera przez istniejące endpointy. Ścieżka N2 nadal fail-closed, a N1 SHARED/EXCLUSIVE pozostaje w DEV.

## Kontrola bezpieczeństwa i ograniczenia

- Istniejący, root-owned obserwator `ai-vision-gpu-observer` działa odrębnie, tylko read-only, z autoryzacją peer account `ai-gateway-rm` i `ai-vision`. To **właściwy komponent do wykorzystania** przy pełnym przekazaniu GPU — NIE instalować drugiego obserwatora. Obecny kod diagnostyczny `ProcDiagnostics` działa bez uprawnień root, więc przy odmowie odczytów cross-UID zwraca UNKNOWN i nie może samodzielnie poświadczać globalnej czystości.
- Sprawdzenie zakończenia procesowego + lokalne `torch.cuda.synchronize` + chwilowo puste kolejki KFD **nie zapewniają** globalnej blokady nowych submitów, odroczonego sprzątania kernela ani praw do wyłączności nad Radeonem, kiedy Ollama/ComfyUI działają poza kontrolą nowego workera.
- Obecna produkcja udostępnia lokalne API `127.0.0.1:11434` (Ollama) i `127.0.0.1:8188` (ComfyUI). To potencjalna ścieżka omijająca Gateway przez procesy tego samego hosta. **Nie włączać realnego workera przez sam `/resource/leases`**, bo aktualny rejestr pozwala w external use wyłącznie na ComfyUI; PyTorch nie jest zatwierdzonym workload.
- Do fizycznej demonstracji potrzeba autoryzowanego kontraktu w **tym samym** Resource Managerze, izolacji nieznanych klientów, kontrolowanego uruchomienia i niezależnego potwierdzenia zamknięcia jego GPU kontekstu. Nie jest rozsądne wykonywanie próby przez uruchomienie PyTorch „z boku”; konflikt mógłby nasilić wcześniejsze awarie MES.
- Odrębny, wrześniowy raport jądra CVE-2026-89811 dotyczył race KFD/MES podczas usuwania kolejek na gfx1151; nasza karta to gfx1150 i nie stwierdzono obecności tego błędu. Przed bardziej intensywnymi próbami warto potwierdzić, czy pakiet kernela zawiera odpowiednią poprawkę; nie aktualizowano sterownika/OS w tym zadaniu.

## Wyniki testów

- **61/61** focused tests ROCm adapter/payload PASS (tylko CPU/mock, w tym HIP ABI ctypes, fałszywe potwierdzenia, PID reuse, KFD, PCI, crash/timeout).
- **677/677 PASS**: końcowa niezależna regresja na serwerze po wszystkich poprawkach, 23 wybrane pakiety N1-N5, Gateway, Resource API, Stage O, WVC i adapter ROCm. Exit 0. Lokalny zapis: ROCM_FULL_HOST_TESTS.log; bez GPU.
- Jedno stare ostrzeżenie `StarletteDeprecationWarning` w zestawie API; bez regresji.
- Nie uruchamiano nowych procesów GPU ani nie wysyłano sygnałów do Ollama/ComfyUI. Produkcja, kernel, systemd i Resource Manager w /opt pozostają nietknięte.

## Minimalna bramka do **jednego prawdziwego** pilota ROCm

1. Dodać do **obecnego** Gateway wewnętrzną, ściśle allowlistowaną autoryzację `rocm-matmul-64-v1`, która wiąże grant z fizycznym Radeonem oraz oryginalnym PID/cgroup workera, bez publicznego arbitralnego endpointu.
2. Podczas testu wybrać zatwierdzone okno konserwacyjne (lub nieinwazyjnie dowiedzioną niezależność od obecnych procesów). Kontrolować dostęp do Ollama i ComfyUI tak, by nie pojawiał się niezarejestrowany GPU submit; wykorzystać istniejącego observera i procesowego opiekuna. Nie manipulować bezpośrednio MES/sterownikiem.
3. Wykonać pojedynczą małą operację i synchronizację lokalną, po czym zweryfikować zakończenie całego scope, brak przekazanych FD i kolejki KFD/DRM, stan sterownika, pozostałe SHARED owners oraz brak nowego nieznanego submit. Każdy brak dowodu = BLOCKED, bez automatycznego odblokowania.
4. Dopiero po zaliczeniu zakończenia i kontrolowanego ponownego uruchomienia rozważyć SHARED=2 na Radeon 890M, a potem osobne pule dla następnych fizycznie podłączonych kart.

**Status końcowy:** kod adaptera i testy — PASS (DEV). Zaufany hardware E_safe i rzeczywista ścieżka uruchomienia GPU — **NOT VERIFIED**. Nie scalać do main ani nie włączać w produkcji.

## Podstawa techniczna

- AMD HIP [hipDeviceGetPCIBusId](https://rocm.docs.amd.com/projects/HIP/en/docs-10.0.0/doxygen/html/group___driver.html) i [hipDeviceSynchronize](https://rocmdocs.amd.com/projects/HIP/en/develop/reference/hip_runtime_api/modules/device_management.html).
- [Linux KFD process teardown](https://code.googlesource.com/linux/torvalds/linux/+/8abc1c8badc11c859bb4ba43211611347e59c55c/drivers/gpu/drm/amd/amdkfd/kfd_process.c), procesowe cleanup może być asynchroniczne.
- [CVE-2026-89811 (Linux Kernel CVE announce)](https://lists.openwall.net/linux-cve-announce/2026/09/16/36).
