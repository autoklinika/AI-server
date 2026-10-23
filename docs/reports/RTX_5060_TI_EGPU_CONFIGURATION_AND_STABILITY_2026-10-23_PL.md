# RTX 5060 Ti / TBGAA — konfiguracja produkcyjna i odbiór (23.10.2026)

**Werdykt: PASS — automatyczny boot PCIe Gen3 x4 + HA i 120 minut ciągłego obciążenia CUDA/cuBLAS.**

Przedmiot: rzeczywisty serwer AI Platform, harrypotter-AI-Series.
To jest zapis stanu po próbie, bez jakiejkolwiek zmiany konfiguracji sprzętu czy usług.
Nie oznacza certyfikacji 24/7, hotplug, uśpienia ani separacji wielu fizycznych GPU.

## 1. Potwierdzona konfiguracja

| Składnik | Stan |
|---|---|
| Host | Minisforum, Ubuntu 26.04.1 LTS, kernel 7.0.0-39-generic |
| RTX | ASUS GeForce RTX 5060 Ti 16 GB, NVIDIA GB206, 10de:2d04, subsystem 1043:8a11 |
| eGPU adapter | TBGAA, USB4, Intel JHL9480 bridge 8086:5786 |
| BDF GPU i downstream bridge | 0000:03:00.0 i 0000:02:00.0 (adresy zależne od topologii) |
| Root / upstream | 0000:00:01.1 / 0000:01:00.0 |
| Połączenie USB4 | TBGAA, 20 Gb/s × 2 linie RX oraz TX, authorized=1 |
| PCIe | 8 GT/s, Gen3 x4, oba końce połączenia |
| Rejestry Link Control 2 | GPU 0x0023; bridge 0x0063 |
| Tryb Gen3/HA | Hardware Autonomous Speed Disable, boot-gate PASS |
| Sterownik | NVIDIA Open 615.71.09, CUDA 13, cuBLAS 13 |
| Ollama | 0.40.7, dostępny CUDA13 oraz Vulkan |
| VRAM | 16 311 MiB raportowane przez NVIDIA-SMI |
| Limit fabryczny | 180 W, niezmieniony |
| Wbudowane GPU | AMD Radeon 890M / Strix, osobne od RTX |
| Dysk | /srv/ai-data, NVMe |

Przed załadowaniem sterownika uruchamiana jest jednostka ai-egpu-gen3-ha.service.
Sprawdza tożsamość GPU, audio, mostka i autoryzowanego routera USB4,
brak Xid/AER, boot-ID oraz odpowiednie rejestry.
Wykonuje kontrolowane zamaskowane zapisy PCIe Gen3 i HA oraz jeden retrain
przed załadowaniem NVIDIA. Bez automatycznych retry po niepowodzeniu.
Wszystkie usługi zależne od GPU mają Requires/After dla boot gate.

Parametry startowe blacklist obejmują nvidia, nvidia_uvm, nvidia_modeset,
nvidia_drm i snd_hda_intel. Ostatni wpis blokuje również inne audio systemowe.
Zewnętrzny module_guard weryfikuje znacznik gotowości zanim dopuści
modprobe NVIDIA. Jest to konfiguracja **specyficzna dla tego hosta**.

Wcześniej historyczne PCIe Device Status miało na RTX bity CED i URD
(0x0009), nieobecne w licznikach AER. Implementacja dopuszcza wyłącznie
dokładnie znany wariant 0x0009 albo 0x0000. Nie czyści RW1C, więc
powtórzenia identycznych bitów nie można w ten sposób rozróżnić.
Błąd w trakcie rozruchu wymaga ręcznej diagnostyki, a nie samoczynnego restartu.

Kopie aktualnie działających plików znajdują się w katalogu
[installed](rtx5060ti-egpu-20261023/installed/).
Odczytowy [snapshot JSON](rtx5060ti-egpu-20261023/installed/effective-hardware-and-runtime-snapshot.json)
zawiera rzeczywistą topologię, statusy usług, flagi boot i RM.

## 2. Badania i pełne wyniki

| Test | Wynik |
|---|---:|
| Normalny start Gen3 + HA / sterownik NVIDIA | PASS |
| Inferencja Ollama i 60 s embeddingów BGE-M3 | PASS |
| Wysoka VRAM, w odrębnej próbie | 14 730 / 16 311 MiB = 90,31%, PASS |
| Krótka próba mocy, w odrębnej próbie | 176,43 W, 65°C, PASS |
| Rozgrzewka 2048×2048 | 300,001 s, PASS |
| Zwiększanie obciążenia 4096×4096 | 120,004 s, PASS |
| Główny test SGEMM 8192×8192 | **7200,001 s, PASS** |
| SGEMM łącznie (3 fazy) | **432 577 operacji** |
| SGEMM w 2-godzinnej fazie | 124 339 operacji |
| Zebrane próbki telemetryczne ~1 Hz | 7621 (główna faza: 7200) |
| Średnia / maks. moc, faza główna | **177,38 W / 178,92 W** |
| Średnia / maks. temperatura, faza główna | **65,76°C / 66°C** |
| Maksymalna temperatura całej próby | 67°C |
| Średnie wykorzystanie GPU, faza główna | 99,6% |
| Średnie taktowanie SM, faza główna | 2759,86 MHz |
| VRAM, maksimum fazy głównej | 918 MiB |
| Throttling termiczny | 0 |
| NVIDIA Xid | 0 |
| PCIe AER (GPU, downstream, upstream, root) | 0 |
| Połączenie PCIe | Gen3 x4 przez cały okres |
| Po zakończeniu | P8, 2 MiB VRAM, brak aktywnych procesów CUDA |
| RM po zakończeniu | IDLE, recovery_required=false, brak zadań |
| Werdykt | **PASS** |

Test zakończony 23.10.2026 o 19:24:06 CEST.
Moc jest wartością raportowaną przez NVIDIA-SMI, a nie pomiarem
zewnętrznego watomierza. Nie łączono 90% VRAM z obciążeniem maksymalnej mocy.
Nie zmieniano BIOS, firmware, GRUB, sterownika, zegarów ani fabrycznego
limitu mocy podczas testów.

Zapis pełnej telemetrii, dokładnych zdarzeń, wyników i źródeł:
[archiwum testowe](rtx5060ti-egpu-20261023/README.md).
Dokładne trzy raporty:
[krótki](rtx5060ti-egpu-20261023/reports/REPORT.md),
[VRAM i moc](rtx5060ti-egpu-20261023/reports/REPORT_EXTREME.md),
[długotrwały](rtx5060ti-egpu-20261023/reports/REPORT_LONG_SOAK.md).

## 3. Resource Manager, Hermes i podział dwóch GPU

Główny test 2h uruchomiono **bezpośrednio przez CUDA/cuBLAS, bez lease RM**.
Nadzorca pilnował IDLE, braku jobów i recovery_required=false, a także
nowych procesów GPU. Nie testowano fizycznego przypinania modeli do GPU.

Aktualny RM zawiera logiczny akcelerator local-primary opisany jako
integrated, lecz backend unknown **nie gwarantuje wyboru Radeona**.
Hermes/Telegram jest kierowany przez Gateway
127.0.0.1:11435/clients/hermes/v1, a Gateway przekazuje do Ollamy.
Ollama wybierała wcześniej CUDA0 = RTX 5060 Ti. Brak więc jeszcze
gwarancji, że zapytanie Telegram ominie RTX.

Ollama ma obecnie OLLAMA_MAX_LOADED_MODELS=1, a Gateway ma
max_concurrency=1. Równoległe małe modele na RTX oraz poprawny routing
na AMD 890M to osobny etap, wymagający kontrolowanego wdrożenia i odbioru.

## 4. Decyzja

**Zaakceptowano 2h PASS.** Nie wydłużamy testu do 4h jako warunku
przejścia dalej. Konfiguracja Gen3 + HA pozostaje bez zmian.
Następny etap: przypinanie fizycznych GPU przez istniejący RM,
bez dodawania nowego koordynatora, z możliwością rollbacku.

Raport jest historycznym snapshotem konfiguracji i dowodów,
**nie pakietem do wdrażania bez autoryzacji**. Wcześniejsze raporty
ze statusem NOT_DEPLOYED pozostają prawdziwe dla ich etapów.
