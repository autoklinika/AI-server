# Vision RM — bramka oddzielnego kontrolera i modelu

Data: 2026-10-13. Branch: feature/vision-rm-system-security-20261013. **DEV only / no merge**.

## Potwierdzenia systemowe

- Obserwator root (read-only GPU FDs, AF_UNIX SO_PEERCRED) działa jako usługa systemd.
- Operator zweryfikował dwa realne GPU clients dla ai-vision i ai-gateway-rm.
- Nieuprawnione konto ma DENIED.
- ai-gateway-rm ma dostęp do osobnej grupy ai-vision-rm-control i poświadczenia; użytkownik potwierdził `AI_VISION_TOKEN_ACCESS=False`.
- Produkcyjne Qwen, Ollama, Gateway i main pozostały bez zmian; feature Vision nadal OFF.

## Kontroler i wykonawca — nowe komponenty DEV

- `src/ai_bridge/benchmarks/vision_rm_broker.py`: pojedynczy broker pod ai-gateway-rm z chronionym bearerem. AF_UNIX + SO_PEERCRED. Dopuszcza tylko ai-vision wewnątrz **konkretnej systemowej jednostki** ai-vision-rm-runner.service, uruchamiającej root-owned code z SHA256. Stały workload vision-benchmark i background priority; protokół jedynie create, poll, begin, finish. Brak obsługi dowolnych poleceń, adresów, kodu, modeli lub priorytetów.
- `deploy/vision-rm-security/vision_rm_runner.py`: tylko model/supervisor pod ai-vision. Weryfikuje root-owned immutable JSON manifest, uruchamia zaparkowanego workera w user-scope, czeka na broker admission, daje workerowi **tylko scoped read-only capability** do potwierdzenia aktywnego use. W modelu nie ma ani kontrolnego bearera, ani ścieżki do jego pliku.
- ResourceLease Registry: jednorazowy, ograniczony do aktywnego Vision-use token, nie pozwalający na POST/DELETE/heartbeat; token traci ważność przy zwolnieniu zasobu. Brak wpływu na dotychczasowe zadania LLM/WVC i ComfyUI z wyłączoną funkcją Vision.
- `vision_residency_evidence.worker_cgroup_path(expected_uid=...)` oraz `gateway_vision_worker_uid`: jawne zaufane UID modelu różne od kontrolera.
- `ai-vision-rm-broker.service`, `ai-vision-rm-runner.service`: szablony root-owned systemd. Domyślny URL **localhost:11575 DEV**, a nie port 11435 produkcji. Nie instalowano/nie uruchamiano.
- Stary same-UID ScopedVisionExecutor ma blokadę dla środowiska z protected-file credential, by nie omijać nowej izolacji.

## Zakres testów

- Lokalny mock Gateway + realny AF_UNIX peer credential test; odmowa obcego UID i niedozwolonych RPC, jeden aktywny lease, właściciel PID/starttime, token tylko do odczytu, negatywne testy POST/DELETE/heartbeat.
- Pełny lokalny suite Python CI w DEV.
- Realny cross-UID end-to-end i GPU/ROCm **nie zostały** wykonane przez nowy broker. Konta ai-gateway-rm i ai-vision nie mogą być używane w modelowym remote shell bez autoryzacji administratora. Nie wolno imitować tego wyniku testami pod harrypotter.

## Kolejna bramka — read-only diagnoza między UID

Wymagany wynik `sudo bash deploy/vision-rm-security/probe-cross-uid-worker.sh --verify` (sprawdza /proc/stat, /proc/cgroup, /proc/cmdline i /proc/exe dla chwilowego, nie-GPU procesu pod ai-vision, czytając go spod ai-gateway-rm; nie dotyka produkcji ani sekretu).

Jeśli którykolwiek dowód nie jest czytelny, fail-closed i adaptacja attestation z wykorzystaniem ograniczonego root observer — bez nadawania ai-gateway-rm CAP_SYS_PTRACE.

## Nie spełniono jeszcze

- Wdrożenie root-owned broker/runner i immutable manifest na **oddzielnym DEV**.
- Pełne rzeczywiste IPC ai-gateway-rm → ai-vision i test odmowy IPC procesu modelu, potem GPU probe przez uprzywilejowanego obserwatora.
- Test crash/restart kontrolera oraz utrata sieci, gdy GPU nadal jest zajęte, powtórna niezależna ocena audytowa.
- Osobna decyzja operatora w sprawie merge/cutover produkcyjnego Gatewaya.

**Production gate: NO-GO until independent cross-UID e2e PASS.**
