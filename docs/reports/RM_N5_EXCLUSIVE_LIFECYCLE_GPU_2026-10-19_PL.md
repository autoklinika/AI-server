# RM N1–N5 — EXCLUSIVE worker lifecycle evidence (DEV)
**Data:** 2026-10-19 | **GPU:** Radeon 890M, PCI 0000:c6:00.0, gfx1150

## Cel
Nie przebudowywać N1–N5. Uzupełnić pomiar życia pojedynczego, wyłącznego
workera: sprawdzić tożsamość PID/birth/boot przed uruchomieniem GPU,
potwierdzić kontekst KFD/DRM **podczas** wykonania i ponownie sprawdzić
stan hosta **po** naturalnym zakończeniu procesu. Brak zgody na N1 grant
lub bezpieczny handoff bez osobnej weryfikacji.

## Implementacja
- `rocm_lifecycle_worker.py`: stały, dwuetapowy worker; najpierw `READY`
  (bez importu torch), dopiero sygnał `G` uruchamia test 64×64 ROCm;
  po synchronizacji worker pozostaje aktywny do prywatnego sygnału `X`.
  Nie akceptuje dodatkowych argumentów ani komend dowolnego użytkownika.
- `rocm_lifecycle_pilot.py`: wymaga zatrzymania timer/AI Gateway/AI Bridge,
  Ollama i ComfyUI; identyfikuje GPU PCI; sprawdza brak widocznych właścicieli.
  Używa istniejącego N5 `WorkerObserver`, markera fsync i blokady flock.
  W trakcie aktywnego procesu sprawdza KFD + fuser, dopuszczając wyłącznie
  oryginalny PID. Następnie zapisuje potwierdzony status N5
  `PROCESS_CLOSED` i końcowy snapshot właścicieli.
  Błąd, timeout lub obcy właściciel zatrzymuje próbę i utrzymuje DIRTY.
  Brak resetu sterownika, sygnałów do innych procesów, automatycznego
  uruchomienia usług i odblokowania GPU.
- `tests/test_rocm_lifecycle_pilot.py`: 8 CPU/mock negatywnych i pozytywnych
  testów właściciela, obcego PID, braku snapshotu, awarii i blokady restartu.

## Dowód na rzeczywistym GPU
Cztery niezależne próby na GPU:
1. `lifecycle-20261019-1941-01`, PID 205531 — PASS.
2. `lifecycle-repeat-20261019-1`, PID 205696 — PASS.
3. `lifecycle-repeat-20261019-2`, PID 205771 — PASS.
4. `lifecycle-repeat-20261019-3`, PID 205848 — PASS.

W każdej: preflight KFD/fuser puste, worker faktycznie wykonywał
`rocm-matmul-64-v1` na PCI 0000:c6:00.0,
`WORKER_LOCAL_SYNC`, aktywny kontekst KFD i otwarte GPU FD wyłącznie
przez jego PID, `PROCESS_CLOSED`, postflight KFD/fuser puste.
`worker.stderr` brak błędów w pierwszej próbie; w replikach raporty PASS.
W sprawdzonym `journalctl -k` od 19:20 bez wpisów dopasowanych do
AMDGPU/MES reset/fault/timeout.
Evidence:
`/srv/ai-data/evaluation/rm-rocm-hardware-pilot/lifecycle-*/result.json`.

## Ograniczenia
`WORKER_LOCAL_SYNC_AND_CLOSED` NIE jest `GPU_REUSE_SAFE`.
Odczyty `fuser` i `/sys/class/kfd/kfd/proc` są punktowe i
nie stanowią atomowego, niezależnego poświadczenia zamknięcia wszystkich
kolejek, odroczonego driver cleanup ani uniemożliwienia nowych submitów.
Root observer nadal jest read-only, dostępny wyłącznie dla dopuszczonych UID.
AMDGPU `enforce_isolation` istnieje, ale odczyt wynosi `0`; nie zmieniano
ustawienia ani nie wykonywano `run_cleaner_shader`.
Sterownik ma osobny mechanizm serializacji grafiki i czyszczenia LDS/GPR,
nie zastępujący bezpośrednio zaufanego certyfikatu KFD/MES teardown.

## Status
`N5_SINGLE_WORKER_LIFECYCLE_HARDWARE=PASS_4_OF_4`.
`N1_GPU_GRANT=NOT_ADMITTED`.
`N1_GPU_LIVE_HANDOFF=NOT_RUN`.
`GPU_REUSE_SAFE=NOT_VERIFIED`.
`PRODUCTION_CHANGED=NO`.
Usługi AI utrzymane inactive zgodnie z oknem serwisowym.
Dalszy krok: autorytatywny mechanizm izolacji nowych GPU submitterów
oraz weryfikacja cleanup dla wszystkich właścicieli przed N1.release.
Bez takiego mechanizmu nie aktywować automatycznego handoff.
