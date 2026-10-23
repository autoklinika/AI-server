# AI Platform / Hermes — ComfyUI na żądanie w Resource Managerze (DEV)

Data: 23.10.2026, host harrypotter-AI-Series.
**DEV CPU/ASGI PASS. LIVE GPU ON-DEMAND NOT_RUN. PRODUCTION UNCHANGED.**

## Dlaczego ComfyUI dotąd stale działało

Rzeczywisty audyt wykazał:
- Produkcyjne comfyui.service posiada WantedBy=multi-user.target i Restart=always.
- Gateway ma drop-in 98-comfyui-ready.conf z Requires=comfyui.service oraz
  After=comfyui.service. Sam start Gateway powoduje wymaganie ComfyUI.
- Od 16:02 CEST żywy ComfyUI PID 4937 utrzymuje pliki /dev/kfd i
  /dev/dri/renderD128 w procesie ROCm.
- GET /queue i /ai-platform/residency: zero zadań, modeli i cleanup_pending.
  RM jednocześnie pokazuje IDLE. To różne stany; IDLE kolejki nie oznacza
  fizycznego zwolnienia GPU.
- Hermes /foto już przechodzi przez istniejący Resource Manager: pobiera
  lease i przed generowaniem używa /resource/leases/{id}/uses z providerem
  comfyui-local i capability image-generation / image-edit.
  Nie potrzeba nowego koordynatora ani zmian algorytmu kolejki Hermesa.

## Przygotowana implementacja DEV

W istniejącym Gateway / RM:
- Opcjonalna flaga gateway_comfy_ondemand_dev_mode=False domyślnie.
- Tryb może być uruchomiony wyłącznie z osobnym, **zaufanym**
  kontrolerem procesu i izolowanym portem ComfyUI 127.0.0.1 (nie 8188);
  jeden PriorityScheduler / max_concurrency=1 i bez równoległego RADIO.
- ResourceLeaseRegistry zachowuje zewnętrzny ticket od Hermes /foto
  przez pełny lifecycle. Nie zmieniono dotychczasowych priorytetów.
- Na wejściu /uses: trwały marker blokady/recovery -> start kontrolera ->
  token tożsamości procesu (boot, incarnation, PID, birth, cgroup) ->
  przejście legacy GPUResidency do media.
- Na wyjściu /uses: ComfyUI /free, potwierdzenie zerowych modeli,
  kolejek i rezerwacji pamięci -> stan freeing_comfy, z markerem nadal
  obecnym i tokenem lease w RM -> kontroler kończy i potwierdza
  zatrzymanie własnego procesu/cgroup -> dopiero wtedy marker
  zostaje usunięty, a RM pozwala zwolnić ticket.
- Każdy start, unload, stop, crash, zmiana tokenu albo timeout bez
  potwierdzenia oznacza BLOCKED, zachowanie lease i recovery marker
  także przy zwolnieniu klienta. Nie ma automatycznego wyczyszczenia
  markera, retry, przeładowania NVIDIA czy rebootu.
- Bez jawnej konfiguracji i kontrolera wszystkie ścieżki produkcyjne
  zachowują oryginalne, dotychczasowe zachowanie.

## Testy DEV i granice wyniku

- 20/20 testów dedykowanych (15 przepływów CPU/ASGI i 5 kontroli
  niezainstalowanego profilu systemd) PASS.
- Testy obejmują: lease Hermes image-generation, niezależne zadanie
  oczekujące w tej samej priorytetowej kolejce, poprawny start/use/free/
  stop, trzymanie markera aż do potwierdzenia stop, odmowę startu bez
  zaufanego kontrolera, nieudany start, /free, stop, utratę procesu,
  zmianę inkarnacji, marker po restarcie, odrzucanie portu produkcyjnego,
  pracy poza localhost, RADIO i max_concurrency>1.
- Pełne regresje Gateway / RM / leases / lifecycle / GPU budget pozostają
  do potwierdzenia na końcu tego etapu; surowe logi lokalne.
- Przygotowano draft system-manager jednostki
  deploy/comfy-ondemand-dev/ai-rm-comfy-ondemand-dev.service.
  Restart=no, RuntimeMaxSec=300, KillMode=control-group, DevicePolicy=closed,
  AMD /dev/kfd + renderD128, MemoryMax=12G. Brak sekcji Install.
  Jednostka **nie została zainstalowana ani uruchomiona**.
- NIE wykonano start-stop rzeczywistego ComfyUI pod nowym kontrolerem
  i nie sprawdzono realnej generacji na nim. Kontroler root-owned,
  autoryzujący konkretne start/stop z weryfikacją PID/InvocationID i
  cgroup, nadal wymaga niezależnego przygotowania/odbioru.
- GPU_REUSE_SAFE nadal NOT_VERIFIED. Sam process-exit nie dowodzi
  wszystkich warunków driver E_safe AMDGPU/KFD/MES.

## Odbiór konieczny przed produkcją

1. Rozwiązać rzeczywistą zależność boot Gateway Requires=comfyui.service.
   Nie wolno obecnie zatrzymać ComfyUI tylko dlatego, że RM IDLE;
   obecny systemd może wpłynąć na Gateway.
2. W odrębnym, zatwierdzonym oknie serwisowym z kopią jednostek oraz
   rollbackiem: wyłączyć dawny autostart i stale aktywną usługę,
   zachowując Gateway/Hermes, a następnie uruchomić krótkie prawdziwe
   zadanie GPU pod odpowiednio chronionym systemowym systemd.
3. Dowieść negatywnego dostępu procesów obcych, poprawnej tożsamości
   boot/PID/birth/cgroup/InvocationID, weryfikacji zatrzymania i
   awaryjnego fail-closed; testy pamięci i kontekstu ROCm.
4. Zachować zgodność endpointów /foto i ComfyUI (aktualnie 8188).
   Port DEV jest odrębny tylko na czas pilotu. W przyszłym prod trzeba
   utrzymać 8188 po bezpiecznej zamianie jednostki albo jawnie
   przeprowadzić migrowanie dispatcherów.
5. Sprawdzić WVC, Hermes Telegram, Vision, ComfyUI, aktualne priorytety
   oraz oba GPU, potem odbiór i osobna zgoda na produkcyjny cutover.

**NO PROD CUTOVER.** Nie zmieniano systemd, GRUB, sterownika,
PCIe Gen3+HA, GPU power, Gateway, Ollama, ComfyUI ani Hermesa w produkcji.

## Additional real CPU systemd lifecycle proof

A deliberately GPU-free fake ComfyUI HTTP endpoint ran in a bounded
temporary **user** systemd unit (not production, not the trusted system
manager) with MemoryMax=96M, Restart=no and a 45s maximum duration.
The probe verified real PID/cgroup/InvocationID, handled dummy /queue,
CPU-only /prompt and /free, then stopped the precise transient unit.
After stop, MainPID=0, service inactive, PID absent and the port closed:
**USER_SYSTEMD_CPU_ONLY_START_PROMPT_FREE_STOP_PASS**.

Machine evidence: RM_COMFY_CPU_SYSTEMD_LIFECYCLE_2026-10-23.json.
This probe does NOT use RM as its process controller, does NOT use
CUDA/ROCm, and does NOT prove GPU DevicePolicy isolation. Together
with 434/434 focused Gateway/RM/GPU regression tests this validates
implementation groundwork only, not real ComfyUI on-demand production.

## Uwaga po próbie rzeczywistego ComfyUI (23.10.2026)

Rzeczywiste ComfyUI z istniejącego venv ROCm nie przeszło startu w odizolowanym
środowisku DEV. Opcja --cpu nie zapobiega inicjalizacji komponentów HIP.
ROCm nie akceptował ROCR_VISIBLE_DEVICES=-1 ani CUDA_VISIBLE_DEVICES=-1:
proces zakończył się ABRT bez generowania obrazu. Testowy RM pozostał
fail-closed, a system produkcyjny nietknięty. Ten wynik **blokuje**
zatwierdzenie GPU on-demand i nie unieważnia jedynie testów logicznych RM.

Szczegółowy raport: RM_COMFY_REAL_STARTUP_DEV_BLOCKER_2026-10-23_PL.md.
Dowody: RM_COMFY_REAL_START_DEV_BLOCKED_2026-10-23.json.
