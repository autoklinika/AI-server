# Vision GPU / Resource Manager — SEC-01–SEC-06, remediation DEV

**Status: DEV HARDENING. Produkcja nadal NO-GO.** Ocena źródłowa: PR #162, audyt security, report VISION_RM_INDEPENDENT_SECURITY_AUDIT_2026-10-13.md.

## Wykonane zmiany

| Ustalenie | Implementacja | Dowód / status |
|---|---|---|
| SEC-01 HIGH: anonymous Resource Lease API | Przy feature flag Vision wymagana tajna wartość minimum 32 znaków w `gateway_vision_executor_token`; bez niej Gateway nie wystartuje. Każda operacja `/resource/leases` (create, GET, POST, heartbeat, DELETE, uses) odrzuca błędne/nieobecne poświadczenie `x-ai-vision-executor-token` kodem 403. Weryfikacja w stałym czasie. Legacy API dla flagi OFF niezmienione. Nie stosować globalnego middleware — zepsułby scheduling starych HTTP. | Unauthenticated 403, credentialed 201/200; regresja routingu PASS. **Częściowo zamknięte**: ten sam UID może potencjalnie pozyskać env sekret. Produkcja wymaga osobnego service UID/ACL i odseparowanego kanału transportu. |
| SEC-02 HIGH: worker provenance | Obowiązkowa niepusta lista dozwolonych skryptów oraz SHA256. Gateway sprawdza faktyczny cmdline procesu w /proc, ustalony interpreter exe, **przypięty SHA-256 programu `vision_worker_gate.py`**, zawartość zatwierdzonego skryptu i jawnie wskazanego checkpointu (jeżeli występuje). Worker musi już znajdować się w dopuszczonym cgroup. | Real parked-child attestation: allow/deny, mutacja pliku -> DENY. **Częściowo zamknięte**: TOCTOU przy zmianie plików przez ten sam UID; do produkcji wymagane root-owned immutable release + oddzielny UID. |
| SEC-03 HIGH: HIP ownership | Dodano drugi, domyślnie WYMAGANY przy Vision ON, dowód własności: pełny odczyt /proc/*/fd w celu ustalenia klientów /dev/kfd i /dev/dri/renderD*, z tożsamością PID/starttime. Brak dostępu do choćby jednej przestrzeni UID oznacza fail-closed, a pojawienie się nowego klienta GPU po cleanup blokuje slot. Zachowano sprawdzenie pustego cgroup, Ollama /api/ps, ComfyUI idle i DRM VRAM po unload. Zdiagnozowano brak uprawnień do `/sys/kernel/debug/dri/0/clients` oraz /proc/PID/fd użytkownika ollama. Nie zgadujemy, że globalny licznik pamięci dowodzi braku obcych kontekstów GPU. | **CODE / TEST PASS, HOST GATE BLOCKED:** probe i testy negatywne działają, lecz na bieżącym koncie obserwator nie ma uprawnień do odczytu /proc innych UID, więc produkcyjny gate słusznie odmawia. Wymagany uprzywilejowany, ograniczony wyłącznie do odczytu obserwator lub zatwierdzony odpowiednik. DEV-only flaga gateway_vision_strict_gpu_clients=False pozwala wykonywać nadzorowane smoke bez twierdzenia, że przeszły pełny production gate. Nie instalować nowego sensora w produkcji bez osobnej zgody. |
| SEC-04 MEDIUM: recovery/rollback | Trwały marker atomowo zapisany przez plik 0600 + fsync pliku + os.replace + fsync katalogu. Restart z markerem blokuje przydział. Runbook ręcznej walidacji i jawnego restore; brak auto-unblock. | Istniejące testy fail closed, testy marker+restart PASS; fizyczny destrukcyjny SIGKILL podczas HIP nadal NIE wykonywany. |
| SEC-05 MEDIUM: arbitrary program | Łącze RM ma script allowlist + SHA256. Worker potwierdza use token i usuwa poświadczenie RM z env **przed execv modelu**. Checkpoint wskazany przez `--checkpoint` musi mieć zgodną sumę z listą Gateway. | Test procesu po execv wykazuje brak sekretu w środowisku modelu; atestacja zmiany skryptu odmawia. Przed produkcją ścieżki i model files root-owned/immutable. |
| SEC-06 LOW/MEDIUM: missing cgroup | `scoped_processes` zwraca Unknown (None), jeśli nie można przeczytać cgroup.procs. Clean state po zniknięciu cgroup jest dopuszczony wyłącznie po dodatkowym sprawdzeniu systemd user scope: ActiveState=inactive, ControlGroup pusty; brak dowodu blokuje release. | Real systemd scope tests + orphan descendant PASS. |

## Granice i wymagania produkcyjne

1. Uwierzytelnianie przez bearer na loopback zabezpiecza przed klientem bez tokenu, lecz **nie przed nieufnym procesem mającym ten sam UID**. Token i zatwierdzone skrypty muszą być obsługiwane przez dedykowane, nieuprzywilejowane konto serwisowe, z kontrolą ACL i izolacją od innych aplikacji.
2. W produkcji strict GPU clients jest domyślnie ON i brak globalnego odczytu /proc/fd oznacza fail-closed. Potrzebne jest kontrolowane uprawnienie (oddzielny read-only helper z audytem i ACL) do wszystkich GPU clients. Bez tego samo VRAM baseline + 64 MiB nie dowodzi kontekstów HIP. Wyłączenie tej kontroli tylko dla nadzorowanych testów DEV, bez produkcyjnych obietnic.
3. Funkcja domyślnie OFF w produkcji, a brak poprawnej konfiguracji poświadczenia/allowlist przy ON powoduje odmowę startu Gatewaya.
4. Dalsze testy fizycznego GPU i CI można uruchamiać na osobnym DEV Gateway tylko przy zabezpieczonej produkcyjnej kolejce; brak promocji do main.

## Ręczny recovery / rollback — operacje tylko po decyzji operatora

**Read-only diagnoza:** sprawdź `/status` i `gpu_residency.recovery_required`, zidentyfikuj marker produkcyjny/DEV, zweryfikuj brak aktywnych leases, `/api/ps` Ollama, ComfyUI /queue i /ai-platform/residency, rzeczywiste scope przez `systemctl --user list-units 'vision-bench-*.scope'`, `cgroup.procs`, oraz GPU clients przez uprawniony obserwator.

**Jeśli proces jeszcze żyje:** nie usuwaj markera i nie wykonuj manualnego unload Ollamy. Operator kończy zaufany scope i weryfikuje, że wszystkie descendants odeszły. Nie używać reboot jako substytutu walidacji GPU.

**Jeśli wskaźnik cleanup jest niepewny:** pozostawić `recovery_required=true`. Nie restartować i nie odblokowywać automatycznie; zachować logi, PID/starttime, scope, checkpoint hash, zdarzenia dmesg oraz kopię markera.

**Wznowienie:** wyłącznie po niezależnym pozytywnym attestation wszystkich dowodów, zatwierdzony supervisor recovery i jawna decyzja operatora. Przy niepowodzeniu przywrócić poprzedni binarny release/konfigurację bez ustawiania Vision flag i utrzymać trwały blocked marker aż do odrębnej procedury recovery.

**Brak automatycznego merge/promote/restart.** Ten raport nie autoryzuje produkcji.

## Bramka GPU-client i fizyczna regresja po zabezpieczeniach

Na DEV uruchomiono drugi wariant wymaganego dowodu GPU, porównujący zbiór PID+starttime wszystkich procesów z otwartym `/dev/kfd` lub `/dev/dri/renderD*` przed i po zadaniu. Każdy brak uprawnień do odczytu `/proc/*/fd` zwraca Unknown, nigdy pusty zbiór. **Testy symulowane PASS**: brak cross-UID evidence nie dopuszcza GPU, pojawienie się nowego klienta uniemożliwia cleanup, stabilny zbiór klientów pozwala na release.

Fizyczny host uruchomiony jako `harrypotter` zgłasza **HOST_CROSS_UID_GPU_CLIENT_EVIDENCE=UNAVAILABLE_FAIL_CLOSED** (brak praw do `/proc/3005/fd` użytkownika Ollama oraz `/sys/kernel/debug/dri`). Dlatego `gateway_vision_strict_gpu_clients=True` (domyślnie) nie może jeszcze bezpiecznie przejść produkcyjnej bramki. Nadzorowany test czterech obrazów GPU po wszystkich poprawkach wykonano na izolowanym Gateway DEV z jawnie ustawionym `gateway_vision_strict_gpu_clients=False`; 4/4 inferencje i weryfikacja VRAM/cgroup/lease **PASS**, cały test 17,0s, DEV marker usunięty po weryfikacji, produkcja nietknięta.

Dodatkowo: przy `gateway_vision_external_enabled=True` wymagany jest przypięty `gateway_vision_worker_gate_sha256`; błędny digest gate oznacza brak autoryzacji nawet dla skryptu o poprawnej sumie. Sekret executor zostaje usunięty z env **przed uruchomieniem modelu**; end-to-end test to potwierdził.

Pełny lokalny zestaw AI Platform po najnowszej implementacji: **VERIFIED_PYTEST_RC=0**. CI GitHub nowego commitu jeszcze niewykonane na etapie tego raportu.
