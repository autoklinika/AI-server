# RM N1–N5 — realny pilot ROCm, wynik 19.10.2026

## Wynik
**REAL_ROCM_SINGLE_WORKER=PASS (4/4 prób po poprawce).**
**N1_REAL_GRANT=NOT_VERIFIED; GPU_REUSE_SAFE=NOT_VERIFIED.**
Produkcja nie została zmieniona ani przełączona na N1/N2.

Zamknięte próby: `pilot-pci-fixed-20261019-04`,
`pilot-repeat-20261019-1`, `pilot-repeat-20261019-2`, `pilot-repeat-20261019-3`.
Każda: exit 0, `WORKER_LOCAL_SYNC`, `PROCESS_CLOSED`, poprawna
matmul 64×64, PCI `0000:c6:00.0`, brak widocznych KFD/DRM owners przed
i po próbie, procesy pozostałych usług AI zatrzymane.
Dziennik kernela w sprawdzonym oknie nie wykazuje resetu/fault/timeout AMDGPU/MES.
Ścieżka dowodów: `/srv/ai-data/evaluation/rm-rocm-hardware-pilot/`.
`ownership.dirty` nie jest automatycznie usuwany, a wynik workera nie
zatwierdza ponownego przydziału GPU przez N1.

## Przyczyna pierwszych niepowodzeń
Pierwsza próba `pilot-20261019-165639-201193` zwróciła `WORKER_FAILED`,
a druga `pilot-diagnostic-20261019-02` ujawniła wyjątek
`runtime PCI binding unavailable`.
Trzecia diagnostyczna `pilot-pci-diagnostic-20261019-03` ujawniła
wartość `torch.cuda.get_device_properties(0).pci_bus_id = 198`:
PyTorch ROCm zwraca **liczbę magistrali**, nie pełne BDF.
Poprzedni kod oczekiwał wyłącznie `0000:c6:00.0`, dlatego blokował pracę
**przed** uruchomieniem obliczenia.
Poprawka: przy numerycznym `pci_bus_id` pobierz pełne BDF przez
udokumentowaną funkcję HIP `hipDeviceGetPCIBusId`, porównaj numer
magistrali PyTorch do HIP, sprawdź pełny BDF i PCI vendor/device w sysfs.
Nie poluzowano tożsamości ani zakazu wykonania na niewłaściwej karcie.
Worker zapisuje teraz typ błędu i krótki komunikat na STDERR, bez
zmiany fail-closed statusu `WORKER_FAILED`.
Testy jednostkowe obejmują wartość 198, zły numer, bool i błędny string.

## Architektura i granice bezpieczeństwa
N1–N5 nie zostało skasowane. Pilot jest kontrolowanym N5 one-shot
w oknie serwisowym, NIE produkcyjnym grantem N1.
Używa `WorkerObserver` (PID, birth, boot, sesja), trwałego markera i
locka. Preflight przed startem, ponowny preflight i postflight wymagają
zatrzymania timer/AI Gateway/AI Bridge/Ollama/ComfyUI, stałego PCI
1002:150e i braku widocznych KFD/FUSER owners.
Powtórzone próby nie są hot handoff pomiędzy żywymi silnikami;
oddzielna analiza driver/runtime E_safe pozostaje konieczna.

## Zmiany i walidacja
- `src/ai_bridge/gateway/rocm_test_worker.py`: naprawa numerycznego bus ID;
  szczegółowe, lokalne błędy workera na STDERR.
- `tests/test_rocm_managed_adapter.py`: regresja wartości bus ID 198,
  rozbieżności PyTorch/HIP i niewłaściwych typów.
- Wcześniejszy `rocm_maintenance_pilot.py`, `tools/run_rm_rocm_maintenance_pilot.sh`
  i testy DEV zachowane.
- Testy focused po poprawce: PASS. Regresja wybranych 15 pakietów N1–N5,
  Gateway, leasing, Stage O: **529/529 PASS po poprawce PCI**, exit 0;
  `/tmp/rm-rocm-pci-fix-full-regression-20261019.log`.

## Stan usług
Po testach timer analizy, AI Gateway, AI Bridge, ComfyUI i Ollama pozostają
`inactive` — zgodnie z procedurą bezpieczeństwa.
Obserwator GPU i narzędzia zdalne nie były zatrzymywane.
Do powrotu produkcji operator powinien osobno autoryzować start systemd.

## Co dalej
1. Zatwierdzić granicę zaufanego adaptera N1 i rozliczania kontekstu;
   obecny N3 `NonApprovingSafetyAdapter` nie może być obchodzony.
2. Sprawdzić GPU release/ponowny start jednego właściciela oraz
   sekwencję Ollama–ComfyUI–Ollama w oddzielnym teście z kompletną
   kontrolą procesów.
3. SHARED/EXCLUSIVE na prawdziwym GPU dopiero po powyższej weryfikacji.
