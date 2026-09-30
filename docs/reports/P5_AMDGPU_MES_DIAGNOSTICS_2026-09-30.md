# P5 AMDGPU/MES — audyt i eksperymenty, 2026-09-30

Status: **ROOT CAUSE NOT CONFIRMED / STABILITY GATE NOT PASSED**.
Gałąź: `fix/p5-amdgpu-mes-stability`, baza: `34d3b9554ca2bbe523e84e7fd74581a46c66c46a`
(`stage-p5.6/discriminating-measurement-v4`). Pełny trening P5.6 nie został wznowiony.

## 1. Wnioski z poziomami pewności

| Poziom | Wniosek | Granica wnioskowania |
|---|---|---|
| confirmed | W ostatniej awarii pierwszym wpisem GPU był MES `MISC (WAIT_REG_MEM)` o 20:35:50.491 CEST. Pierwszy `ring full` o 20:36:28.876, 38.385 s później. | To potwierdza kolejność objawów, nie konkretny błąd źródłowy kernela/firmware. |
| confirmed | Oba nowsze i dwa starsze problematyczne boot’y zaczynają się od 15 timeoutów WAIT_REG_MEM, następnie ring-full. | Liczba komunikatów nie jest liczbą niezależnych awarii. |
| confirmed | Ostatni przebieg P5.6: 33 ukończone kroki, loss 0.61967, 23 min 37 s telemetryki, peak sysfs VRAM 59.55 GiB, minimum MemAvailable 24.40 GiB. | Miary PyTorch allocation/reservation i sysfs VRAM mierzą różne zakresy. |
| highly likely | Pierwotny brak postępu w operacji rejestr/handshake MES powoduje kolejne timeouty, a następnie zapełnienie kolejki. Ring-full jest skutkiem rozwiniętej awarii. | Bez stanu firmware/registra oczekiwania nie znamy powodu utraty postępu. |
| possible | Problem współpracy KFD/GPUVM/TLB invalidation z MES przy alokacji, mapowaniu i zwalnianiu pamięci. | Upstream opisuje podobną klasę; brak dowodu wskazującego dokładny patch dla tego hosta. |
| possible | SVM/userptr, SDMA, churn allocatora, BF16/backward albo firmware mogą wyzwalać problem. | Wymagane porównanie jednoczynnikowe i długie powtórzenia. SVM warnings były w starszych bootach, nie bezpośrednio przed ostatnią awarią. |
| possible | Temperatura, firmware/BIOS lub szczególny podział pamięci unified. | Brak historycznego przebiegu temperatury; nie przypisujemy winy carve-out na podstawie jego rozmiaru. |
| ruled out — dla ostatniego P5.6 | Klasyczny host OOM jako bezpośrednio udokumentowany wyzwalacz: brak wpisów OOM w całym poprzednim boot, duży zapas MemAvailable. Wyczerpanie dysku nie tłumaczy zdarzenia. | Nie wyklucza błędu zarządzania pamięcią, błędów adresowania ani OOM w innych bootach. |
| ruled out — jako wyjaśnienie danych | Założenie „to tylko regresja -34”: identyczny podpis występuje także na -31. | Nie wyklucza błędu wspólnego dla obu kerneli. |

Łańcuch roboczy: **nieustalony trigger pod obciążeniem → brak odpowiedzi MES na
WAIT_REG_MEM → ponawiane timeouty/failed reg_write_reg_wait → ring-full → zatrzymanie
kontenera przez dotychczasowy watchdog**. Nie było automatycznego GPU resetu w zbadanych
incydentach. Zabicie procesu nie stanowi dowodu naprawy stanu GPU.

## 2. Konfiguracja faktycznie odczytana

| Warstwa | Wynik audytu |
|---|---|
| CPU/GPU | Ryzen AI 9 HX 470 / Radeon 890M, PCI `1002:150e`, `0000:c6:00.0`; KFD target 110500 i PyTorch **gfx1150** |
| Host | Ubuntu 26.04 LTS; kernel `7.0.0-34-generic`, pakiet `7.0.0-34.34`, bazowa wersja raportowana w logu `7.0.14` |
| Sterownik | In-tree amdgpu; vermagic zgodny z uruchomionym kernelem; DRM 3.64.0; KFD dodaje urządzenie poprawnie |
| MES | `mes_v11_0`, aktywny ring `mes_kiq_3.1.0`. Parametry modułu `mes=0`, `mes_kiq=0` **nie są dowodem nieaktywnego MES** na tym GPU |
| Firmware | `linux-firmware 20260319.git217ca6e4.1ubuntu`; obecne `gc_11_5_0_mes1.bin.zst` i `gc_11_5_0_mes_2.bin.zst`; VBIOS `113-STRIXEMU-001` |
| Żywy firmware MES | Odczyt debugfs niedostępny dla konta; `sudo -n cat .../amdgpu_firmware_info` wymaga interaktywnego uwierzytelnienia. Bez obchodzenia uprawnień. Nie utożsamiamy pliku na dysku z potwierdzoną wersją w GPU |
| Pamięć | sysfs VRAM 103079215104 B = 96 GiB; host MemTotal 32732946432 B = 30.49 GiB; GTT 15.24 GiB; GART 512 MiB; 8 GiB swap hosta |
| IOMMU/SVA | IOMMU Translated, lazy TLB invalidation; CONFIG_IOMMU_SVA=y, CONFIG_HSA_AMD_SVM=y. Brak aktywnych parametrów wyłączających IOMMU. SVA zbudowane w kernelu nie potwierdza jego użycia przez dany proces |
| Boot firmware warning | ACPI/AMD-Vi: brak pasującego UID dla urządzenia MSFT0201. Występuje również w czystych bootach; nie jest GPUVM fault ani potwierdzoną przyczyną MES |
| Runtime image | `ai-platform-p5-train:rocm7.2.1-v1`, ID `sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8` |
| ROCm/HIP/PyTorch | ROCm 7.2.1; HIP `7.2.53211-e1a6bc5663`; torch `2.9.1+rocm7.2.1.gitff65f5bc` |
| Python packages | transformers 5.17.0; peft 0.21.0; accelerate 1.15.0; safetensors 0.8.0; Python 3.12 w obrazie |
| Środowisko A | Brak HSA/HIP/ROCm/allocator overrides w obrazie i launcherze P5.6; rzeczywisty allocator `native` potwierdzony w workload log |
| Docker P5.6 | `/dev/kfd`, `/dev/dri`, user UID/GID, grupy render/video, `--ipc=host`, `--memory=48g --memory-swap=48g`; brak mountów sterowników hosta do obrazu |
| Docker diagnostyczny | Te same urządzenia/cgroup/IPC; dodatkowo brak sieci, limit 512 PID, repo/model read-only. Rzeczywiste `memory.max=51539607552`, `memory.swap.max=0` |
| Ochrona hosta | 48 GiB cgroup przekracza host RAM 30.49 GiB, więc nie zastępuje ochrony MemAvailable. Harness zatrzymuje test poniżej 8 GiB dostępnej RAM |
| Dysk | `/srv/ai-data`: ~3.4 TiB wolne, zajęcie 4% w momencie audytu |

Hash SHA256 skompresowanych blobów MES:
- mes1: `58e7996aa14821ef7e91628d97afecda6caadd93ff4d906b36840f3dc73dc8b0`
- mes_2: `3da06e0b2f61fb48314000238df24c6871de4207e469b1028d611827cd125966`

## 3. Historia sześciu bootów

Boot offset odnosi się do audytu przy boot ID `df32f64f673541768517f29659878002`.
OOM i SVM w tabeli to liczby pasujących komunikatów, nie liczby incydentów.

| Boot | Kernel | MES WAIT | MES full | KFD errors | GPUVM | Reset | SVM warnings | OOM lines |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | -34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| -1 | -34 | 15 | 30 | 0 | 0 | 0 | 0 | 0 |
| -2 | -34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| -3 | -34 | 15 | 156 | 0 | 0 | 0 | 0 | 9 |
| -4 | -31 | 15 | 945 | 0 | 0 | 0 | 25 | 18 |
| -5 | -31 | 15 | 67 | 0 | 0 | 0 | 20 | 0 |

Brak pasujących runtime IOMMU/SVA fault i kernel watchdog lockup w tych logach.
To nie oznacza braku działania użytkowego watchdog P5.6: jest on osobnym procesem shell,
nie kernel watchdog. Jego skrypt sprawdzał tylko ring-full, co pięć iteracji sekundowych;
w ostatnim incydencie pierwsze rozpoznawalne zdarzenie MES wyprzedzało ring-full o ~38 s.
Nowy harness rozpoznaje już WAIT_REG_MEM. Nie zmieniono istniejącego launchera treningu.

OOM w boot -3 wystąpił wiele godzin przed MES. W boot -4 OOM również poprzedzał MES o godziny.
W boot -5 ostrzeżenie userptr restore pojawiło się 13 s przed pierwszym MES — korelacja,
nie dowód wspólnego mechanizmu ostatniego P5.6. Pełne evidence przechowywane lokalnie.

## 4. Upstream i zgodność wersji

1. [Linux e9f58ff991dd — rework how we handle TLB fences](https://github.com/torvalds/linux/commit/e9f58ff991dd4be13fd7a651bbf64329c090af09):
   ogranicza zbędne TLB fences dla kernel queues i odnosi się do timeoutów KIQ/MES.
   KFD/compute nadal ustawia `need_tlb_fence=true`. Kod w tagu
   [v7.0](https://github.com/torvalds/linux/blob/v7.0/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.c)
   zawiera tę logikę. Host jest oparty na 7.0.14, więc obecność jest bardzo prawdopodobna;
   dokładne źródła dystrybucyjnego pakietu nie zostały pobrane (endpoint Ubuntu zwrócił 403).
   Nie twierdzimy, że patch jest nieobecny ani że jego obecność rozwiązuje KFD training.
2. [ROCR 7.2.1 openclose.c](https://github.com/ROCm/ROCR-Runtime/blob/rocm-7.2.1/libhsakmt/src/openclose.c):
   odczytuje `HSA_USE_SVM`; wartość `0` wyłącza udostępnienie ścieżki SVM API w thunk.
   Symbol/string obecny także w `libhsa-runtime64.so` używanego obrazu. To uzasadnia B;
   nie oznacza globalnego wyłączenia HMM, IOMMU albo wszystkich mapowań GPUVM.
3. [HIP 7.2.1 debugging](https://rocm.docs.amd.com/projects/HIP/en/docs-7.2.1/how-to/debugging.html):
   `HSA_ENABLE_SDMA=0` kieruje odpowiednie kopie przez compute blit. To uzasadnia C i,
   po poprawnej inicjalizacji B/C, interakcję D. Nie jest uniwersalną naprawą MES.
4. [Oficjalna macierz Ryzen ROCm 7.2.1](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html):
   gfx1150 i HX 470 są wymienione; torch 2.9.1/ROCm 7.2.1/Python 3.12 zgodne z tabelą.
   Host Ubuntu 26.04 nie jest OS z tej konkretnej tabeli (24.04.4); deklaracja walidacji dtype
   obejmuje FP16. Samo działanie BF16 nie dowodzi objęcia pełnego stosu oficjalną walidacją.
5. [PyTorch #173367](https://github.com/pytorch/pytorch/issues/173367),
   [ROCm #5665](https://github.com/ROCm/ROCm/issues/5665),
   [TheRock #2684](https://github.com/ROCm/TheRock/discussions/2684): przykłady problemów gfx1151,
   starszych wersji lub współbieżnego kodowania video. Podobny podpis nie upoważnia do
   przypisania tej samej przyczyny gfx1150 ani przeniesienia cudzych obejść jako rozwiązania.
6. [AMD RDNA3.5 memory guidance](https://rocm.docs.amd.com/en/latest/reference/system-optimization/rdna3-5.html):
   opisuje różnice VRAM/GTT oraz specyficzne poprawki dla gfx1151. To kontekst architektury,
   nie dowód, że aktualny 96-GiB carve-out wywołuje awarie. Nie zmieniono tych ustawień.

Nie znaleziono i nie potwierdzono poprawki specyficznie usuwającej nasz podpis pod tym
konkretnym zestawem wersji. Nie wykonano upgrade/downgrade żadnego komponentu.

## 5. Test matrix i stability gate

A: bez overrides; B: `HSA_USE_SVM=0`; C: `HSA_ENABLE_SDMA=0`; D: B+C.
Opcjonalne E: `PYTORCH_ALLOC_CONF=backend:native,expandable_segments:True`, wyłącznie po
potwierdzeniu wsparcia runtime; hipoteza churn/fragmentacji, bez założenia wyniku.
Nie zmieniać kilku dodatkowych flag naraz ani dobierać ustawień na P5.5.

Pełny gate: **3 oddzielne przebiegi po minimum 3600 s każdy**, po załadowaniu Qwen,
zero nowych MES/KFD/GPUVM/reset/IOMMU/OOM/lockup/SVM warnings, poprawne obliczenia i
zakończenie, porównywalny footprint >=52 GiB, MemAvailable >=8 GiB, brak nowych failed units,
zwolnienie VRAM. Ta sama wersja kodu/obrazu/kernela/wariantu; brak nakładających się prób.
W aktualnym P5.6 oszacowanie 65 kroków z pierwszych 33 daje ~2667 s compute (~44.5 min),
więc godzina na powtórzenie daje margines. Gdy pełny czas wzrośnie, wydłużyć gate.

Profile: mały smoke; resident 56 GiB + BF16 backward/copies/churn; następnie rzeczywisty
Qwen BF16 forward/backward + świeża LoRA rank 8 i Adam lr=0, długości 396/900/960/887/399,
wyłącznie losowe tokeny. Nie ładuje adaptera v3 ani checkpointu v4. Żadne wagi nie są zapisywane.
PASS krótkiej próby nie jest PASS stability gate. Ostateczny gate nie dowodzi nieskończonej
stabilności ani pełnej równoważności rozkładu obliczeń z rzeczywistym treningiem.

## 6. Evidence i zachowane granice

Evidence root: `/srv/ai-data/training/p5/diagnostics/mes-20260930/`:
- `audit-v2/`: pełne JSON journal dla sześciu bootów, klasyfikacja, sysfs, image i pakiety;
- `container-static.txt`, `upstream/`: wersje oraz pobrane źródła/patch do weryfikacji;
- podkatalogi prób: result, telemetry, workload log, kernel cursor/tail, Docker launch/state;
- błędy samego harnessu oznaczone oddzielnie, bez przerabiania ich na wyniki GPU.

Skrypty i testy w `tools/mes_stability/` oraz `tests/test_mes_stability.py`.
Nie commitować pełnych logów hosta, lease IDs i unrelated network logów do Git.

`electronics-foundation-v3/current` nadal wskazuje
`electronics-v3-electronics-foundation-v3-replay-r2-20260930`, a SHA256 adaptera to
`2fbcbd394318576d2a50924ad2e3f7b452306566243ede24dd524c6d1b549183`, zgodny z selection v3.
Nie zmieniono P5.5, checkpointów, main, BIOS, GRUB, IOMMU, driverów ani boot parameters.
Obecny boot rozpoczął się o 20:50:43 CEST **przed rozpoczęciem tej diagnostyki**.
Nie wykonano restartu ani resetu GPU.

## 7. Rekomendacja następnego eksperymentu

Po przejściu krótkiej macierzy uruchomić **B na rzeczywistym Qwen BF16 z syntetycznymi
wejściami**, najpierw kontrola pełnej ścieżki forward/backward, potem 3 × 3600 s w świeżych
procesach. B jest hipotezą do sprawdzenia, nie zaakceptowaną zmianą produkcyjną.
Po pierwszym nowym błędzie zatrzymać całą serię i zachować stan/evidence; nie przechodzić
do C/D na tym samym uszkodzonym stanie GPU i nie wykonywać automatycznego restartu.
Wynik B nie uzasadnia samodzielnie zmiany BIOS/kernel/boot ani wznowienia pełnego P5.6.

Wersja uruchomionego MES oraz dokładny zestaw poprawek dystrybucyjnego kernela pozostają
lukami audytu. Odczyt live firmware wymaga udostępnienia uprawnionego odczytu, nie zmiany sterownika.
