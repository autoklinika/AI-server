# Autostart ComfyUI i kolejność startu — przygotowane do instalacji

Status przy przygotowaniu: **READY_FOR_OPERATOR**, bez zmiany działającej konfiguracji. Aktualizacja: instalacja i odbiór po restarcie zostały następnie zakończone **PASS** — [raport końcowy](COMFYUI_POST_REBOOT_ACCEPTANCE_2026-10-20_PL.md).

Po restarcie o 17:00:45 CEST podstawowe usługi wystartowały poprawnie. Qwen 27B przeszedł rzeczywisty test GPU o 17:13 CEST, po czym model wyładowano, a RM wrócił do IDLE. Telegram, Discord i API Hermes są połączone. Bieżąca odczytowa kontrola Stage K była PASS; ostatnia kopia zakończyła się o 14:21 CEST.

ComfyUI pozostało wyłączone po restarcie zgodnie z wcześniejszym odbiorem autostartu. O 17:22:11 CEST żądanie `telegram-foto` zajęło rezerwację `job_45783f09b4d141bc93bf9833f4a19896`; próba przejścia do nieuruchomionego ComfyUI zatrzymała RM w stanie BLOCKED. Zatrzymana rezerwacja i marker zostały zachowane. Nie ma jednostki RADIO ani widocznych procesów generowania obrazu/wideo. Ollama ma jednak ponownie załadowany Qwen 27B; kontrola root przed uruchomieniem ComfyUI musi go wyładować i potwierdzić brak właścicieli urządzeń GPU.

## Zatwierdzona konfiguracja

Użytkownik zatwierdził przywrócenie autostartu i kolejności startu przy zachowaniu jednego istniejącego RM. Pakiet obejmuje trzy pliki drop-in i jeden krótki program sprawdzający gotowość:

1. ComfyUI wymaga zamontowanego katalogu wyjściowego. `ExecStartPost` czeka do 120 s na istniejące lokalne API residency: schemat 1, zero modeli/zadań i brak oczekującego cleanup. Systemd traktuje jednostkę jako uruchamianą do zakończenia tego sprawdzenia.
2. Gateway ma `Requires=comfyui.service` i `After=comfyui.service`. Zachowane są jego zależności od Ollamy i nadzorcy RADIO. Gdy start ComfyUI się nie powiedzie, Gateway nie otwiera wejścia.
3. Hermes w swoim dotychczasowym menedżerze użytkownika czeka w `ExecStartPre` do 180 s na zdrowy Gateway. Nie tworzymy zależności między jednostkami różnych menedżerów systemd.

Preload Ollamy i timer analizy pozostają disabled. Nie zmieniamy źródeł Gateway, limitu 64 MiB, konfiguracji modeli, urządzeń ani uprawnień GPU. Program gotowości nie uruchamia inferencji i nie usuwa markerów.

## Instalacja i odzyskanie

`deploy/comfyui-boot/install.py` sprawdza manifest pakietu i wszystkie 239 plików odebranego produkcyjnego overlay. Jednorazowa instalacja jest ograniczona do zapisanej blokady, konkretnego żądania i bieżącego boot ID. Inne zadanie, nowy boot, aktywny agent lub oczekująca praca powodują odmowę.

Kolejność jest zgodna z istniejącym `GPU_RESIDENCY_RECOVERY.md`: zapis statusu/konfiguracji/markera → zatrzymanie Hermes i Gateway → sprawdzenie końca workerów → wyładowanie Ollamy → rootowa kontrola fuser i KFD → instalacja drop-inów i autostartu → start ComfyUI → sprzątanie przez istniejącą, zweryfikowaną klasę GPUResidency → kontrola jądra i workerów → usunięcie żywego markera z zachowaniem archiwum → start Gateway i kontrola pustego RM → start Hermes.

Nie odtwarzamy automatycznie nieudanego żądania zdjęcia. Żadna procedura boot nie usuwa markerów awarii. Nie restartujemy Ollamy, sterownika ani hosta. Po błędzie odzyskiwania wejście pozostaje zamknięte; zachowane dowody wymagają sprawdzenia przed ponowieniem.

Dowody instalacji: `/var/lib/ai-platform/comfyui-boot`. Niezmienny helper jest instalowany w `/opt/ai-platform/comfyui-boot/<manifest-prefix>`. Rootowa konfiguracja wymaga terminala operatora: zdalny `systemctl --no-ask-password start comfyui.service` zwrócił odmowę uwierzytelnienia.

## Weryfikacja przed instalacją

- 117 testów CPU: readiness i odmowy odzyskania oraz regresje GPUResidency, engine lifecycle, Vision i Resource Leases — PASS.
- Odczytowa weryfikacja pakietu i zainstalowanego produkcyjnego overlay — PASS.
- `systemd-analyze verify` dla dokładnych jednostek systemowych z przygotowanymi drop-inami — exit 0.
- `systemd-analyze --user verify` dla dokładnej jednostki Hermes z przygotowanym drop-inem — exit 0.
- Uprzywilejowana instalacja, ponowny cykl GPU i odbiór po restarcie — **PENDING**. To nie jest raport wdrożenia.

## Wycofanie konfiguracji

Zapisane przed instalacją pliki zawierają pełną poprzednią konfigurację. Wycofanie samych trzech dodatków oznacza usunięcie `20-ai-platform-ready.conf` z ComfyUI, `98-comfyui-ready.conf` z Gateway oraz `50-platform-ready.conf` z Hermes, ponowne wyłączenie autostartu ComfyUI i przeładowanie obu menedżerów systemd. Nie zatrzymuje to działającej sesji ComfyUI. Przy nieudanym cleanup wycofanie konfiguracji nie uprawnia do wznowienia pracy ani usunięcia markera; nadal obowiązuje istniejący runbook recovery.

## Próba operatora 17:37 i poprawka kontroli zatrzymania

Pierwsza instalacja zatrzymała Hermes o 17:37:41 CEST. Główny proces wyszedł z kodem 1 po SIGTERM; `ExecStopPost` zakończył się poprawnie. Systemd pokazał `ActiveState=failed`, `MainPID=0`, `ControlPID=0` i pusty `ControlGroup`. Instalator błędnie wymagał wyłącznie `ActiveState=inactive`, przez co zwrócił `Hermes did not stop`, choć procesy były już zakończone.

Odczyt hosta potwierdził: Gateway nadal ma pierwotny PID 3342 i tę samą zablokowaną rezerwację; ComfyUI pozostaje inactive/disabled; żaden z trzech nowych drop-inów nie istnieje. Marker i rootowe dowody pierwszej próby pozostały zachowane. Plik statusu aplikacji Hermes zawiera stary PID i stan running, dlatego nie jest używany jako dowód żywego procesu.

Poprawiona kontrola akceptuje inactive lub failed wyłącznie przy obu PID-ach równych 0 i pustej grupie procesów. Nie zmienia obsługi kodów wyjścia samego Hermes. Wznowienie zachowuje oryginalny komplet pięciu plików dowodowych i wymaga identycznej rezerwacji, markera oraz konfiguracji usług. Inny stan lub ślad dalszej instalacji powoduje odmowę. Nie kasujemy ani nie zastępujemy katalogu dowodów.

Regresja po poprawce: **124 testy PASS**. Dodatkowy odczyt rzeczywistych właściwości zatrzymanej usługi potwierdził PASS nowej kontroli. Pakiet i wszystkie źródła produkcyjnego overlay nadal przechodzą kontrolę SHA256. Rootowe wznowienie instalacji oraz odbiór GPU i po restarcie pozostają PENDING.
