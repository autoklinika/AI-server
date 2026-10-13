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

   **Wszystkie trzy jednostki pozostają zatrzymane i niewłączone w autostarcie.** Instalator nie nadpisuje wcześniej istniejących plików: jeśli staging istnieje, wymaga pełnej zgodności plików, hashy, własności root, praw katalogów, jednostek i braku autostartu. Niekompletne lub zmodyfikowane stagingi są blokowane bez kasowania danych. Weryfikacja read-only, bez sudo: `bash deploy/vision-rm-security/stage-crossuid-dev.sh --verify`.

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

## Diagnostyka i korekta stagingu — 2026-10-13, 18:59 CEST

Rzeczywista inspekcja serwera przez Remote Desktop Commander, przed poprawką:

| Jednostka | UnitFileState | is-enabled (stdout / RC) | ActiveState | Autostart |
|---|---|---|---|---|
| ai-vision-rm-dev-gateway | static | static / 0 | inactive | brak |
| ai-vision-rm-broker | disabled | disabled / 1 | inactive | brak |
| ai-vision-rm-runner | disabled | disabled / 1 | inactive | brak |

Przyczyna komunikatu `DEV_UNIT_UNEXPECTEDLY_ENABLED=ai-vision-rm-dev-gateway` jest potwierdzona: `systemctl is-enabled --quiet` zwraca **0 również dla jednostki static**. Nie było autostartu; wszystkie jednostki były nieaktywne. Staging był już fizycznie zainstalowany, w całości root-owned. Nic nie usunięto ani nie przeinstalowano.

Poprawka gałęzi PR #163:
- `stage-crossuid-dev.sh --verify` — read-only, uruchamialny bez `sudo`.
- `--stage` — przy istniejącym stagingu waliduje go i kończy bez nadpisania; niekompletne lub rozbieżne dane oznacza **BLOCKED**.
- `verify-crossuid-dev-stage.py` — porównanie całego drzewa źródeł i staged, SHA-256 zawartości, wykrywanie dodatkowych/brakujących plików, root ownership, uprawnienia plików i katalogów nadrzędnych, brak symlinków autostartu, jawne UnitFileState i nieaktywność jednostek.
- `test_verify_crossuid_dev_stage.py` — przypadki dodatnie i negatywne (static, enabled, active, symlink autostartu, zmienione dane, niewłaściwy właściciel).

Wyniki weryfikacji bez praw administratora: `DEV_STAGING_VERIFICATION=PASS`, `DEV_STAGING_INTEGRITY=PASS`, `DEV_STAGING_AUTOSTART=ABSENT`; jednostki DEV pozostawały zatrzymane. Weryfikacja nie oznacza zaliczenia CPU-only E2E.

**Nadal NO-GO dla produkcji.** Do wykonania pozostaje rzeczywisty `accept-crossuid-dev-cpu.sh --apply` jako root. W sesji Remote MCP `sudo -n true` zwraca `interactive authentication is required`; nie uruchamiano usług DEV bez autoryzacji, nie obchodzono polityki systemu. Po autoryzacji należy uruchomić CPU-only E2E, zebrać logi, sprawdzić zwolnienie lease i brak zmian produkcji przed jakimkolwiek testem GPU lub decyzją o merge.

## Pierwszy realny CPU-only E2E — FAIL i poprawka (2026-10-13, 21:07 CEST)

Operator uruchomił `accept-crossuid-dev-cpu.sh --apply`. Potwierdzone rzeczywistym stdout i `journalctl`:

- `PRODUCTION_RM_IDLE=PASS`
- `ISOLATED_DEV_GATEWAY_READY=PASS`
- `ISOLATED_BROKER_SOCKET_READY=PASS`
- `ai-vision-rm-runner.service` FAILED, `ai-vision-rm-broker.service` exited code 1.
- W brokerze `vision_rm_executor.call()`: `TypeError: can only concatenate str (not "PosixPath") to str`.
- Root cause: zmienna `path` reprezentująca endpoint `/resource/leases` została nadpisana przez `Path(token_path)` po przejściu na oddzielne konto z poświadczeniem w pliku. Mockowe testy z tokenem środowiskowym nie obejmowały tego przebiegu.
- Runner otrzymał zerwane IPC i zgłosił `broker reply invalid` jako efekt wtórny; nie było inferencji GPU.

Po awarii: systemd DEV gateway/broker inactive, runner failed (systemd bookkeeping), produkcyjne ai-gateway/ollama/observer active, port 11435 listening, 11575 absent; produkcyjny /status: residency llm, `recovery_required=false`, leases=0, active=0, queued=0.

**Poprawki DEV:**
1. `vision_rm_executor.py`: oddzielenie `credential_file` od ścieżki HTTP; kontrola symlinków i wzmocniona walidacja rzeczywistego loopback URL, aby `127.0.0.1:port@outside` nie przekazał bearer poza host.
2. `tests/test_vision_rm_executor_protected_file_dev.py`: testy stdlib (bez zależności production), POST/GET/DELETE po file-based token, błędny bearer, niedozwolone uprawnienia, symlink i złośliwe URL. PASS 5/5.
3. `test_verify_crossuid_dev_stage.py`: przypadek istniejącego root-owned stagingu, którego SHA różni się po poprawce, pozostaje oczekiwanym fail-closed; testy PASS 7/7.
4. `refresh-crossuid-executor-dev.sh --apply-and-test`: **oddzielny krok administracyjny**. Wymaga dokładnego starego i nowego SHA, weryfikuje cały istniejący root-owned staging z dokładnie jedną dozwoloną różnicą, brak działających usług/workerów i markerów awarii; atomowo aktualizuje wyłącznie `vision_rm_executor.py`, czyści status failed *wyłącznie* usługi DEV runnera, ponownie wykonuje pełne attestation i następnie uruchamia CPU-only E2E. Nie dotyka `/opt/ai-platform/current`, produkcyjnego Gatewaya, Ollamy ani observera.

**Bramka nadal NO-GO do czasu powtórzenia realnego E2E**, niezależnych dowodów bezpieczeństwa i dopiero potem fizycznego testu WinCLIP ROCm na rozdzielonych kontach. Żaden test CPU-only nie dowodzi własności GPU w rzeczywistym obciążeniu.
