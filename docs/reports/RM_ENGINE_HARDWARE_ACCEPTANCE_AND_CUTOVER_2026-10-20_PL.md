# AI Platform — odbiór GPU i pakiet bezpiecznego wdrożenia RM V1 (2026-10-20)

## Wynik odbioru sprzętowego
**REAL_HARDWARE_ACCEPT_PASS** na Minisforum z Radeon 890M. Test w izolowanym
Gateway DEV (ASGI, bez drugiej usługi systemd) korzystał z rzeczywistych
API pracujących Ollamy i ComfyUI. Operator nie zatrzymywał ich procesów.

Kolejność i wyniki:
1. Kontrola nieaktywnego produkcyjnego RM (kolejka=0, lease=0,
   Ollama /api/ps=[], ComfyUI idle, brak DIRTY) **PASS**.
2. Rzeczywisty /api/embed na Ollamie, model bge-m3:latest:
   jeden embedding 1024-wymiarowy **PASS**.
3. Własna rezerwacja w Gateway DEV; wejście w ComfyUI
   poprzez /resource/leases/{id}/uses. Stan RUNNING/comfyui,
   jedna aktywna rezerwacja i weryfikacja owner tokenu **PASS**.
4. Zwolnienie MEDIA poprzez istniejący GPUResidency.leave_media
   (/free, /ai-platform/residency, kolejka i VRAM);
   zwolnienie lease, stan IDLE, brak DEV DIRTY **PASS**.
5. Produkcyjny Gateway nieprzerwanie aktywny, po teście
   status ok, brak zadań i niezmieniony release **PASS**.

Pierwsze dwie próby testu wykryły defekt diagnostyczny:
JobState.snapshot() przechowuje workload jako tuple, podczas gdy
nowy widok ownera akceptował wyłącznie list. Objaw: media działało,
ale diagnostyka pokazywała BLOCKED/active_engine=null. Poprawiono
akceptację list/tuple tylko w zaufanym in-process snapshot;
dodano test regresyjny rzeczywistego API. Nie rozluźniono admission.
Po poprawce test na kodzie DEV i minimalnym backporcie Stage O:
**REAL_HARDWARE_ACCEPT_PASS** (oba).

## Minimalny wariant produkcyjny
Bieżący Stage O: `/opt/ai-platform/releases/stage-o-28e3ea214660`.
Nie modyfikujemy release, jego metadanych ani globalnego symlinka
`/opt/ai-platform/current`.

`tools/build_rm_gateway_candidate.py` z SHA256 porównuje bazowe
pliki, tworzy źródła **oryginalnego** ai-gateway i nanosi tylko
cztery zatwierdzone pliki gateway:
- zmienione `app.py`, `resource_leases.py`;
- nowe `engine_state.py`, `engine_lifecycle.py`.
Nie przenosi DEV scheduler, N1/N2, GPU pilot ani managed-worker.
`residency.py`, `scheduler.py`, settings i pozostałe źródła
pozostają bajtowo identyczne z zaakceptowaną produkcją.
Dołącza niezmienione dane benchmarków, wymagane dla Control Center,
oraz pełny manifest SHA256 (237 plików).

Wariant zweryfikowano na produkcyjnym interpreterze:
`PRODUCTION_PYTHON_IMPORT_PASS` oraz hardware API
`REAL_HARDWARE_ACCEPT_PASS`.
CPU-regresja istniejącego Gateway, mediów, schedulerów, Control
Center/Platform API: **261/261 PASS**.
Testy skryptu cutover/rollback z zamockowanym systemd: **4/4 PASS**.
Log: `/tmp/rm-gateway-backport-full-20261020.log`.

## Cutover operatora
Zdalny agent nie ma interaktywnego `sudo`, więc **nie zastosowano
zmian systemd ani nie zatrzymano działającej AI Platform**.
Bieżący stan: preflight `PREFLIGHT_PASS`, bez niepoprawnego markera.

Jedna komenda w terminalu konta harrypotter:
```bash
sudo python3 /srv/ai-data/evaluation/rm-engine-hardware-accept-20261020/tools/deploy_rm_gateway_backport_v1.py --apply
```
Skrypt (tryb domyślny tylko read-only) powtarza bramki bezpieczeństwa,
weryfikuje manifest 237 plików, instaluje niemodyfikowalny root-owned
overlay pod /opt/ai-platform/gateway-overlays/, zatrzymuje **tylko**
`ai-gateway.service`, instaluje jeden systemd drop-in PYTHONPATH,
wykonuje daemon-reload i start Gateway. Ollama, Bridge i ComfyUI
pozostają aktywne. Po starcie sprawdza: nowy /status
(resource_manager IDLE, Vision execution false), /health, Control
Center, API benchmarków, endpoint Ollamy, zero zadań i brak DIRTY.
Powodzenie: `GATEWAY_CUTOVER_PASS`.

Jeżeli po próbie wdrożenia Gateway nie przejdzie smoke,
skrypt automatycznie podejmuje rollback: usuwa TYLKO własny
drop-in, daemon-reload, start starego Gateway i kontrola smoke.
W raporcie znajdzie się `OLD_GATEWAY_RESTORED` albo jawny błąd.
Nie usuwa DIRTY, nie resetuje GPU, nie instaluje nowego schedulera.

## Rollback operatora
W zwykłym terminalu:
```bash
sudo python3 /srv/ai-data/evaluation/rm-engine-hardware-accept-20261020/tools/deploy_rm_gateway_backport_v1.py --rollback
```
Zachowuje stary Stage O i identyfikatory systemd; cofa tylko override.
Przy aktywnej kolejce lub markerze DIRTY przerywa zamiast wymuszać
nowy handoff. Po poprawnym rollbacku raport
`OLD_GATEWAY_ROLLBACK_PASS`.
Root-owned overlay może pozostać jako nieaktywny artefakt audytowy.

## Ograniczenia
Pozytywna walidacja adapterów nie dowodzi fizycznej globalnej
wyłączności GPU. `GPU_REUSE_SAFE=NOT_VERIFIED`,
`N1_REAL_GPU_GRANT=NOT_ADMITTED`.
Vision zarejestrowane, ale wykonywanie zablokowane.
Brak generowania obrazu przez ComfyUI: test obejmował rzeczywistą
komunikację, inicjalizację ROCm, media lease i zwolnienie allocator,
a nie inferencję modelu graficznego.

Wdrożenie jest zawężone do Gateway. Nie modyfikuje globalnego
release Stage O; udokumentowano jawny, odwracalny overlay
źródeł Gateway. Po cutover wymagany kolejny odczyt stanu realnych
usług i kodu z /status.
