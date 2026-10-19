# AI Platform — N1/N5 dwufazowy admission, Stage NEXT DEV
Data: 2026-10-19; host: harrypotter-AI-Series; gałąź: feature/rocm-managed-worker-adapter-dev-20261017.

## Decyzja i zakres
Zachowano N1–N5. Brak nowych daemonów/schedulerów, brak zmian w produkcji
`/opt/ai-platform`, systemd, kernelu oraz sterowniku AMDGPU.
Testujemy wiązanie rzeczywistego PID/boot/birth przed admission, następnie
otwarcie bramki wykonania dopiero po grancie. Osobne ścieżki:
- DEV CPU: N1 z `cpu` + syntetyczny SafetyAdapter -> rzeczywisty proces CPU N5
  uruchamiany dwufazowo (PARKED -> grant -> GO -> wait -> release).
- DEV ROCm: N1 z `rocm`, właściwym providerem `vision-rocm-dev` i
  `NonApprovingSafetyAdapter`. Prawdziwy proces ROCm N5 jest PARKED; N1
  odmawia recovery i grantu. Bez wysyłania GO, importu torch ani GPU kernel.
  Ten wariant NIE przyznaje fałszywego prawa do karty.

## Zmiany
- `src/ai_bridge/gateway/n1_n5_cpu_bridge.py`: jednolita sekwencja PID
  before grant dla stałego programu CPU. Wymusza `backend=cpu`,
  `kind=virtual` i EXCLUSIVE. Każdy wyjątek pozostawia marker i anuluje
  żądanie; grant po awarii jest przypięty przez N1.
- `src/ai_bridge/gateway/rocm_parked_worker.py`: proces wstrzymany
  przed importem torch, oczekujący na pojedynczy prywatny sygnał GO.
- `src/ai_bridge/gateway/n1_n5_rocm_probe.py`: rzeczywisty test bramki N1
  na Radeonie 890M, oddzielny provider DEV, rocm backend,
  read-only obserwacje diagnostyczne systemu i N3 always-deny.
  `ParkedROCmRuntime.activate()` jawnie odrzuca uruchomienie bez E_safe.
- `tests/test_n1_n5_cpu_bridge.py`, `tests/test_n1_n5_rocm_probe.py`:
  grant/deny/cancel/release/marker oraz nierozruch GPU w zablokowanym N1.

## Wykonane testy — zakresy nie mogą być mylone
- Scenariusze N1 -> N5 na realnym **CPU**: 3/3 PASS; czwarty test w tym module weryfikuje odmowę konfiguracji fizycznego GPU.
- N1 ROCm policy on host z realną identyfikacją PCI 0000:c6:00.0:
  PARKED_BEFORE_GPU, DENIED_BY_N3, grant DENIED, N1 BLOCKED_EXPECTED,
  zero nowych obliczeń GPU, brak widocznych KFD/fuser owners po próbie.
  Dowód: `/srv/ai-data/evaluation/rm-rocm-hardware-pilot/n1-n5-gate-*/gate-result.json`.
- Regresja rozszerzona N1–N5, Gateway, leasing, ROCm: **536/536 PASS**,
  exit 0, `/tmp/rm-n1-n5-stage-next-regression-20261019.log`.
- Poprzedni niezależny test **N5** na prawdziwym Radeon 890M:
  4/4 single-worker ROCm matrix 64x64 PASS po poprawce PCI bus 198.
  To NIE był N1 grant ani automatyczny handoff.

## Aktualny rzeczywisty status N1
`N1_N5_CPU_INTEGRATION=PASS`
`N1_GPU_PROVIDER_BINDING_DEV=PASS`
`N1_GPU_RECOVERY=DENIED_BY_POLICY`
`N1_GPU_GRANT=NOT_ADMITTED`
`N5_ROCM_HARDWARE_SINGLE_JOB=PASS` (poprzedni etap)
`N1_GPU_LIVE_HANDOFF=NOT_RUN`
`GPU_REUSE_SAFE=NOT_VERIFIED`
`PRODUCTION_UNCHANGED=YES`

## Dlaczego N1 GPU jest nadal zatrzymany
N3 ma intencjonalny, niemodyfikowalny `NonApprovingSafetyAdapter`.
Brak niezależnej zaufanej weryfikacji uniemożliwienia nowych submitów,
zamknięcia kontekstu KFD/MES i cleanup właściciela sprzętu. `fuser`,
KFD snapshot, lokalne HIP sync, ukończenie N5 nie stanowią takiego dowodu.
Nie używamy syntetycznego SafetyAdapter do realnego GPU.

## Minimalny kolejny warunek
Dostarczyć osobny, pozytywnie zweryfikowany, device- oraz
process-incarnation-bound adapter bezpieczeństwa dla rzeczywistego
EXCLUSIVE start/release na 890M, uwzględniający izolację wszystkich
lokalnych submitterów, uniemożliwienie GPU opens poza RM, brak
orphan FD/descendants, rozstrzygnięcie worker teardown i stan sterownika.
Dopiero potem wolno włączyć N1 GPU recovery i sprzętowy handoff.
SHARED nadal domyślnie wyłączony. Bez zmian produkcyjnych do osobnej decyzji.

## Stan usług po pracy
`ai-bridge-analysis.timer`, `ai-bridge`, `ai-gateway`, `ollama`,
`comfyui` pozostawiono zatrzymane zgodnie z wcześniejszym
oknem serwisowym. `ai-vision-gpu-observer` aktywny. Backup/DR nie był dotykany.
