# AI Platform — Cooperative RM V1, bezpieczne wznowienie (20.10.2026)

## Cel
Przywrócić codzienną pracę bazowej AI Platform przy zachowaniu jednego
Gateway / Resource Managera, bez zmian uprawnień GPU i bez stawiania
drugiego koordynatora. W tym kroku wznawiamy wyłącznie Ollama, Gateway
oraz Bridge; ComfyUI, analysis timer i preload dużego modelu pozostają
nieaktywne.

**Status: przygotowane i zweryfikowane w DEV. Produkcyjne uruchomienie
wymaga jednego wykonania przez operatora ze zwykłego terminala sudo.**

## Potwierdzone na hoście
- Headless Ubuntu `multi-user.target` bez GDM.
- SSH, Tailscale i zdalny agent działają, `harrypotter` ma linger.
- KFD/fuser nie wskazały aktywnego właściciela Radeona 890M.
- Brak `/var/lib/ai-platform-gpu/residency.blocked` i drugiego
  znacznika w profilu użytkownika.
- Produkcja nadal ma release `stage-o-28e3ea214660`.
- `ai-gateway.service` wymaga `ollama.service` przez
  systemd `Requires=`, dlatego nie można bezkarnie zatrzymywać
  Ollamy przy działającym Gateway.
- `comfyui.service` i `ollama-preload.service` są nadal
  **enabled** — przy następnym rozruchu hosta mogą wystartować
  automatycznie. Zmiana ich autostartu wymaga osobnej
  zatwierdzonej konfiguracji i testu.
- Gateway w obecnym release korzysta z istniejącego trybu
  legacy PriorityScheduler + GPUResidency. DEV N2 jest
  blokadą, nie automatycznym mechanizmem handoff.

## Dostarczone pliki
- `tools/restore_cooperative_v1.py` — zachowuje status
  BLOCKED przy każdym błędzie, blokuje równoległe wywołania,
  sprawdza symlink release, sumy SHA256 konfiguracji/źródeł,
  kluczowe urządzenia i stan usług oraz SSH/Tailscale.
  Domyślnie działa wyłącznie w trybie read-only.
- `tools/restore_cooperative_v1.baseline.json` — snapshot
  SHA256 bieżącego release, systemd i plików konfiguracji;
  nie zawiera wartości haseł ani tokenów.
- `tools/restore_cooperative_v1.sh` — jeden wrapper dla operatora.
- `tests/test_cooperative_restore.py` — CPU-only testy
  kolejności i blokad.

## Wyniki weryfikacji
- Testy obejmujące zmiany oraz RM/Gateway/N1–N5:
  **639/639 PASS**, exit 0.
  Log: `/tmp/rm-cooperative-restore-v1-regression-20261020.log`.
- Uruchomiony read-only preflight na rzeczywistym serwerze:
  `READ_ONLY_PREFLIGHT_PASS` (exit 0).
  Pozostaje `PARTIAL_OPERATOR_APPLY_REQUIRED` w zakresie
  uprzywilejowanego fuser dla procesów innych kont.
- **Nie wykonywano** operacji `--apply`, sudo/systemctl
  start/stop, obliczeń GPU, instalacji systemd ani zmian
  konfiguracji produkcyjnej.

## Akcja operatora — jeden kontrolowany start
W zwykłym terminalu konta `harrypotter`:

```bash
bash /srv/ai-data/evaluation/rm-cooperative-restore-v1-20261020/tools/restore_cooperative_v1.sh --apply
```

Skrypt ponownie sprawdza stan przed każdym uruchomieniem,
żąda sudo z aktywnego terminala i startuje wyłącznie:
`ollama.service` → `ai-gateway.service` →
`ai-bridge.service`. Odczytuje lokalne API Ollama i
`/health` Gateway. Nie uruchamia ComfyUI, preload ani timerów.
W razie błędu zachowuje raport `BLOCKED` oraz instrukcję
ręcznego rollbacku. Nie kasuje markerów ani nie resetuje GPU.

Sukces ma status `RESTORED_BASE_AI_ONLY`: to nie znaczy, że
automatyczny systemd handoff trzech silników działa produkcyjnie.
Nie uruchamiać wielokrotnie po częściowym sukcesie bez
sprawdzenia stanu i raportu.

## Integracja EXCLUSIVE — pozostały minimalny zakres
Sprawdzony pilot transient systemd 3/3 jest dowodem, że silniki
można obsługiwać kolejno. Nadal wymaga operatora i nie używa
produkcyjnego grantu N1. Dalsze prace powinny wykorzystać
istniejącą kolejkę Gateway oraz stałe profile systemd,
bez przenoszenia kodu N1 z DEV do produkcji bez testu.

Na zaufanym hoście rezygnujemy z wymuszania globalnych
uprawnień `render/video` i absolutnej izolacji. Zamiast
tego stosujemy politykę współpracy własnych silników:
jeden wykonywany GPU workload naraz, kontrolowane stop/start
i stop przy niepewnym stanie. Zwolnienie sterownika
AMDGPU/MES nadal `GPU_REUSE_SAFE=NOT_VERIFIED`;
nie wolno obiecywać gwarantowanego automatycznego handoffu.

## Granice i rollback
Gdy skrypt zgłosi BLOCKED, odczytać ścieżkę `REPORT=` i
zapis systemd, a nie usuwać zabezpieczeń. Przy częściowym
uruchomieniu operator może zatrzymać w odwrotnej kolejności
Bridge → Gateway → Ollama; nie wykonywać automatycznego
rollbacku bez sprawdzenia aktywnego żądania. Zachować SSH
i Tailscale przez całą procedurę.
