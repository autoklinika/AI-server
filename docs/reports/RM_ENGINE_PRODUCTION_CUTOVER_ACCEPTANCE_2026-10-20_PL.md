# AI Platform — RM V1: produkcyjny odbiór po cutover
Data: 2026-10-20, 09:24–09:25 CEST

## WYNIK: GATEWAY_CUTOVER_PASS
Operator uruchomił skrypt `deploy_rm_gateway_backport_v1.py --apply`.
Wynik z serwera potwierdzono niezależnie przez systemd, pliki, proces
Gateway, HTTP API i GPU. Nie wykonywano rollbacku.

- `ai-gateway.service`: ACTIVE, MainPID 282426, start 09:24:06,
  Result=success; proces rzeczywiście używa
  `PYTHONPATH=/opt/ai-platform/gateway-overlays/rm-engine-adapters-v1-0016bbe-hwpass/src`.
- Drop-in `99-rm-engine-adapters-v1.conf` obecny, zawartość dokładnie
  zgodna z manifestem procedury. Wdrożony overlay sprawdzono z
  `SOURCE_SHA256.json`: **OVERLAY_CHECKSUMS=PASS**.
- `/opt/ai-platform/current` nadal wskazuje na
  `/opt/ai-platform/releases/stage-o-28e3ea214660`.
  Pierwotne źródło `app.py` ma niezmienione SHA256
  `4501a344e0769337e8d14f57457c83fe840cd837e989197ab415861a371d4214`.
- `/health` i `/status`: RM `schema_version=1`,
  `state=IDLE`, `reason=no_active_ticket`, brak bieżącego właściciela
  i celu przełączenia, aktywne zadania=0, kolejka=0, lease_count=0,
  admission_blocked=false, Ollama=ok.
- W nowym rejestrze są `ollama` i `comfyui` configured, zaś
  `vision` not_installed/execution_available=false.
- Legacy `gpu_residency=llm`, `recovery_required=false`.
  `GPU_REUSE_SAFE=NOT_VERIFIED`, N1 real grant nieudzielony.
- API `/control/`, `/api/v1/benchmarks`, `/api/tags`: **200**.
- Ollama, AI Bridge, ComfyUI, GPU observer, SSH i Tailscale: active.
  Timer analizy i preload: inactive/disabled; ComfyUI active/disabled.
  Ollama `/api/ps` puste; ComfyUI `/ai-platform/residency`:
  zero modeli i zadań, cleanup_pending=false.
- ComfyUI PID 267058 pozostaje właścicielem kontekstu KFD/DRM podczas
  bezczynności; to nie jest dowód absolutnie pustego GPU.
- Brak wykrytych nowych AMDGPU/MES faults w obserwowanym przedziale
  i brak produkcyjnych markerów DIRTY.
- Istniejąca procedura rollback jest dostępna i jej warunki sprawdzono
  odczytowo: **OVERLAY_CHECKSUMS=PASS, DROPIN_EXACT=PASS**.
  Rollback nie był potrzebny i nie został uruchomiony.

## Granica odbioru
Przed cutover: hardware acceptance na realnej Ollamie i ComfyUI
(`REAL_HARDWARE_ACCEPT_PASS`), oraz 261/261 regresji kandydata,
4/4 testów skryptu wdrożeniowego.

Po cutover: PASS dla systemd, nowego kodu Gateway, istniejącego API,
optymalnej współpracy bezczynnych silników, zachowania stanu zasobu.
Nie wykonywano dodatkowych GPU inferencji po cutover; potwierdzone
testy sprzętowe były przed wdrożeniem. Vision nadal wymaga osobnej
integracji. Brak globalnej gwarancji E_safe.

## Sterowanie operacyjne
Jeżeli będzie konieczny rollback, tylko w spokojnym oknie bez zadań:
```bash
sudo python3 /srv/ai-data/evaluation/rm-engine-hardware-accept-20261020/tools/deploy_rm_gateway_backport_v1.py --rollback
```
Nie usuwać markerów DIRTY, nie restartować sterownika, nie
nadpisywać release Stage O. Przy aktualnym stanie rollback
**nie jest zalecany**.
