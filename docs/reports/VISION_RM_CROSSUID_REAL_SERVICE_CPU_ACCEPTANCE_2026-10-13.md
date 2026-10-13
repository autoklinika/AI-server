# Vision RM — test akceptacyjny oddzielnych kont i brokera CPU-only

Data: 2026-10-13. Scope: DEV, **produkcja poza zakresem**.

## Potwierdzony stan wejściowy

- Zainstalowany obserwator jest binarnie zgodny z PR #163 i działa jako root z ograniczonymi możliwościami tylko odczytu.
- Operator otrzymał **OBSERVER_WORKER_EXE_E2E=PASS**, CROSS_UID_EXE_ATTESTATION=PASS, STALE_PID_BIRTH=DENIED, MODEL_EXE_INSPECTION=DENIED i TEMPORARY_WORKER_CLEANUP=PASS. Nowa operacja odczytu /proc/exe jest już wdrożona, bez dodatkowych uprawnień dla ai-gateway-rm.
- Produkcyjne ai-gateway, ollama aktywne, Resource Manager = llm, leases=0, main bez zmian.
- Sekret kontrolny root:ai-vision-rm-control 0640, ai-vision nie ma dostępu, ai-gateway-rm ma.

## Kolejny test — rzeczywisty IPC, nadal bez GPU

**Dwie operacje administracyjne, oddzielone walidacją.**

1. Staging:
   `sudo bash deploy/vision-rm-security/stage-crossuid-dev.sh --stage`

   Kopiuje zatwierdzony kod do **root-owned** /opt/ai-platform/vision-rm-candidate (nie dotyka /opt/ai-platform/current), instaluje root-owned manifest oraz trzy usługi:
   - ai-vision-rm-dev-gateway.service — localhost:11575, real Shared Resource Manager, mock Ollama/ComfyUI (żadnych zmian modeli);
   - ai-vision-rm-broker.service — UID ai-gateway-rm, odczyt chronionego sekretu i root GPU observer;
   - ai-vision-rm-runner.service — UID ai-vision, brak sekretu kontrolera, root-owned CPU-only worker.

   **Wszystkie trzy jednostki pozostają zatrzymane i niewłączone w autostarcie.** Instalator odmawia nadpisania wcześniej istniejących plików lub wyników.

2. Test CPU-only:
   `sudo bash deploy/vision-rm-security/accept-crossuid-dev-cpu.sh --apply`

   Sprawdza pustą produkcyjną kolejkę, uruchamia na chwilę izolowany DEV Gateway z fake backendami, broker i jednokrotny CPU worker w user cgroup, kontroluje brak sekretu u modelu oraz release/cleanup. Na końcu zatrzymuje broker i DEV Gateway; nigdy nie uruchamia rzeczywistego modelu GPU ani nie restartuje produkcji.

## Kontrakty

- Root-owned stały JSON manifest: interpreter /usr/bin/python3, program /usr/local/libexec/ai-platform/vision-rm-dev-cpu-worker.py, zero argumentów zewnętrznych.
- SO_PEERCRED brokera sprawdza ai-vision i konkretny PID root-owned ai-vision-rm-runner.service wraz z hashem kodu; nie przyjmuje żądań arbitrary job/URL/shell.
- Broker przechowuje RM secret i jako jedyny wykonuje create/poll/heartbeat/begin/finish.
- Worker otrzymuje wyłącznie ograniczony token do potwierdzenia jednego przydzielonego use i nie może mutować lease.
- Jednostki DEV nie mają flagi auto-start. W przypadku niepewności procesów cgroup lub GPU cleanup marker FAIL-CLOSED, bez automatycznego odblokowania.

## Kryteria i ograniczenia

Oczekiwane: `CROSS_UID_DEV_STAGING=PASS`, a po teście `CROSS_UID_CONTROLLER_MODEL_CPU_E2E=PASS` i `PRODUCTION_GATEWAY=UNCHANGED`.

Jeśli test nie przejdzie, zachować logi z `journalctl -u ai-vision-rm-*` i nie robić automatycznej promocji. CPU-only potwierdza systemd IPC, nie fizyczny ROCm; przed zmianą produkcyjną pozostają rzeczywiste GPU pod odseparowanymi UID, odtworzenie awarii, niezależny audyt i jawna zgoda na merge.
