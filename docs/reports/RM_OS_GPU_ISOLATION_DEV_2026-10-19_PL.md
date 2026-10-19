# RM — izolacja dostępu do GPU: audit DEV, 2026-10-19

## Decyzja
**Przygotowanie DEV: PASS. Izolacja produkcyjna hosta: BLOCKED / NOT_APPLIED.**
To nie jest autoryzacja prawdziwego grantu N1 ani GPU_REUSE_SAFE.
Nie tworzono drugiego schedulera, nowej usługi root ani nowego koordynatora.

## Stan sprawdzony na AI Platform
- Ubuntu 26.04 w trybie `multi-user.target`, GDM nieaktywny;
  usługi Gateway/Bridge/Ollama/ComfyUI zatrzymane podczas utrzymania;
  GPU Observer aktywny.
- GPU AMD Radeon 890M, PCI 0000:c6:00.0.
- Węzły: `/dev/kfd`, `/dev/dri/renderD128` mają `0660 root:render`,
  a `/dev/dri/card0` ma `0660 root:video`. Aktualnie bez ACL
  nadających prawa użytkownikowi gdm-greeter.
- NSS: `harrypotter`, `ollama`, `ai-vision` należą do obu grup
  `render` i `video`. Podczas odczytu audytu wykryto 34 aktywne
  procesy z odziedziczoną jedną z tych grup (wynik chwilowy).
- `ollama.service`, `comfyui.service`, `ai-gateway.service`,
  `ai-bridge.service` i `ai-bridge-analysis.timer` nadal mają
  włączony autostart; pierwsze dwie usługi mają `Restart=always`.
- W próbie transient systemd EXCLUSIVE 3/3 realne silniki przeszły
  test z `DevicePolicy=closed` i dokładnym `DeviceAllow`. Nie
  udowadnia to odmowy wobec zwykłych procesów poza RM.

## Co dostarczono
1. `src/ai_bridge/gateway/host_gpu_audit.py` — metadane tylko do
   odczytu: DAC, ACL, urządzenia KFD/DRM/card0, NSS i odziedziczone
   grupy procesów, jednostki systemd oraz ich stan autostartu.
   Urządzeń nie otwiera, nic nie zapisuje w systemie i nigdy nie
   przyznaje dostępu. Raport JSON zawsze zakończony `BLOCKED`
   i `GPU_REUSE_SAFE=NOT_VERIFIED`; exit 2.
2. `tests/test_host_gpu_audit.py` — testy fail-closed, nieznanych
   danych, parsowania niepełnych pól systemd, braku otwierania GPU,
   procesów ze starymi uprawnieniami i alternatywnego węzła `card0`.
3. `deploy/rm-host-gpu-isolation-dev/README.md` — jedna konkretna
   instrukcja operatora: backup, kontrola SSH/Tailscale/Remote Desktop,
   migracja kont i grup, zamknięcie autostartu i bypassów,
   odświeżenie starych sesji, pozytywne i negatywne testy rzeczywistych
   usług systemowych, bezpieczny rollback. Materiał jest tylko
   do przeglądu, nie instaluje stałych jednostek.

## Walidacja
`PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest -q`
z 24 wybranymi modułami testowymi RM/OS/Gateway:
**634/634 PASS, exit 0**.
Log na serwerze: `/tmp/rm-host-isolation-regression-20261019.log`.
Odrębny rzeczywisty audyt:
`/tmp/rm-host-gpu-audit-actual-20261019.json`,
exit 2 (`BLOCKED`, oczekiwany). Bieżący stan procesów
nie jest trwałą właściwością systemu.

## Co nadal blokuje egzekwowalną izolację
- Cgroup `DevicePolicy` ogranicza tylko procesy w danej jednostce;
  zwykłe procesy z grupą `render` mogą omijać RM.
- `SupplementaryGroups=render` **dodaje**, nie usuwa,
  grup istniejących w NSS; zmiana NSS nie unieważnia uprawnień
  już uruchomionych sesji ani otwartych deskryptorów.
- Samo ograniczenie DAC nie eliminuje możliwości obejścia przez
  administratora/root, kontenery uprzywilejowane, inne device nodes.
  Root/sudo pozostają zaufane i muszą być jawnie poza modelem zagrożeń.
- Nie ma zaufanego pozytywnego dowodu zakończenia całej pracy
  AMDGPU/KFD/MES; `NonApprovingSafetyAdapter` pozostaje False.
  Automatyczny grant i hot handoff N1: **NO-GO**.

## Odbiór przed zmianą produkcji
Operator musi najpierw potwierdzić odrębną sesję SSH/Tailscale,
backupu grup i jednostek oraz bezpieczną procedurę odświeżenia sesji.
Dopiero potem można wdrażać zatwierdzone root-owned profile GPU
i migrację NSS, wykonać negatywne próby otwarcia wszystkich znanych
urządzeń GPU spoza RM oraz pozytywne próby w zarządzanych jednostkach.
Jeżeli wynik jest niepełny: utrzymać BLOCKED, przywrócić baseline,
bez wznowienia GPU na podstawie pustego KFD.

**Nie zmieniano produkcji, ACL, udev, grup, usług, GDM, SSH/Tailscale,
GPU ani sterownika.**
