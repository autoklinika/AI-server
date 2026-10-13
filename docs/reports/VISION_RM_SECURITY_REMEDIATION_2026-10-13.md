# Vision GPU / Resource Manager — SEC-01–SEC-06, remediation DEV

**Status: DEV HARDENING. Produkcja nadal NO-GO.** Ocena źródłowa: PR #162, audyt security, report VISION_RM_INDEPENDENT_SECURITY_AUDIT_2026-10-13.md.

## Wykonane zmiany

| Ustalenie | Implementacja | Dowód / status |
|---|---|---|
| SEC-01 HIGH: anonymous Resource Lease API | Przy feature flag Vision wymagana tajna wartość minimum 32 znaków w `gateway_vision_executor_token`; bez niej Gateway nie wystartuje. Każda operacja `/resource/leases` (create, GET, POST, heartbeat, DELETE, uses) odrzuca błędne/nieobecne poświadczenie `x-ai-vision-executor-token` kodem 403. Weryfikacja w stałym czasie. Legacy API dla flagi OFF niezmienione. Nie stosować globalnego middleware — zepsułby scheduling starych HTTP. | Unauthenticated 403, credentialed 201/200; regresja routingu PASS. **Częściowo zamknięte**: ten sam UID może potencjalnie pozyskać env sekret. Produkcja wymaga osobnego service UID/ACL i odseparowanego kanału transportu. |
| SEC-02 HIGH: worker provenance | Obowiązkowa niepusta lista dozwolonych skryptów oraz SHA256. Gateway sprawdza faktyczny cmdline procesu w /proc, ustalony interpreter exe, zaufany `vision_worker_gate.py`, zawartość zatwierdzonego skryptu i jawnie wskazanego checkpointu (jeżeli występuje). Worker musi już znajdować się w dopuszczonym cgroup. | Real parked-child attestation: allow/deny, mutacja pliku -> DENY. **Częściowo zamknięte**: TOCTOU przy zmianie plików przez ten sam UID; do produkcji wymagane root-owned immutable release + oddzielny UID. |
| SEC-03 HIGH: HIP ownership | Utrzymano sprawdzenie pustego cgroup, Ollama /api/ps, ComfyUI idle oraz DRM VRAM po unload. Zdiagnozowano brak uprawnień do `/sys/kernel/debug/dri/0/clients` oraz /proc/PID/fd użytkownika ollama. Nie zgadujemy, że globalny licznik pamięci dowodzi braku obcych kontekstów GPU. | **BLOCKED** do czasu dostarczenia uprzywilejowanego tylko-do-odczytu, audytowanego obserwatora aktywnych klientów GPU albo zatwierdzonego ekwiwalentu. Nie instalować nowego sensora w produkcji bez osobnej zgody. |
| SEC-04 MEDIUM: recovery/rollback | Trwały marker atomowo zapisany przez plik 0600 + fsync pliku + os.replace + fsync katalogu. Restart z markerem blokuje przydział. Runbook ręcznej walidacji i jawnego restore; brak auto-unblock. | Istniejące testy fail closed, testy marker+restart PASS; fizyczny destrukcyjny SIGKILL podczas HIP nadal NIE wykonywany. |
| SEC-05 MEDIUM: arbitrary program | Łącze RM ma script allowlist + SHA256. Worker potwierdza use token i usuwa poświadczenie RM z env **przed execv modelu**. Checkpoint wskazany przez `--checkpoint` musi mieć zgodną sumę z listą Gateway. | Test procesu po execv wykazuje brak sekretu w środowisku modelu; atestacja zmiany skryptu odmawia. Przed produkcją ścieżki i model files root-owned/immutable. |
| SEC-06 LOW/MEDIUM: missing cgroup | `scoped_processes` zwraca Unknown (None), jeśli nie można przeczytać cgroup.procs. Clean state po zniknięciu cgroup jest dopuszczony wyłącznie po dodatkowym sprawdzeniu systemd user scope: ActiveState=inactive, ControlGroup pusty; brak dowodu blokuje release. | Real systemd scope tests + orphan descendant PASS. |

## Granice i wymagania produkcyjne

1. Uwierzytelnianie przez bearer na loopback zabezpiecza przed klientem bez tokenu, lecz **nie przed nieufnym procesem mającym ten sam UID**. Token i zatwierdzone skrypty muszą być obsługiwane przez dedykowane, nieuprzywilejowane konto serwisowe, z kontrolą ACL i izolacją od innych aplikacji.
2. Sam globalny AMD DRM VRAM baseline + 64 MiB nie jest pełnym dowodem zwolnienia kontekstów HIP (SEC-03). Sensor poza zasięgiem obecnego nieuprzywilejowanego użytkownika.
3. Funkcja domyślnie OFF w produkcji, a brak poprawnej konfiguracji poświadczenia/allowlist przy ON powoduje odmowę startu Gatewaya.
4. Dalsze testy fizycznego GPU i CI można uruchamiać na osobnym DEV Gateway tylko przy zabezpieczonej produkcyjnej kolejce; brak promocji do main.

## Ręczny recovery / rollback — operacje tylko po decyzji operatora

**Read-only diagnoza:** sprawdź `/status` i `gpu_residency.recovery_required`, zidentyfikuj marker produkcyjny/DEV, zweryfikuj brak aktywnych leases, `/api/ps` Ollama, ComfyUI /queue i /ai-platform/residency, rzeczywiste scope przez `systemctl --user list-units 'vision-bench-*.scope'`, `cgroup.procs`, oraz GPU clients przez uprawniony obserwator.

**Jeśli proces jeszcze żyje:** nie usuwaj markera i nie wykonuj manualnego unload Ollamy. Operator kończy zaufany scope i weryfikuje, że wszystkie descendants odeszły. Nie używać reboot jako substytutu walidacji GPU.

**Jeśli wskaźnik cleanup jest niepewny:** pozostawić `recovery_required=true`. Nie restartować i nie odblokowywać automatycznie; zachować logi, PID/starttime, scope, checkpoint hash, zdarzenia dmesg oraz kopię markera.

**Wznowienie:** wyłącznie po niezależnym pozytywnym attestation wszystkich dowodów, zatwierdzony supervisor recovery i jawna decyzja operatora. Przy niepowodzeniu przywrócić poprzedni binarny release/konfigurację bez ustawiania Vision flag i utrzymać trwały blocked marker aż do odrębnej procedury recovery.

**Brak automatycznego merge/promote/restart.** Ten raport nie autoryzuje produkcji.
