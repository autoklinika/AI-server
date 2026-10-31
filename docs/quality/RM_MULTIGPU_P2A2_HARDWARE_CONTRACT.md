# P2-A2 — read-only Linux hardware observation (DEV)

**Status:** osobny, zależny pakiet GitHub, bez aktywacji na produkcji. **NO-GO do alokacji GPU.**

## Cel i rzeczywisty zakres

P2-A2 dodaje jawnie uruchamianą, wyłącznie odczytową obserwację:

- NVIDIA: `/usr/bin/nvidia-smi` (stałe argumenty `--query-gpu=index,uuid,pci.bus_id,memory.total,memory.used`, format CSV; liczniki w MiB). Timeout 3 s, bez shell, bez zmian sterownika.
- AMD: `/sys/class/drm/cardN/device/vendor`, `mem_info_vram_total`, `mem_info_vram_used`; rozpoznajemy wyłącznie wpisy `cardN`, a nie złącza monitora `card0-DP-1`.
- Host RAM: `/proc/meminfo` (`MemTotal` i `MemAvailable` w KiB).
- Boot epoch: `/proc/sys/kernel/random/boot_id`.

Pomiary są zachowywane osobno z informacją o źródle i tożsamości (UUID zgłaszane przez sterownik NVIDIA, PCI BDF dla AMD). Identyfikacja AMD na podstawie PCI jest ważna w kontekście określonego uruchomienia systemu, ale nie jest kryptograficzną atestacją ani nie ustanawia generacji urządzenia.

Nie ma uruchamiania modeli, alokacji, odblokowywania/kwarantanny RM, zmian systemd, nowych schedulerów, demonów czy procesów działających w tle. `nvidia-smi` jest uruchamiany **wyłącznie podczas jawnej próby**. Import modułu i zwykły `GET /status` nie skanują GPU.

## Ustalenie z fizycznego odczytu sprzętu (31.10.2026)

Na stanowisku podczas jednorazowego odczytu otrzymaliśmy:

- NVIDIA: jedna karta, około 16 GiB dedykowanej VRAM (sterownik pokazuje 16311 MiB).
- AMD DRM: `mem_info_vram_total=103079215104` B, czyli **96 GiB**.
- Linux: `MemTotal=32732876800` B, czyli około **30,5 GiB** RAM widoczne CPU.

**Wartości AMD DRM i host RAM nie mogą być bez dowodu sumowane, utożsamiane ani traktowane jako automatycznie współdzielony budżet.** Możliwe są carve-out BIOS/firmware, osobne apertury lub inne ograniczenia. Poprzedni matematyczny model P1 opisuje zadeklarowaną domenę host RAM/UMA, ale nie stanowi poprawnego automatycznego odwzorowania tych konkretnych pomiarów sprzętowych.

Dopóki nie zweryfikujemy mapowania, observer zachowuje oddzielne pola `amd_driver_reported_unclassified` i `host_ram`, a `memory_domain_mapping=unverified`.

## Protokół i odporność

Parser NVIDIA odrzuca N/A, błędne jednostki/liczniki, duplikaty UUID/PCI/indeksu, niekompletne i nadmiernie długie odpowiedzi. Numer logiczny CUDA jest tylko zmiennym aliasem. Wartości pamięci są konwertowane MiB → bajty, a nie przyjmowane jako budżet RM.

Parser AMD odczytuje wyłącznie skończone pliki sysfs o maksymalnym, ograniczonym rozmiarze. Niepoprawne lub nieobecne liczniki dają `None`, nigdy 0 wolnej pamięci. Wiele wpisów DRM o tym samym PCI BDF oznacza błąd. Pojedynczy problem AMD nie powinien przekreślać poprawnej obserwacji NVIDIA, i odwrotnie. Brak całego źródła nie jest interpretowany jako brak karty.

Opcjonalne oczekiwania operatora: `expected_nvidia`, `expected_amd`, a w interfejsie programowym również `expected_nvidia_uuids`. Dzięki temu możemy wykryć utratę eGPU lub zamianę karty nawet przy niezmiennej liczbie urządzeń. Bez oczekiwań nie wolno deklarować kompletnego inwentarza.

## Diagnostyka w RM

Nowa flaga `gateway_resource_hardware_observation_enabled=False` jest domyślnie wyłączona. Gdy włączona **tylko w izolowanym DEV**, dodatkowe pole `GET /status` nazywa się `resource_hardware`. Źródło dostarczamy przez `create_gateway_app(..., resource_hardware_source=...)`.

**Dostawca musi zwracać wcześniej pobrany snapshot** i być szybki/niedziałający na GPU. Endpoint nigdy sam nie wywołuje `nvidia-smi` ani sysfs. Przy błędzie dostawcy pokazuje ogólną diagnostykę `UNKNOWN`, bez ujawnienia wyjątków. Odczyt poprzedzający odpowiedź statusu jest porównywany z monotonicznym zegarem procesu: próbka starsza niż **5 sekund** otrzymuje `hardware_sample_stale`, a próbka z przyszłości/po niezgodnym restarcie `hardware_sample_clock_mismatch`. Nie jest to potwierdzenie identyfikacji generacji GPU ani proof of quiescence.

Wyświetlane są liczby urządzeń, oddzielne liczniki pamięci NVIDIA, AMD DRM i hosta oraz liczba aktualnych globalnych lease RM. W diagnostyce publicznej przepuszczane są wyłącznie stałe kody błędów; nieznany tekst od dostawcy zamieniany jest na `unclassified_hardware_issue`, bez ujawnienia jego treści. Brak per-GPU powiązania każdej rezerwacji z procesem/pamięcią; `allocation_attribution=unverified` nawet jeśli `rm_lease_count=0`. Podsumowanie nie wyświetla UUID, PCI BDF ani boot_id. `authorizes_execution=False` zawsze.

Nie wolno zamieniać tej obserwacji na `ShadowInputs` P1 bez niezależnie zweryfikowanej tożsamości, generacji, kompletności rezerwacji, atrybucji i mapowania pamięci. `OBSERVED` oznacza tylko sukces odczytu, nie wolną pamięć ani gotowość GPU.

## Uruchomienie ręcznego odczytu (tylko autoryzowany Linux)

Po instalacji kodu w izolowanym DEV — nie na produkcji:

```bash
python tools/rm_hardware_observe.py --expected-nvidia 1 --expected-amd 1
```

Polecenie drukuje jedynie zanonimizowaną diagnostykę JSON. Bez sekretów, hostname, adresów IP, UUID ani PCI BDF. Jeśli GPU nie jest dostępne, brak źródła jest zachowany jako `UNKNOWN/PARTIAL`, nie symulowany stan wolny. Po dołączeniu drugiej RTX zmienimy oczekiwaną liczbę na 2, a w integracji będziemy porównywać również deklarowane UUID.

## Odbiór i dalsze etapy

CI: Python 3.12/3.14, testy CPU/mock (parsery, zniknięcie/zamiana GPU, niepełna telemetria, niezależność kart, niespójna pamięć), Ruff, mypy oraz regresje RM P1/P2-A.

Rzeczywisty test odczytowy powinien zostać wykonany w osobnym środowisku DEV na Minisforum — **bez** zmiany aktywnego RM/sterowników. Jego wynik jest diagnostyką sprzętu, nie produkcyjnym GO.

Dalszy pakiet, osobny PR: spójne mapowanie `GPU UUID ↔ proces ↔ lease RM ↔ pamięć` oraz domeny pamięci/carve-out AMD. Dopiero po tym P2-B atomowe rezerwacje w istniejącym RM i P2-C cleanup/recovery. Brak merge do `main` bez odrębnego polecenia użytkownika.
