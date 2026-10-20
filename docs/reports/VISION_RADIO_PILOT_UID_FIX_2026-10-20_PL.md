# RADIO pilot — naprawa UID Gateway i kontrolowane wznowienie

> Aktualizacja: odzyskanie tej próby przeszło, lecz następny pilot ujawnił odrzucenie właściwości systemd. Aktualna poprawka i komenda: [VISION_RADIO_SYSTEMD_FIX_2026-10-20_PL.md](VISION_RADIO_SYSTEMD_FIX_2026-10-20_PL.md). Poniższa komenda opisuje wcześniejszy etap.

Data: 20.10.2026. Nieudany pilotaż operatora: 10:27 CEST. Baza: `b1a82a5` / PR #174.

## Przyczyna i stan

Mój skrypt uruchamiał in-process Gateway z UID 0 operatora. Produkcyjne ComfyUI ma UID 1000 (MainPID 267058). Istniejąca funkcja `resume_stopped_managed_comfy()` wymaga zgodności UID i prawidłowo zwróciła `managed ComfyUI uid mismatch` jeszcze przed uruchomieniem RADIO. Ta kontrola nie została osłabiona.

Przyczynę odtworzono odczytowo na rzeczywistym procesie ComfyUI, z symulacją UID 0 wyłącznie w kontrolerze testowym. Nie wysyłano sygnałów do ComfyUI.

Gateway został przywrócony, lecz **pozostaje BLOCKED** zgodnie z markerem. Ollama i ComfyUI nie zgłaszają załadowanych modeli/zadań. Nie zaobserwowano nowych dopasowanych błędów AMDGPU/MES w dzienniku badanego okna. Nie ma widocznych jednostek `ai-radio-*`. Prywatny katalog stanu wykonawcy wymaga root; pełna kontrola jego braku sesji zostanie wykonana przez komendę operatora, zanim cokolwiek zostanie odblokowane.

## Poprawka

- Root jest operatorem instalacji, zamknięcia okna i nadzoru; sam testowy Gateway działa w osobnym procesie jako **harrypotter, UID/GID 1000**, z normalnymi grupami tego konta.
- Dziecko sprawdza własny UID i odmawia uruchomienia, jeżeli produkcyjny Gateway nadal działa. To sprawdzono rzeczywistym, nieuprzywilejowanym wywołaniem: `LIVE_UID1000_CHILD_GUARD=PASS`.
- Worker modelu pozostaje odseparowany jako `ai-vision` UID 994; root-owned supervisor i dotychczasowe zabezpieczenia pozostają niezmienione.
- Nie zmieniono render/video, uprawnień GPU, sterownika, produkcyjnego overlay ani zasad N1.

## Wznowienie tylko tego błędu przed startem workera

Nowa opcja `--resume-prelaunch` nie jest ogólnym usuwaniem markerów. Zadziała wyłącznie, jeśli root potwierdzi wszystkie warunki:

1. Poprzedni pakiet i jednostka są dokładnie wersją SHA256 `389beaa97b11783361ff8ec49e60dfbe15e3ca7da70d327626c4ee47eca46acf`; wszystkie pliki pakietu nadal są zgodne z root-owned manifestem. Supervisor jest zatrzymany.
2. Zachowany raport pasuje do `Vision prepare failed closed`, ma `prior_gateway_restored=true` i nie zawiera wykonanych inspekcji RADIO.
3. Nie ma żadnej sesji RADIO, jednostki workera, markera jego ownership ani błędu nadzorcy. W znanej wersji źródeł te dowody powstają przed startem workera, więc ich obecność wyklucza tę procedurę.
4. Globalny marker ma **dokładnie** treść z tej nieudanej próby. Żaden niezależny marker GPU nie jest obecny. Gateway jest zablokowany i pusty; Ollama/ComfyUI są bez modeli i pracy.
5. Rootowy kolektor FD/KFD nie widzi obcych właścicieli; dozwolony jest jedynie wcześniej zaakceptowany kontekst bezczynnego ComfyUI. Nie ma nowych wykrytych błędów sterownika od czasu próby.

Dopiero wtedy instalowana jest nowa wersja wykonawcy, stary raport i dowody trafiają do `/var/lib/ai-platform-radio/prelaunch-recovery/`, a **znany marker jest archiwizowany przez rename**, po czym poprzedni Gateway wraca do IDLE. Następnie uruchamiany jest poprawiony pilotaż. Nieznany stan zachowuje blokadę; nie wykonuje się resetu GPU.

Stary pakiet nie jest nadpisywany. Zmiana jednostki wykonawcy wymaga zgodności z przypiętą starą zawartością; nieudany start nowej jednostki przywraca jej poprzednią treść. Jest to aktualizacja wykonawcy pilota, nie wdrożenie produkcyjnej integracji.

## Walidacja

- **827 testów CPU PASS**, exit 0, 25 modułów, 6,74 s; jedno dotychczasowe ostrzeżenie Starlette/httpx.
- Testy obejmują regresję uruchamiania dziecka z UID/GID 1000, odmowę UID 0/993/994, zachowanie nieznanych markerów, odmowę dla istniejącej sesji/ownership i archiwizację dowodów zamiast ich kasowania.
- `SOURCE_SHA256_PASS`: 176 plików nowego pakietu. SHA256 manifestu: `1a527a432f3181de0a5da60bfe11bd9a4d9eb7d7e1d11667ef3038368d51ae37`.
- Brak nowego testu GPU i brak uprzywilejowanej instalacji z poziomu narzędzia zdalnego. `GPU_REUSE_SAFE=NOT_VERIFIED`, N1 `NOT_ADMITTED`.

## Jedna komenda na AI Platform

```bash
sudo /usr/bin/python3 -I /srv/ai-data/evaluation/vision-engine-integration-20261020/tools/install_vision_radio_pilot.py --pilot --resume-prelaunch --manifest-sha256 1a527a432f3181de0a5da60bfe11bd9a4d9eb7d7e1d11667ef3038368d51ae37
```

Oczekiwane etapy: `prelaunch_recovery=PASS`, następnie `result=GPU_PILOT_PASS` i `prior_gateway_restored=true`. Jeżeli dowody są niekompletne, procedura odmawia wznowienia. Przy nowej awarii pilotażu zachowuje BLOCKED. Produkcyjna integracja Vision nadal nie jest wdrażana przez tę komendę.
