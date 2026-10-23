# AI Platform / Hermes — ComfyUI na żądanie, realny test GPU DEV (23.10.2026)

**Werdykt: REAL_COMFY_GPU_DEV_ONDEMAND_AND_PRODUCTION_ROLLBACK_PASS.**
**PRODUCTION_CUTOVER=NOT_DEPLOYED; GPU_REUSE_SAFE/E_safe=NOT_VERIFIED; GLOBAL_GPU_EXCLUSIVITY=NOT_VERIFIED; N1_SHARED_GRANTS=NOT_ADMITTED.**

## Realny test — zakres i przebieg

23 października 2026 r. około 23:53 CEST operator uruchomił zatwierdzoną,
jednorazową procedurę serwisową w DEV.

- Preflight: RM IDLE, 0/0 aktywnych/oczekujących, 0 rezydentnych
  modeli ComfyUI/Ollama, prawidłowa topologia obu GPU: PASS.
- Przed zatrzymaniem produkcji uzbrojono niezależny watchdog rollback.
- Oryginalny Gateway i ComfyUI wstrzymano, brak obcych właścicieli AMD
  KFD/renderD128 zweryfikowano w oknie próby.
- Uruchomiono ComfyUI we własnym krótkim system-manager cgroup z
  DevicePolicy=closed, dopuszczonym KFD/renderD128, MemoryMax=9G,
  Restart=no, RuntimeMaxSec=240s; bez instalacji usługi ani boot zmian.
- Testowy Gateway używał jednej, dotychczasowej kolejki PriorityScheduler
  i zewnętrznego lease RM do uruchomienia fazy media.
- Workflow: EmptyFlux2LatentImage 64x64 -> VAELoader flux2-vae.safetensors
  -> VAEDecode na AMD Radeon 890M -> SaveImage.
- Po zadaniu kontrolowano /free, załadowane modele, kolejkę, wykonanie
  i zakończenie procesu/cgroup, dopiero potem zwolnienie lease RM.
- Produkcyjny comfyui.service i ai-gateway.service przywrócono
  automatycznie. Watchdog zebrany; marker DEV nie pozostał.

Operator stdout: REAL_GPU_DEV_PASS_PENDING_PRODUCTION_RESTORE,
PRODUCTION_RESTORE_PASS oraz MAINTENANCE_EXIT_CODE=0.

## Niezależna kontrola realnych dowodów

| Sprawdzenie | Wynik |
|---|---|
| GPU w logu ComfyUI | cuda:0 AMD Radeon 890M Graphics : native (PyTorch ROCm) |
| Dekodowanie VAE | VAE load device: cuda:0, offload device: cpu, torch.bfloat16 |
| Czas pracy VAE | 0,86 s |
| Plik wyjściowy w NVMe | rm-comfy-dev-flux2-vae_00001_.png |
| Zweryfikowany PNG | 64x64, 7922 bajty |
| SHA256 PNG | 16e0117ddd83e8d051956f3e70cfccf1e9ac81e091f19527383b13fe0d44f205 |
| Tymczasowy systemd | uruchomiony 23:53:06, wyłączony 23:53:11, exit SUCCESS |
| Pamięć peak cgroup | 1.4G host RAM, NIE pomiar GPU VRAM |
| DEV port i jednostka | 11657 zamknięty; jednostka inactive/not-found, MainPID 0 |
| Watchdog rollback | inactive/not-found |
| DEV recovery marker | brak |
| Produkcyjny ComfyUI | COMFYUI_READY=PASS, kolejka=0, modele=0, cleanup_pending=false |
| Produkcyjny Gateway | HTTP ok, RM IDLE, 0 zadań, recovery_required=false |
| Inne usługi | Ollama, ai-bridge, eGPU boot gate aktywne |
| RTX 5060 Ti | P8, VRAM 2 MiB, PCIe Gen3 x4 |
| Błędy NVIDIA Xid i PCIe AER | 0 / 0, w badanym oknie jądra brak nowych błędów GPU |

Dane JSON, generowane z niezależnego odczytu journald, sysfs i HTTP:
[RM_COMFY_GPU_REAL_DEV_PASS_2026-10-23.json](RM_COMFY_GPU_REAL_DEV_PASS_2026-10-23.json)

Oryginalny plik PNG i root-owned surowe logi pozostają na NVMe w:
 /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/

Do publicznego GitHub nie kopiowano logów systemowych ani oryginalnego
root-owned raportu testu.

## Co zostało udowodnione

1. Prawdziwy ComfyUI rozpoznaje AMD 890M i wykonuje dekodowanie VAE
   w odizolowanej, tymczasowej jednostce systemd.
2. Istniejący RM utrzymuje pojedynczy slot/lease w czasie pracy
   ComfyUI; oczekujące zadanie nie omija kolejki.
3. Model release, proces stop i finalizacja pierwotnej rezerwacji RM
   przeszły jeden pełny, rzeczywisty cykl.
4. Rollback przywrócił produkcyjne ComfyUI i Gateway, bez zmiany
   systemd na stałe.

## Ograniczenia i bramki dalszego odbioru

- To test realnego VAE na obrazie 64x64, a NIE pełny text-to-image
  modelem Flux2 Klein, WAN ani LTX.
- Wynik stop/cgroup nie dowodzi GPU_REUSE_SAFE ani kompletnej bariery
  sterownika AMDGPU/KFD/MES. E_safe nadal NOT_VERIFIED.
- Hostowe bypassy do GPU, Ollamy/ComfyUI i uprawnienia grup render/video
  nie zostały trwale ograniczone.
- Nie wykonano jeszcze rzeczywistych prób kill/timeout/cgroup OOM
  podczas obliczeń GPU ani ponownego przydziału GPU po awarii.
- Nie testowano jeszcze pełnego Hermes Telegram /foto, Vision,
  WVC i równoległych fizycznych grantów AMD/NVIDIA.
- Gateway w produkcji nadal wymaga comfyui.service; ten ma autostart
  i Restart=always. Żadnego produkcyjnego on-demand NIE włączano.

Następne kroki DEV: odseparowane testy awarii i restartu GPU runtime,
weryfikacja bezpieczeństwa driver E_safe i host-wide access, następnie
pełny Hermes /foto i obraz modelu produkcyjnego w kontrolowanym oknie.
Dopiero po pełnym odbiorze i osobnej zgodzie — produkcyjny cutover
ze sprawdzonym rollbackiem.

**ONE-SHOT GPU DEV PASS, PRODUCTION NO-GO.**
