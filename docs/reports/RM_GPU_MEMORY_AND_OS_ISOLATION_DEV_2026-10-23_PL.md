# AI Platform — dwie fizyczne karty GPU, bezpieczeństwo pamięci i OS (DEV)

Data: 23.10.2026, host harrypotter-AI-Series.

**Werdykt: DEV ROUTING PASS + MEMORY ADMISSION PASS; OS GPU ISOLATION = NOT VERIFIED / BLOCKED.**
**PRODUCTION_UNCHANGED=YES; N1_GPU_GRANTS=NOT_ADMITTED; GPU_REUSE_SAFE=NOT_VERIFIED.**

## Architektura — bez drugiego RM

Zachowano istniejący, sprawdzony PriorityScheduler, globalną kolejkę
priorytetów, rezerwacje, obsługę stanów silnika i fail-closed. Dodatkowa
warstwa RM mapuje model na fizyczny akcelerator i sprawdza pamięć po
przydzieleniu dotychczasowego slotu kolejki. Nadal obowiązuje
max_concurrency=1: wiele modeli na RTX może pozostawać w VRAM, lecz
nie ma zatwierdzonego równoległego grantu RM dla dwóch GPU ani SHARED.

## Wprowadzone dodatkowe zabezpieczenia DEV

- physical_gpu_budget.py: wymagana jawna wycena RAM/VRAM każdego modelu,
  porównanie z rzeczywistym /proc/meminfo oraz nvidia-smi, kontrola PCI
  identyfikatorów Radeona 890M i RTX 5060 Ti. Ignoruje pozorną pamięć
  ~111 GiB raportowaną przez Vulkan na hoście z ~30 GiB fizycznej RAM.
- GET /api/ps sprawdza dotychczas załadowane modele w docelowej Ollamie;
  nieznany model rezydentny lub brak telemetrii => odmowa 503.
- Modele z ponadlimitowym num_ctx, num_predict, max_tokens, keep_alive,
  albo żądaniem wymuszającym num_gpu / main_gpu => odmowa.
- Testowy tryb routing jest dostępny tylko z jawną flagą
  gateway_physical_gpu_dev_mode=True oraz lokalnym Gateway 127.0.0.1.
  Domyślnie wyłączony; wymagany jest pełny JSON budżetów.
- Przy odmowie bez uruchomienia modelu RM zwalnia ten sam ticket,
  a stara produkcja pozostaje na dotychczasowej ścieżce.
- Warstwa raportuje jawnie, że cgroup CPU RAM nie jest twardym limitem
  VRAM NVIDIA, i że systemowe profile OS nie są jeszcze aktywne.

## Realne testy (bez zmian produkcji)

| Próba | Wynik |
|---|---|
| Fizyczne przypinanie Qwen3 0.6B do Radeon 890M Vulkan | PASS |
| Fizyczne przypinanie BGE-M3 do RTX CUDA | PASS |
| Dwa różne rezydentne modele RTX, łącznie 1441 MiB VRAM | PASS |
| Dwa zadania przez jeden DEV Gateway/RM z pamięciowymi budżetami | PASS |
| AMD 4+6=10, RTX embedding 1024, brak innego GPU | PASS |
| Wstrzyknięty model wymagający 24 GiB AMD przy fizycznym RAM 31 216 MiB | DENIED |
| Fizyczne dane MemAvailable ~26 503 MiB i RTX 16 311 MiB | PASS |
| cgroup użytkownika, MemoryMax=48M, alokacja 96M | oom-kill, PASS |
| systemd użytkownika DevicePolicy=closed, próba otwarcia AMD renderD128 | OPEN_SUCCEEDED — brak izolacji |
| Read-only audyt znanej granicy hosta | BLOCKED, UNVERIFIED_OPEN_BYPASS |
| systemd-analyze verify obu projektów jednostek systemowych | PASS |
| system-manager DevicePolicy pozytywny/negatywny test otwarcia GPU | NOT RUN — wymaga sudo |
| Globalny OS GPU exclusivity i driver E_safe | NOT VERIFIED |

Wszystkie realne dowody i logi zachowano lokalnie na NVMe:
 /srv/ai-data/staging/gpu-dual-route-20261023/
W szczególności dev-routing-budget-accepted-e2e/result.json,
rm-routing-bounded-full-dev.log, os_gpu_boundary_readonly.json,
host_gpu_audit_readonly.json i źródłowe logi obu Ollam.
Po testach produkcyjny RM IDLE, recovery_required=false, RTX P8, 2 MiB,
Gen3 x4, brak błędów NVIDIA Xid i PCIe AER w sprawdzonym oknie.

## Systemd — gotowe projekty, lecz nie zainstalowane

Dwie jednostki DEV w deploy/physical-ollama-routing-dev/systemd:
- AMD: DevicePolicy=closed, jedynie /dev/dri/renderD128,
  MemoryMax=6G, jeden mały model.
- RTX: DevicePolicy=closed, jedynie /dev/nvidia0, nvidiactl, uvm;
  MemoryMax=4G host RAM (nie VRAM), dwa małe modele;
  zależność od zweryfikowanego ai-egpu-gen3-ha.service.

Oba profile mają Restart=no, RuntimeMaxSec=360, KillMode=control-group,
NoNewPrivileges i nie mają sekcji Install; nie mogą się uruchomić
automatycznie bez dalszych działań. Nie instalowano żadnej jednostki.

Osobny skrypt operatorski run_system_scope_gpu_negative_dev.sh uruchamia
tylko krótkotrwałe usługi system-manager (nie user-manager), sprawdza
wybór własnego / odmowę obcego urządzenia i zapisuje wyniki.
**Nie uruchomiono go** — wymaga osobnej operacji sudo.

## Co jeszcze blokuje produkcję

1. System-manager transient GPU DevicePolicy, test rzeczywistych DENIED
   i ALLOWED, plus brak omijania ograniczeń przez inne UID/grupy/kontenery.
2. Zaufane uruchomienie obu runtime przez root-owned profile/cgroup,
   tożsamość procesu (PID/birth/boot/InvocationID), backend i fizyczne PCI.
3. Odbiór cgroup MemoryMax na obu systemowych profilach i rezerwy RAM
   przy docelowym Qwen3.8 27B; nie ufać pozornym 111 GiB Vulkan.
4. Błędy/timeout/kill, odzyskiwanie i rollback, kompatybilność Hermes,
   WVC, ComfyUI oraz Vision.
5. Dopiero po oddzielnym akceptacyjnym protokole i świadomej decyzji:
   ewentualne wdrożenie produkcyjne. Nie scalać DEV na podstawie samego CI.

Nie zmieniano GRUB, BIOS, firmware, sterownika, parametrów PCIe Gen3+HA,
mocy RTX ani usług produkcyjnych Gateway/Ollama.
