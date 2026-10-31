# P2-A3 — właściciel procesu GPU i domeny pamięci (wyłącznie DEV)

**Nie ma zgody produkcyjnej ani automatycznego przydziału GPU.** Zależność: P1 #194 → P2-A #196 → P2-A2 #197 → ten odrębny pakiet. Brak scalania.

## Fakty ustalone w audycie rzeczywistego serwera

Obecny `ResourceLeaseRegistry.snapshot()` pokazuje `job_id`, `in_use` i `external_in_use`, ale **nie** zawiera `PID`, czasu powstania procesu, tożsamości fizycznego GPU i generacji urządzenia ani niepodrabialnego powiązania procesu z identyfikatorem lease. Dlatego skojarzenie samego `job_id` z PID byłoby niebezpieczne przy restarcie, zmianie procesu lub ponownym użyciu PID. Kod P2-A3 celowo zwraca najwyżej *kandydata do dopasowania*.

Pasywny odczyt z 31.10.2026 na Minisforum (bez inferencji) wykazał jedną NVIDIA i jeden Radeon AMD; `nvidia-smi --query-compute-apps` nie zwrócił w tym momencie procesów. **Brak wpisów compute nie dowodzi, że wszystkie konteksty GPU zostały zwolnione.** Query nie obejmuje wszystkich typów procesów i aktywności.

AMD sterownik pokazuje:

- `mem_info_vram_total = 103079215104 B` (**96 GiB**);
- `mem_info_vis_vram_total = 103079215104 B` (**96 GiB**);
- `mem_info_gtt_total = 16366436352 B` (około **15,24 GiB**);
- host `MemTotal = 32732876800 B` (około **30,48 GiB**).

To osobne **liczniki i przestrzenie adresowe**, nie suma pamięci do przydziału. GTT jest aperturą/zarządzaną przestrzenią sterownika i nie oznacza dodatkowej fizycznej puli. Bez potwierdzenia konfiguracji BIOS/firmware i faktycznej alokacji host↔GPU nie mamy dowodu, jaki fragment pamięci można bezpiecznie przydzielać CPU, Radeonowi i RTX. Wstępny model P1 był deklaratywny, nie automatycznie wyprowadzony z tych danych.

## Implementacja

### 1. NVIDIA: wąski, nieautoryzujący ślad procesu

`resource_gpu_process.py` jawnie pobiera (tylko przy wywołaniu jednorazowej operacji) `nvidia-smi --query-compute-apps=gpu_uuid,pid,used_gpu_memory`. Dla dodatniego PID odczytuje ograniczony `/proc/PID/stat`, pole 22 `starttime`, aby wykrywać ponowne użycie PID. `boot_id` pochodzi z odczytu sprzętowego. Wszystkie porównania wymagają GPU UUID z wcześniej pobranej listy urządzeń.

Ograniczenia: UUID jest informacją sterownika, starttime dowodzi tożsamości *procesu*, ale ani jedno ani drugie nie jest atestacją własności lease. Dla AMD nie wdrażamy w tym etapie automatycznego, bezpiecznego przypisania procesu: `/proc/PID/fdinfo` wymaga dodatkowej weryfikacji uprawnień, kontekstów i generacji, więc oznaczamy je jako nieznane. `nvidia-smi` nie obejmuje pełnego katalogu kontekstów render/video, a 0 widocznych procesów nie jest dowodem quiescence.

### 2. Mapowanie kandydatów do lease RM

`resource_ownership.py` porównuje: NVIDIA UUID + PID + startticks + boot_id + obserwowany aktualny `job_id` z `external_in_use=True` oraz osobne deklaracje procesu z przyszłego nadzorcy. Jest to wyłącznie kandydat — nawet dokładny match ma `lease_process_attribution=unverified`, `result=UNKNOWN`, `authorizes_execution=False`. Dwie sprzeczne deklaracje są niejednoznaczne. Przesunięty boot/clock, nieświeże próbki, zmieniony GPU UUID, brak tożsamości PID, błędny lease snapshot i brak potwierdzonej własności dają brak autoryzacji.

**Nie modyfikujemy `ResourceLeaseRegistry`, jego kluczy, ACL ani zwalniania; nie dopisujemy niezweryfikowanych PID do rzeczywistych rezerwacji.** Dopiero przyszły protokół zarządzanego workera/supervisora może dostarczyć dowód procesu i zamknięcia jego GPU kontekstów, przypięty do lease i generacji RM.

### 3. Diagnostyka apertur AMD

`resource_memory_domains.py` odczytuje wyłącznie `cardN/device` dla PCI AMD i nie sumuje VRAM, visible VRAM, GTT oraz host RAM. Wynik `memory_domain_mapping=unverified` jest **stały**, niezależnie od zgodności liczników. Weryfikujemy tożsamości PCI i anomalie liczników bez twierdzenia o potwierdzonej domenie fizycznej.

### 4. Integracja tylko odczytowa

`gateway_resource_ownership_observation_enabled=False` domyślnie. Przy jawnej aktywacji w **izolowanym DEV** pole `GET /status → resource_ownership` jest obliczane z dwóch *już pobranych, niemutowalnych* próbek + istniejącego `resource_leases.snapshot()` + opcjonalnych syntetycznych deklaracji kandydata. Endpoint **nie wywołuje `nvidia-smi` ani nie skanuje `/proc`**. Zwraca jedynie agregaty, nigdy PID, UUID, boot_id, lease ID ani szczegółów wyjątków.

CLI `tools/rm_gpu_owner_observe.py` realizuje na autoryzowanym hoście **jednorazowy** odczyt i drukuje tylko zanonimizowany JSON. Nie łączy się z produkcyjnym API RM i nie może zwalniać ani rezerwować zasobów.

## Testy i warunek dalszych prac

Testy CPU/mock: parser NVIDIA, PID reuse, dwie karty, źle podany/nieaktualny PID, stale clock/boot, brak procesu (nie dowodzi bezpiecznego zwolnienia), sprzeczne deklaracje lease, odmowa automatycznego match, sanitizacja statusu, oddzielne apertury AMD i GTT, błędy sysfs, regresja niezmienności RM. GitHub CI uruchamia te testy na Pythonie 3.12 i 3.14 z Ruff/mypy.

**P2-B pozostaje zablokowany** do chwili istnienia:

1. Wiarygodnego, wersjonowanego rejestru procesów uruchomionych przez RM (boot id + PID birth ticks + lease token + worker/supervisor scope + GPU UUID + generacja).
2. Jawnego, spójnego modelu fizycznych domen pamięci UMA/CPU potwierdzonego konfiguracją firmware i sterownika; GTT nie może stać się kolejnym budżetem.
3. Zaufanego protokołu cleanupu/quiescence po anulowaniu i utracie eGPU.
4. Odbioru sprzętowego bez modyfikacji produkcji oraz osobnej zgody na P2-B.

Zielone testy P2-A3 **nie będą** oznaczać produkcyjnego GO.
