# N3 DEV — fundament odczytu evidence / identity Multi-GPU

Data: 2026-10-17. Worktree: `/srv/ai-data/evaluation/gpu-multipool-n3-verifier-dev-20261017`.
Gałąź zadania: `feature/gpu-multipool-n3-verifier-dev-20261017`; baza zadania: N2 `39bf6f0`.
Status: **NOT_VERIFIED, nieoperacyjny, bez zgody na wykonanie GPU**.

## Wykonane

Dodano wyłącznie `src/ai_bridge/gateway/accelerator_evidence.py`, testy CPU w
`tests/test_accelerator_evidence_n3.py` oraz ten raport i zapis walidacji.
Nie zmieniono N1, N2, schedulera, konfiguracji Gateway ani istniejących testów.
Nie powstał nowy serwis, scheduler, endpoint ani automatyczny skaner hosta.

- `EvidenceCollector.devices()` przyjmuje jawne mapowanie identyfikatora na ścieżki
  render node w sysfs. Normalizuje je przez strict realpath, sprawdza relację
  `renderD*/device`, strukturę PCI, subsystem PCI i zgodność linku bus/devices.
  Odczytuje vendor/device dla AMD 1002, Intel 8086 i NVIDIA 10de. Ponowny odczyt
  tożsamości i boot ID wykrywa część zmian podczas obserwacji.
- Aliasy tej samej funkcji są dozwolone wewnątrz jednej rejestracji; dwie karty
  wskazujące tę samą funkcję są odrzucane. Konserwatywnie odrzucane są również
  oddzielne rejestracje funkcji tego samego slotu PCI. Brak, niejednoznaczność,
  nieobsługiwany vendor, błędny layout i non-PCI dają `UNKNOWN`, bez mapowania
  zastępczego. Nie dodano mechanizmu zatwierdzania wyjątków non-PCI.
- Zamrożone struktury `Observation`, `PciIdentity`, `ProcessSnapshot` i
  `DeviceHandle` rozróżniają obserwację od `UNKNOWN`; brak wartości nie jest
  pustą listą właścicieli. Nie ma statusu SAFE/PASS.
- `process()` odczytuje boot ID, pole 22 `/proc/<pid>/stat` (nazwa może zawierać
  spacje, nowe linie i nawiasy), cztery UID oraz wszystkie wpisy cgroup
  z pathname. Powtarza odczyt metadanych i uchwytów; wykryta zmiana PID birth,
  UID, scope, boot, FD, zniknięcie procesu lub EPERM oznacza `UNKNOWN`.
- Dla FD używa numeru urządzenia znakowego i `/sys/dev/char`, a nie nazwy linku
  `/dev`. DRM render/primary otrzymuje tożsamość PCI, jeśli layout jest obsługiwany.
  KFD pozostaje globalnym uchwytem AMD z **UNKNOWN device identity**; nie jest
  przypisywany do jednej karty. Inne urządzenia znakowe (także proprietary NVIDIA)
  pozostają jawnie niesklasyfikowane. Błąd odczytu FD unieważnia obserwację procesu.
- `ProcessSnapshot.matches()` porównuje całą obserwację, w tym epoch, boot,
  birth_ticks, UID, cgroup i uchwyty. Epoch jest etykietą przekazaną przez wywołującego,
  nie odczytanym ani uwierzytelnionym stanem RM. Metoda nie poświadcza świeżości.
- `NonApprovingSafetyAdapter` ma sygnatury N1 `can_start()` i async `verify()`.
  **Obie metody zawsze zwracają False**, również dla CPU, pustych danych i
  poprawnych obserwacji. Nie istnieje opcja testowego sukcesu ani fabryka/config
  aktywująca adapter. Collector jest osobnym narzędziem odczytu; adapter nie
  udaje walidacji challenge ani dowodu sprzątania.
- N2 pozostaje domyślnie `legacy` lub jawnie `n2-dev-blocked`; blokada
  `NOT_VERIFIED` i brak fallback są niezmienione. N1 pozostaje początkowo BLOCKED;
  recovery z adapterem N3 nie odblokowuje urządzenia, release nie usuwa właściciela.

## Granice dowodu

BDF identyfikuje funkcję PCI w danym uruchomieniu. Boot ID zapobiega utożsamieniu
obserwacji z różnych uruchomień, ale nie zapewnia trwałej tożsamości sprzętu.
Brakuje silniejszego serial/UUID oraz zaufanej generacji hotplug/reset/rebind.
Jedna karta może mieć więcej funkcji, endpointów lub układów; wykluczenie aliasów
funkcji nie dowodzi izolacji całej fizycznej płytki. SR-IOV, vGPU, non-PCI i
nietypowe topologie wymagają oddzielnego zweryfikowanego mapowania.

Czytnik wymaga zaufanego widoku hostowych proc/sys i przestrzeni nazw. Nie
uwierzytelnia mount namespace, PID namespace, user namespace ani cgroup namespace.
Cgroup pathname nie jest niezmiennym identyfikatorem cgroup. Nie tłumaczymy go
automatycznie na pole `scope` N1; potrzebny jest zaufany binding i generacja scope.
Nie ma pidfd, atomowego snapshotu, blokady migracji ani ochrony przed ABA między
odczytami. PID reuse jest wykrywany przy różnicy starttime, nie deklarujemy
nieomylnego dowodu inkarnacji na podstawie samych ticków.

Odczyt dotyczy jawnie wskazanego procesu, nie wszystkich procesów hosta ani jego
potomków. `OBSERVED` z pustą tablicą FD nie oznacza globalnego braku właścicieli.
`OBSERVED` procesu może zawierać uchwyty z `UNKNOWN` tożsamości (np. KFD).
Nie wykrywamy pełnego drzewa submitterów, przekazanych FD, zachowanych mmap,
importowanych dma-buf, stanu kernela ani nowego submitu po odczycie. Aktywny obcy
właściciel nie daje prawa do startu/release; adapter odmawia niezależnie od danych.

## Następny konieczny dowód E_safe

Potrzebna jest zaufana atestacja sterownika/runtime, związana z całym challenge:
nonce, epoch RM, boot, generacja urządzenia, PCI/UUID, digest dziennika, grant,
generacja lease oraz pozostali właściciele. Musi dowodzić skutecznego uniemożliwienia
kolejnych submitów przez daną inkarnację i jej potomków/posiadaczy przekazanych
uchwytów, zakończenia wszystkich prac i sprzątania na właściwych silnikach,
uwzględnienia obcych klientów oraz izolacji pozostałych właścicieli. Replay,
restart, reset, timeout i niepełny widok muszą unieważniać dowód. Sam hash dziennika
nie uwierzytelnia treści ani stanu sterownika.

AMDGPU fences są synchronizacją określonych operacji, nie globalnym zakazem
nowych submitów. Dokumentacja opisuje dma_fence jako prymityw synchronizacji DMA;
AMDGPU wiąże finished fence z konkretnym jobem. Wniosek projektowy N3: nawet
zasygnalizowane znane fences nie dowodzą kompletnego pokrycia HIP/KFD, innych
procesów i przyszłej pracy. Nie sprawdzaliśmy tego na GPU ani nie czytaliśmy
root-only debugfs. Źródła: [dma-buf / dma_fence](https://docs.kernel.org/driver-api/dma-buf.html),
[AMDGPU job](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/amdgpu_job.c).
Puste kolejki, wolny VRAM, job terminal, zniknięcie PID i odczyty `/proc` również
nie zastępują atestacji. Dopiero oddzielny etap z egzekwowaniem izolacji i
zweryfikowanym kontraktem runtime/sterownika może rozważać aktywne admission.

## Walidacja

Wszystkie nowe testy używają wstrzykniętego `FakeReader`, bez realnego `/proc`,
`/sys`, GPU ani ioctl. Przypadki obejmują dwie karty, aliasy DRM, trzech vendorów,
błędne linki PCI, funkcje siostrzane, zmianę sysfs, malformed stat/UID/cgroup,
EPERM cross-UID, globalny KFD, PID reuse, boot mismatch, stale epoch, migrację
scope, exit/FD race, obcego właściciela i odmowy przy współbieżnym release/recovery.
Test release używa syntetycznego adaptera wyłącznie w pliku testowym do zasiania
wcześniejszego grantu, następnie zastępuje go N3. Nie jest to produkcyjna ścieżka.

Komenda zakończonej serii (istniejący venv, bez instalacji zależności):

```bash
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest \
  tests/test_accelerator_evidence_n3.py tests/test_accelerator_admission_n1.py \
  tests/test_gateway_api.py tests/test_gateway_jobs.py \
  tests/test_gateway_n2_integration.py tests/test_gateway_priority_classes.py \
  tests/test_gateway_resource_leases.py tests/test_gateway_scheduler.py \
  tests/test_gateway_unified_admission.py tests/test_wvc_domain.py \
  tests/test_stage_n0_accelerators.py tests/test_resource_evidence_b_dev.py \
  tests/test_media_admission.py
```

Wynik: **411 PASS** (w tym 41 nowych N3, 58 N1, 53 N2 i 9 WVC), exit 0.
Pozostałe testy tej serii obejmują Gateway API/jobs/priority/scheduler/admission,
leasing, N0, evidence B oraz media. Jeden istniejący StarletteDeprecationWarning.
Zapis: `docs/reports/GPU_MULTI_POOL_STAGE_N3_VALIDATION_2026-10-17.log`.

Dwa testy `tests/test_gateway_resource_api.py` wymagają osobnej walidacji:
bezpośredni test `socketpair.send` w sandbox zwrócił EPERM, a seria zatrzymała się
na Resource API. Osobny runner z limitem 45 s używa wyłącznie zakończenia własnego
procesu (`os._exit`); nie zmienia selectorów, socketów, testów ani aplikacji i nie
wysyła sygnałów. Ta sesja nie ma uprawnień wykonania poza sandboxem (approval=never).
Nie deklarujemy, że te dwa testy przeszły w sandboxie. Pierwsza szeroka próba
bez limitu zatrzymała się w tym miejscu; nie wysyłano do niej sygnału kończącego.

Wczesny pomocniczy runner WVC nie miał guard `__main__` i wywołał błąd spawn.
To błąd harness, nie aplikacji; bezpośrednia komenda `python -m pytest` powyżej
potwierdziła wszystkie 9 WVC PASS bez zmian istniejących testów. Poprawiono też
guard pomocniczego runnera, bez obchodzenia ograniczeń sandboxa.

W czasie pracy pojawił się dodatkowy, zewnętrznie utworzony plik
`N3_VALIDATION_OUTSIDE_CODEX_SANDBOX.log` z zakończonym zielonym przebiegiem.
Sam plik nie zawiera komendy, kodu wyjścia ani listy testów; jego pochodzenie i
zakres wymagają potwierdzenia przed uznaniem za pełny dowód walidacji poza sandboxem.
Nie zmieniano tego pliku.

Nie uruchomiono realnego czytnika hosta, nie otwierano GPU, nie wykonywano stress,
resetów, sygnałów do procesów, eviction ani zmian OS/sterownika/systemd.
Nie modyfikowano `/opt/ai-platform`, innych worktree ani metadanych git.
Brak commit/push. `N3_CODEX_TASK.md` istniał przed zmianami i pozostał nietknięty.


## Kontrola niezależna na hoście i końcowa walidacja

- Na żywym serwerze wykonano WYŁĄCZNIE odczyt informacji sysfs/proc, bez GPU submit/driver ioctl: AMD Radeon 890M, PCI BDF 0000:c6:00.0, vendor 0x1002, device 0x150e i bieżące boot ID zostały sklasyfikowane jako OBSERVED.
- Proces ComfyUI PID 7934: metadane /proc OBSERVED; uchwyt renderD128 mapuje się na PCI Radeona; /dev/kfd (511:0) na tym jądrze jest w /sys/devices/virtual/kfd/kfd i po poprawce został oznaczony jako KFD ze stanem device identity UNKNOWN, ponieważ KFD jest współdzielony. Inne nieprzypisane urządzenie /dev/accel/accel0 ma status OTHER/UNKNOWN, a nie osobna automatycznie aktywowana karta.
- Testy syntetyczne dodane dla dwóch wariantów ścieżki KFD: /sys/devices/virtual/misc/kfd oraz /sys/devices/virtual/kfd/kfd.
- Ostateczna niezależna regresja w normalnym środowisku hosta (po poprawce KFD), 19 wybranych plików testowych, **508/508 PASS**, exit 0; wynik: N3_VALIDATION_OUTSIDE_CODEX_SANDBOX.log w katalogu worktree (log nie jest wymaganym artefaktem Gita). Bez użycia GPU w testach.
- Codex sandbox zablokował socketpair.send/multiprocessing w części testów Gateway; brak możliwości wykonania tych testów w tym sandboxie nie jest dowodem awarii aplikacji. Te testy zostały wykonane z powodzeniem poza sandboxem, bez modyfikacji asercji.
- Produkcja, sterownik, usługi, kernel i dotychczasowy scheduler: BEZ ZMIAN. Adapter pozostaje NON_APPROVING, nie ma drogi autoryzującej SAFE.
