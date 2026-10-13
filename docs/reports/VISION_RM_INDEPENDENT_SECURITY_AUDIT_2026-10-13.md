# Niezależny przegląd bezpieczeństwa — Vision GPU / wspólny Resource Manager

Data: 2026-10-13. Podstawa: PR #161, commit fd287a6. Audyt wykonany oddzielnie od implementacji: przegląd źródeł + odtwarzalny, nieinwazyjny test HTTP na osobnym ASGI Gateway z mockowymi backendami. Nie jest zewnętrznym audytem trzeciej strony.

## WERDYKT

**PRODUCTION GATE: BLOCKED. Nie scalać ani nie włączać flagi feature na produkcji.**

Testy funkcjonalne 20/20, fizyczny WinCLIP/ROCm E2E i CI PASS potwierdzają możliwość wykonywania pracy. Nie potwierdzają kompletnego modelu bezpieczeństwa i odporności na lokalnych nieufnych klientów. Nadal istnieją istotne luki.

## Ustalenia

### SEC-01 — HIGH: endpointy Resource Lease API nie wymagają tożsamości wykonawcy

Źródło: src/ai_bridge/gateway/app.py, trasy POST/GET/DELETE /resource/leases i /uses. Lokalny dostęp loopback jest traktowany jako granica zaufania, a token lease_id jest zwracany każdemu klientowi localhost, bez uwierzytelnienia. Możliwe jest tworzenie rezerwacji, heartbeat i DELETE bez oddzielnego uwierzytelnienia wykonawcy. W scenariuszu lokalnego nieufnego procesu/podłączonego serwisu należy rozważyć DoS kolejki, manipulację rezerwacjami uzyskanymi przez klienta, podszycie się pod deklarację procesu i scope.

**Dynamiczny dowód na mock ASGI:** niezalogowany klient otrzymał 201 na POST /resource/leases profile vision-benchmark; następnie 200 na POST heartbeat i 200 na DELETE dla otrzymanego ID. Nie użyto produkcyjnego Gatewaya. To jest faktyczne obecne zachowanie, a nie tylko domniemanie.

**Wymóg:** mutual authentication lub wąski lokalny unix socket z SO_PEERCRED/UID policy i ACL, z autoryzowanym identyfikatorem wykonawcy/scope. Żądania bez tożsamości nie powinny móc uzyskać Vision GPU ownership.

### SEC-02 — HIGH: brak dowodu pochodzenia/trwałego nadzoru dziecka

Źródło: src/ai_bridge/gateway/resource_leases.py oraz gateway/vision_residency_evidence.py. Kontrola worker_pid/starttime/cgroup membership wiąże proces ze scope, ale nie dowodzi, że został utworzony przez autoryzowanego benchmark runnera, na zatwierdzonym kodzie i zbiorze, ani że token nie pochodzi od obcej lokalnej aplikacji. Zaufanie do dowolnego procesu z nazwą vision-bench-<12hex>.scope jest niewystarczające jako polityka tożsamości.

**Wymóg:** mapowanie job_id -> podpisana/uwierzytelniona rezerwacja wykonawcy -> scope/UID -> PID/starttime + plan eksperymentu/checkpoint hash; jednorazowa nieprzenoszalna autoryzacja.

### SEC-03 — HIGH: cleanup pamięci GPU nie dowodzi całkowitego braku zasobów HIP

Źródło: gateway/residency.py leave_vision() i gateway/vision_residency_evidence.py gpu_vram_used_bytes(). Zamknięty scope, puste /api/ps i mała wartość globalnego mem_info_vram_used są wartościowymi sygnałami, ale globalny UMA counter może nie wykrywać wszystkich obcych procesów/pozostałości drivera. Tolerancja 64 MiB jest pragmatyczna, nie dowodzi zerowego GPU ownership.

**Wymóg:** wiarygodne dowody procesów /dev/kfd i /dev/dri; lista aktywnych GPU clients i cgroup ownership, a nie tylko globalny licznik oraz cgroup scope; fail-closed dla niejednoznaczności.

### SEC-04 — MEDIUM: API i liveness mają luki w procesie odzyskiwania

Źródło: gateway/resource_leases.py begin_external_use() i end_external_use(), gateway/residency.py oraz benchmarks/vision_rm_scoped_executor.py. Po nieudanym cleanup marker utrzymuje blokadę poprawnie (testy to potwierdzają), ale brak zatwierdzonego automatycznego/supervisor recovery i proceduralnego rollback. Nie testowano restartu/kill Gateway DEV podczas faktycznych obliczeń GPU. Sam fakt posiadania trwałego markera nie rozwiązuje procedury operacyjnej.

**Wymóg:** operator-reviewed recovery/runbook, reason codes, atomowy fsync/rename markera, test restartu po awarii GPU na wydzielonym hoście i potwierdzenie że nie wznawia przy markerze.

### SEC-05 — MEDIUM: słaba walidacja wejść/wyjść wykonawcy i logów

Źródło: benchmarks/vision_rm_scoped_executor.py i benchmarks/vision_worker_gate.py. Wykonawca przyjmuje dowolne python/script/args przekazane przez lokalnego klienta. Token jest podawany przez plik w prywatnym temp katalogu 0700, co jest poprawnym krokiem, ale samo uprawnienie systemd scope nie potwierdza zatwierdzonego obrazu procesu ani hashów modelu. Potrzebne ograniczenie skryptów/checkpointów i praca po nieuprzywilejowanym UID.

**Wymóg:** allowlist programów i wersjonowanych benchmark manifestów, immutable code/checkpoint hashes, ograniczenie uprawnień oraz kontroli logów i tokenów.

### SEC-06 — LOW/MEDIUM: cgroup disappear = empty bez dodatkowego dowodu

Źródło: gateway/vision_residency_evidence.py scoped_processes(). FileNotFoundError dla ścieżki cgroup.procs zwraca pusty zbiór, zakładając usunięcie scope po wyjściu ostatniego procesu. Jest to prawidłowa heurystyka przy zwykłym systemd teardown, ale nie jest równoważne potwierdzeniu, że systemd scope przeszedł do terminalnego stanu i nie było PID migration/race.

**Wymóg:** sprawdzić terminalny stan scope przez systemd D-Bus / cgroup.events, rozróżnić missing mount/evidence od usuniętego zakończonego scope; odmowa przy niepewności.

## Potwierdzone mocne strony

- Default OFF dla nowych provider/capability; strict registry nie zmienia starego inventory.
- Jeden PriorityScheduler z wyłącznością GPU Vision/ComfyUI przy >1 slotach.
- Oddzielny systemd user cgroup v2, parked worker i token wydawany dopiero po admission.
- Dowód PID + starttime, cgroup scope, fail-closed marker i restart z blokadą.
- Testy SIGKILL, timeout, heartbeat loss i detached descendants (symulowany GPU), 4-obrazowy prawdziwy WinCLIP/ROCm E2E.
- Produkcyjne Qwen/Ollama/adaptery i main nienaruszone.

## Kolejność napraw

1. **P0:** SEC-01 + SEC-02 — uwierzytelniona, nieprzenoszalna tożsamość wykonawcy przy GPU admission.
2. **P0:** SEC-03 — formalny kontrakt dowodów zwolnienia GPU oraz ownership cgroup, łącznie z lokalnymi GPU clients.
3. **P1:** SEC-04 — recovery, rollback i test restartu w izolowanym środowisku bez automatycznego unblock.
4. **P1:** SEC-05 + SEC-06 — allowlist i stricter cgroup evidence.
5. Powtórzyć pełne CI, realny benchmark B1 smoke i red-team testy lokalnych klientów; **ponowny niezależny gate przed merge**.

## Granice tego audytu

To ocena niezależna w sensie oddzielnego przeglądu własnego kodu i testów; nie została przeprowadzona przez zewnętrzną firmę. Nie skanowano systemu penetracyjnie ani nie modyfikowano produkcyjnego Gatewaya. Test dynamiczny odtworzono wyłącznie w procesie mock ASGI na środowisku DEV. Wyniki mają charakter code/security review, a nie certyfikacji.

**KONKLUZJA: NO-GO production, CONTINUE DEV hardening.**
