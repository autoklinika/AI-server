# RM Cooperative V1 — odbiór autostartu i ComfyUI, 2026-10-20

## Wynik
**AUTOSTART_DISABLED_COMFY_READY — PASS, operator 08:07 CEST.**
Potwierdzone niezależnie w systemd, lokalnym API oraz KFD/fuser po
operatorowym uruchomieniu `rm_cooperative_autostart_v1.py --apply`.

- `ollama.service`, `ai-gateway.service`, `ai-bridge.service`,
  `ai-vision-gpu-observer.service`: active.
- `comfyui.service`: active, PID 267058, port 127.0.0.1:8188.
- `comfyui.service`, `ollama-preload.service`,
  `ai-bridge-analysis.timer`: disabled (bez autostartu po reboot).
- `ollama-preload.service` i timer analizy: inactive.
- ComfyUI `/system_stats`: `cuda:0 AMD Radeon 890M Graphics : native`;
  `/ai-platform/residency`: schema 1, loaded_models 0,
  queue_running 0, queue_pending 0, cleanup_pending false.
- Gateway `/health`: status ok, Ollama ok; `/status`:
  state llm, recovery_required false, admission_blocked false,
  max_concurrency 1, active/queued 0, lease_count 0.
- Ollama `/api/ps`: brak załadowanych modeli.
- Brak nowych rozpoznanych reset/timeout/fault AMDGPU/MES w
  sprawdzonym oknie dziennika.
- Produkcyjny release nadal `stage-o-28e3ea214660`.

## Istotna obserwacja techniczna
Mimo pustej kolejki i wyładowanych modeli ComfyUI ma aktywny
**kontekst KFD/DRM PID 267058**. To nie jest rozpoznana awaria:
proces ROCm ma prawo utrzymywać kontekst podczas bezczynności.
Nie należy interpretować `loaded_models=0` albo `queue=0`
jako `GPU_REUSE_SAFE` ani końca procesu GPU. Jeżeli przyszłe
przełączanie wymaga pełnego zwolnienia, trzeba zatrzymać nadzorowaną
jednostkę systemd i potwierdzić zakończenie jej procesów.
Nie wykonano tego teraz, bo ComfyUI ma pozostać aktywne.

## Zakres akceptacji
Sukces obejmuje kontrolowany start, stan usług, politykę autostartu,
gotowość ComfyUI i spójność raportu RM. **Nie testowano**
generowania obrazów ani automatycznego przełączania silników
w trakcie obciążenia. Automatyczny fizyczny grant N1 nadal
`NOT_ADMITTED`, driver `GPU_REUSE_SAFE=NOT_VERIFIED`.

Brak zmian produkcyjnego kodu, wersji release, grup, udev czy
sterownika. Stan po operatorowej akcji odpowiada planowi
Cooperative RM V1. Nie wymaga kolejnego restartu.
