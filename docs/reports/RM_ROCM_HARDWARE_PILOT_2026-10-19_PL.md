# RM N1–N5: sprzętowy pilot ROCm — 19.10.2026

## Cel i ograniczenia
N1–N5 zostaje. Dodano w DEV pojedynczy kontrolowany test rzeczywistego GPU przez istniejący `WorkerObserver` N5. Nie zmieniono produkcji ani nie włączono automatycznych grantów N1. `GPU_REUSE_SAFE` pozostaje zawsze `NOT_VERIFIED`.

## Nowy kod
- `src/ai_bridge/gateway/rocm_maintenance_pilot.py` — wykonawca offline, wyłącznie stałe `rocm-matmul-64-v1`; nie ma endpointu HTTP ani dowolnych komend.
- `tools/run_rm_rocm_maintenance_pilot.sh` — procedura lokalnego operatora: zatrzymuje timer i usługi AI po autoryzacji, sprawdza stan i uruchamia pojedynczy pilot.
- `tests/test_rocm_maintenance_pilot.py` — pozytywne i negatywne przypadki preflight, ponownego użycia, timeoutów i raportowania.
- Małe rozszerzenie `WorkerObserver`: jawny marker `HARDWARE-PILOT`, domyślny `SIMULATION` bez zmian.

## Kontrola ryzyka
Preflight przed i bezpośrednio przed uruchomieniem: timer analizy, AI Gateway, AI Bridge, ComfyUI i Ollama muszą być `inactive`; identyfikacja PCI 0000:c6:00.0 (1002:150e); brak widocznych kontekstów KFD i użytkowników `/dev/kfd` oraz `renderD128`. Postflight ponownie sprawdza te warunki. Próba ma lock, niepowtarzalną ścieżkę, trwały marker i raport.
Nie wymusza resetu AMDGPU ani nie zwalnia N1; po timeout możliwy jest jedynie SIGTERM do własnego dziecka. Błąd zachowuje status DIRTY. Pomiary punktowe `fuser`/KFD nie stanowią globalnego dowodu bezpiecznego reuse.

## Status
ROCm w `/opt/comfyui/venv/bin/python`: PyTorch 2.13.0+rocm10, HIP 7.15, wykryta jedna karta Radeon 890M. Uruchomienie modułu i zestawu testowego na CPU/mock: PASS. Wstępny host preflight: BLOCKED, ponieważ usługi wciąż działają. Zdalny Desktop Commander nie może zatrzymać systemd bez lokalnego uwierzytelnienia administratora; nie obchodzono zabezpieczeń.
**Rzeczywisty test ROCm: NOT_RUN. Produkcja bez zmian.**

## Lokalna komenda operatora
```bash
bash /srv/ai-data/evaluation/rocm-managed-worker-adapter-dev-20261017/tools/run_rm_rocm_maintenance_pilot.sh
```
Skrypt poprosi o hasło administratora, następnie wykona pilot tylko przy pomyślnym preflight. Backup Stage K i zdalny agent pozostają aktywne. Po wykonaniu usługi AI pozostają zatrzymane do przeglądu wyniku; dzienniki próby trafią do `/srv/ai-data/evaluation/rm-rocm-hardware-pilot/<attempt>/`.

## Dalej
Po pojedynczym realnym PASS osobno zweryfikować poprawne zamykanie kontekstu GPU, następnie podłączyć zaufany SafetyAdapter do N1 i przeprowadzić kontrolowany handoff. Nie deklarować SHARED/EXCLUSIVE na rzeczywistym GPU na podstawie samego pilota.
