# RTX 5060 Ti / TBGAA — wysoka zajętość VRAM i test mocy bliskiej 180 W

Data: **2026-10-23**, AI Platform Minisforum `harrypotter-AI-Series`, Ubuntu 26.04, kernel 7.0.0-39-generic, NVIDIA Open Driver **615.71.09**, Ollama CUDA 13 / cuBLAS 13.

**Boot ID:** `067e4fa7-1585-4f81-86fd-30cd6cc4e6ea`.

## Werdykt

**HIGH_VRAM_PASS + NEAR_POWER_PASS.** Dwa niezależne, kontrolowane testy rzeczywistej RTX 5060 Ti. Nie zaobserwowano NVIDIA Xid, PCIe AER ani utraty łącza podczas obu testów. Po testach GPU wrócił do trybu P8 i **2 MiB zajętej VRAM**, bez pozostawionych procesów CUDA; Resource Manager IDLE, AI Platform zdrowa.

**Nie testowano jednoczesnego pełnego zajęcia pamięci przy maksymalnej mocy ani wielogodzinnej pracy.** Oba skrajne warunki były sprawdzane **oddzielnie**, aby nie kumulować ryzyka.

## Wspólne warunki bezpieczeństwa

- Fabryczny limit karty: **180,00 W** (niezmieniony).
- GPU `0000:03:00.0` (NVIDIA GB206 / RTX 5060 Ti); downstream bridge `0000:02:00.0` (Intel JHL9480 / TBGAA).
- Boot gate `ai-egpu-gen3-ha.service`: active, Result=success.
- Automatycznie skonfigurowana i potwierdzona w tym samym boocie para **Gen3 x4 + HA**: `ctl2 GPU 0x0023`, `ctl2 bridge 0x0063`. NVIDIA-SMI i sysfs: **8,0 GT/s ×4** przez cały test.
- Root, upstream switch, downstream bridge i GPU: liczniki AER 0 przed, podczas i po testach; brak NVIDIA Xid w journalu.
- Preflight: systemd/SSH/sieć aktywne, RM IDLE, scheduler 0/0, `recovery_required=false`, Ollama bez modeli, GPU bez innych procesów obliczeniowych, wolna VRAM.
- Bez instalowania pakietów: lokalne `libcudart.so.13` i `libcublas.so.13` z istniejącego katalogu Ollamy `/usr/local/lib/ollama/cuda_v13`, uruchamiane przez `ctypes`.
- Watchdog: próbki NVIDIA-SMI i AER, kontrola Gen3 ×4, logów jądra i innych procesów GPU; progi przerwania: **76°C GPU**, **181 W** raportowanej mocy; dodatkowo przerwanie przy Xid, AER, zmianie łącza, utracie telemetrii lub nieoczekiwanych procesach GPU.
- Nie modyfikowano PCIe, GRUB, sterownika, zegarów, undervoltingu, limitu mocy, konfiguracji RM ani systemd.
- Skrypt pracował w oddzielnym krótkotrwałym procesie; na końcu cudaFree, cublasDestroy i cudaDeviceReset.

## 1. Test dużej zajętości VRAM

**Wynik: `HIGH_VRAM_PASS`.**

| Parametr | Wynik |
|---|---:|
| Całkowita pamięć raportowana NVIDIA-SMI | **16 311 MiB** |
| Alokowane przez test CUDA | **14 592 MiB** (8 bloków) |
| Maksymalnie zajęta VRAM według NVIDIA-SMI | **14 730 MiB** |
| Procent VRAM zajętej łącznie | **90,31%** |
| Pozostałe wolne CUDA przy szczycie alokacji | **1 212,1 MiB** |
| Maksymalna moc | 20,14 W |
| Maksymalna temperatura | 35°C |
| Próbki telemetryczne | 19 |
| Watchdog, Xid, AER, cudaFree | **0 błędów** |

Stopnie alokacji: 2 048 → 4 096 → 8 192 → 12 288 → 14 336 → 14 592 MiB. Całość alokowanej pamięci zapisano poleceniami CUDA memset, z niezależną weryfikacją próbek danych z początku, środka i końca każdego bufora. Zostawiono rezerwę co najmniej 1 000 MiB dla sterownika i ewentualnych alokacji systemowych. Celem było przekroczenie 90% zajętości bez ryzyka OOM związanego z próbą zajęcia ostatnich bajtów VRAM.

## 2. Moc i rzeczywiste obliczenia cuBLAS

**Wynik: `NEAR_POWER_PASS`.**

| Parametr | Wynik |
|---|---:|
| Fabryczny limit mocy | **180,00 W** |
| Szczyt NVIDIA-SMI `power.draw` | **176,43 W** |
| Udział szczytu w limicie | **98,0%** |
| Maksymalna temperatura GPU | **65°C** |
| Chwilowe wykorzystanie SM/GPU | **100%** |
| Maksymalna zajętość VRAM w tym teście | 918 MiB |
| Operacje SGEMM | **24 405** |
| Łączny czas etapów obliczeniowych | **49,0 s** |
| Próbki telemetryczne | 67 |
| Watchdog, Xid, AER, cudaFree, cuBLAS | **0 błędów** |

Obliczenia to cuBLAS SGEMM mnożące macierze float32 ze sprawdzanym numerycznie wynikiem; etapy stopniowo zwiększano:

| Macierz N×N | Czas | Liczba GEMM | Szczyt mocy z monitoringu |
|---|---:|---:|---:|
| 1024×1024 | 3 s | 17 752 | 148,61 W |
| 2048×2048 | 5 s | 4 921 | 168,49 W |
| 4096×4096 | 7 s | 921 | 171,40 W |
| 6144×6144 | 12 s | 429 | 171,40 W |
| 8192×8192 | 22 s | 382 | **176,43 W** |

Szczyty pochodzą z monitoringu NVIDIA-SMI, a nie z zewnętrznego watomierza. Potwierdzają raportowaną moc GPU; nie mierzą sumarycznego poboru zasilacza, strat adaptera ani poboru całego hosta.

## 3. Niezależna kontrola końcowa

**23.10.2026 około 16:58 CEST**, po wyłączeniu testów:

- NVIDIA-SMI: **P8, 37°C, 4,42 W, 0% GPU, 2 MiB VRAM**, PCIe Gen3×4.
- `nvidia-smi --query-compute-apps`: brak procesów.
- Ollama `/api/ps`: pusta lista, model nie pozostał załadowany.
- AER: root `00:01.1`, upstream `01:00.0`, downstream `02:00.0` i GPU `03:00.0` — correctable/nonfatal/fatal **wszystkie 0**.
- Kernel journal: **brak NVIDIA Xid**, GPU-fallen-off-bus i PCIe AER errors.
- `ai-egpu-gen3-ha.service`: active, success.
- AI Gateway: `status=ok`; Resource Manager `IDLE`, `recovery_required=false`, 0 kolejkowanych/aktywnych zadań.
- `ollama`, `nvidia-persistenced`, `ai-gateway`, `ai-bridge`, `ai-platform-radio`, `comfyui`: active.
- SSH, NetworkManager, LAN, Wi-Fi i Tailscale: działają.

## Kwalifikacja

**Potwierdzono** stabilność rozruchu Gen3 ×4 + HA i działanie RTX 5060 Ti pod dwoma skrajnymi, lecz rozdzielonymi rodzajami obciążenia: >90% VRAM i 98% deklarowanego limitu mocy. W tych określonych próbach GPU nie wykazała błędów, a po zakończeniu poprawnie uwolniła zasoby.

**Nie oznacza to gwarancji wielodniowej stabilności** ani potwierdzenia pracy przy maksymalnym poborze z całego układu eGPU. Jednoczesne 90% VRAM i ~180W oraz testy engine handoff Ollama ↔ ComfyUI / Resource Manager pozostają osobnymi zadaniami, jeśli okażą się potrzebne.

## Artefakty na serwerze

Katalog: `/srv/ai-data/staging/egpu-gen3-ha-stability-20261023/`

- `result-extreme-memory.json`: dokładne pomiary VRAM, 19 próbek telemetrycznych.
- `result-extreme-power.json`: pełna sekwencja pięciu poziomów, 67 próbek telemetrycznych.
- `extreme_probe.py`: kod testu CUDA/cuBLAS i autonomicznego watchdoga.
- `REPORT_EXTREME.md`: ten raport.
- `REPORT.md`: wcześniejsza kwalifikacja krótkiego obciążenia BGE-M3.

Żadnych zmian firmware/BIOS, parametrów PCIe, GRUB, sterownika ani limitów mocy.
