# Rzeczywisty wykonawca RADIO — gotowy do pilotażu operatora

Data: 20.10.2026. Kontynuacja draft PR #174. Bazowy etap kontraktów: `ee28746`.

## Aktualny wynik

| Obszar | Wynik |
|---|---|
| Kod wykonawcy RADIO i klienta Gateway | Zaimplementowany |
| Regresja CPU | **820 PASS**, exit 0, 25 modułów, 6,78 s |
| Pakiet źródłowy | **SOURCE_SHA256_PASS**, 175 plików |
| Import w rzeczywistym Pythonie produkcyjnego Gateway | PASS: FastAPI 0.141.1, Pydantic 2.13.5, HTTPX 0.28.1 |
| Statyczna walidacja jednostki systemd | PASS, `systemd-analyze verify`, exit 0 |
| Prawdziwy proces CPU/systemd na hoście | PASS dla zachowania terminalnej usługi i usuwania jej cgroup |
| Instalacja wykonawcy i inferencja RADIO przez RM | **PENDING_OPERATOR / NOT_RUN** |
| Wdrożenie Vision w produkcyjnym Gateway | **NOT_PERFORMED** |
| Globalne `GPU_REUSE_SAFE` / automatyczny grant N1 | Nadal `NOT_VERIFIED` / `NOT_ADMITTED` |

Poprzednia blokada „brak implementacji wykonawcy” ma już rozwiązanie w kodzie. **Odbiór na GPU nadal wymaga wykonania poniższego pilotażu.** Nie jest to deklaracja `GPU_PILOT_PASS` ani `PRODUCTION_PASS`.

## Co zostało dodane

- `radio_worker.py`: jeden przypięty AnomalyVFM RADIO, zachowany runtime ROCm i kalibracyjny obraz `visa-pcb2-normal-0000`. Sprawdza SHA obrazu i checkpointu oraz fizyczny BDF `0000:c6:00.0`/gfx1150. Przed zezwoleniem rodzica nie importuje PyTorch ani nie otwiera GPU. Po obliczeniu zachowuje kontekst do obserwacji, a po poleceniu release synchronizuje, usuwa model i naturalnie kończy proces.
- `radio_supervisor.py`: root-owned wykonawca z lokalnym socketem Unix. Uruchamia wyłącznie ten stały program jako istniejący `ai-vision` UID 994. Nie tworzy kolejki, schedulera ani nowego RM. Model nie ma dostępu do socketu sterującego ani tokenów Gateway. API nie przyjmuje komendy, ścieżki, URL, wyboru interpretera lub modelu.
- `RadioExecutorClient`: realizuje dotychczasowy kontrakt `VisionExecutor`; weryfikuje UID 0 serwera i sesję wykonania. Po restarcie, utracie ownera lub nieznanym wyniku odmawia wykonania/release.
- Kontrolowany worker systemd ma nieprzekazywalną cgroup, brak uprawnień do przenoszenia procesów poza przypisaną cgroup, ograniczenie przestrzeni nazw i brak komunikacji sieciowej/socketów. Używa istniejących grup konta `ai-vision`; nie zmienia render/video, sterownika ani uprawnień urządzeń. Pozycja bazowego Pythona pod `/home` jest udostępniona workerowi wyłącznie przez read-only bind, bez otwierania całego katalogu domowego.

## Co potwierdza cleanup

Wynik workera ani `empty_cache()` nie stanowią autoryzacji release. Zaufany rodzic wymaga jednocześnie:

1. Tej samej jednostki, InvocationID, PID i cgroup, bez delegowania cgroup.
2. Naturalnego końca właściwego procesu: exit 0, systemd `active/exited`, niezerowy czas zakończenia.
3. Pustej cgroup w jądrze albo jej usunięcia po zakończeniu tej samej terminalnej jednostki. Sprawdzony na rzeczywistym procesie CPU przypadek `ControlGroup=""` nie jest mylony z brakiem dowodów.
4. Trzech kolejnych niezależnych odczytów FD/DRM i KFD, bez uchwytów zamkniętego workera i bez nowych obcych właścicieli. Dopuszczone dotychczasowe konteksty bezczynnych Ollamy/ComfyUI muszą pozostać zgodne z bazą.
5. Braku nowych wykrytych błędów AMDGPU/MES od kursora dziennika sprzed startu.

Dopiero wtedy rodzic zwraca `SUPERVISED_SCOPE_CLOSED`, a istniejący Gateway może rozliczyć lokalny legacy-exclusive lease. To potwierdzenie **konkretnego nadzorowanego wykonania**, nie globalny certyfikat sterownika. N1/N3 oraz istniejący niezatwierdzający protokół terminalny obserwatora nie są zmieniane. Obserwator pozostaje read-only; root-owned wykonawca wykorzystuje jego zainstalowany kolektor odczytowy.

Przy timeoutcie, niezerowym exit, awarii, restartach, potomkach, obcych uchwytach lub błędach sterownika pozostają markery i `BLOCKED`. Nie ma automatycznego resetu sterownika ani usuwania niepewnych markerów.

## Przebieg komendy operatora

1. Sprawdza SHA manifestu oraz wszystkich 175 plików, w tym własnego instalatora; kopiuje zweryfikowane bajty do osobnego root-owned, wersjonowanego katalogu `/opt/ai-platform/vision-radio/releases/389beaa97b117833`.
2. Instaluje i uruchamia tylko stałego wykonawcę. Nie włącza go do autostartu i nie nadpisuje żadnego release ani overlay Gateway.
3. Sprawdza idle, timer analizy i rzeczywistą produkcyjną ścieżkę markera GPU.
4. Rezerwuje okno poprzez lease w **działającym RM**. Jeżeli inne zadanie wygra slot lub pojawi się kolejka, pilotaż wycofuje swoją rezerwację. Nie przerywa pracującego zadania.
5. Zatrzymuje produkcyjny Gateway na czas okna odbiorczego i uruchamia jedną aktywną instancję tego samego Gateway RM w procesie pilota. Nie ma dwóch równocześnie działających instancji RM. Pilotaż nie wystawia nowego listenera HTTP.
6. Wykonuje Ollama → RADIO → Ollama i ComfyUI → RADIO → ComfyUI. Dwie pojedyncze inferencje dotyczą tego samego przypiętego obrazu kalibracyjnego i zapisują nowe mapy w osobnych katalogach. Ollama wykonuje realne embedding bge-m3; ComfyUI przechodzi rzeczywisty cykl prepare/verify/free, **bez generowania obrazu**.
7. Przywraca poprzedni Gateway. Po porażce ma on wrócić w `BLOCKED`; marker nie jest usuwany. Po sukcesie ma wrócić do `IDLE`. Zatrzymuje proces nadzorcy po oknie; nie restartuje Ollamy ani ComfyUI podczas przełączeń.

Instalacja root i GPU wymagają interaktywnego operatora. Remote Desktop Commander odrzucił polecenie zawierające `sudo`; nie próbowano obchodzić tego ograniczenia. Wszystkie wykonywane dotychczas zdalne etapy były CPU lub odczytowe.

## Jedna komenda na AI Platform

```bash
sudo /usr/bin/python3 -I /srv/ai-data/evaluation/vision-engine-integration-20261020/tools/install_vision_radio_pilot.py --pilot --manifest-sha256 389beaa97b11783361ff8ec49e60dfbe15e3ca7da70d327626c4ee47eca46acf
```

Oczekiwany wynik końcowy: `result=GPU_PILOT_PASS`, `prior_gateway_restored=true`. Alternatywnie `BLOCKED` z przyczyną; tego wyniku nie traktować jako PASS ani nie usuwać markerów, aby go zmienić.

Raport lokalny: `/var/lib/ai-platform-radio/PILOT_RESULT.json`. Diagnostyka nadzorcy: `/var/lib/ai-platform-radio/LAST_ERROR.json`. Mapy i dowody zamknięcia pozostają w oddzielnych katalogach `/var/lib/ai-platform-radio/sessions/`. Nie publikować surowych plików zawierających lease/use IDs. Zachowany benchmark i oryginalny checkpoint nie są nadpisywane.

Po rzeczywistym PASS należy przygotować osobny produkcyjny overlay, kontrolę zależności i odbiór wdrożenia/rollbacku. Ta komenda **nie promuje** modelu ani integracji do produkcji. Nie scalać draft PR do main bez akceptacji.

## Dowody CPU i ograniczenia

Nowe testy obejmują terminalne i niepełne dowody, złą inkarnację, pozostałych potomków, zmienione ograniczenia jednostki, błędny exit, brak cgroup2, zły owner, niepoprawny JSON, brak autoryzacji release, checksum/path traversal, wyścig z pracującym zadaniem, przywrócenie Gateway po błędzie oraz uprawnienia control files przy `umask 0077`.

Pełny log: `VISION_RADIO_EXECUTOR_CPU_TESTS_2026-10-20.log`. Pakiet jest przypięty manifestem `deploy/vision-radio/BUNDLE_SHA256.json`. Walidacja jednostki miała jedynie istniejące ostrzeżenie dotyczące TeamViewer `/var/run`; regresja miała jedno istniejące ostrzeżenie Starlette/httpx.

Nie wykonano inferencji GPU, instalacji root ani migracji produkcyjnej bez komendy operatora. Testy z mockami nie dowodzą bezpieczeństwa sterownika. Odczyt produkcji po zakończeniu: Gateway `ok`, RM `IDLE`, Vision nadal niedostępne.
