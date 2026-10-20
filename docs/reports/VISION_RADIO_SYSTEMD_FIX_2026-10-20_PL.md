# RADIO — naprawa odrzucenia właściwości transient systemd

Data: 20.10.2026. Dotyczy próby operatora z 08:50:30 UTC, po udanym `prelaunch_recovery=PASS`. PR #174; baza tej poprawki `c110835`.

## Potwierdzona przyczyna

Zainstalowany interfejs transient `systemd-run --property=RestrictAddressFamilies=none` odrzuca żądanie: `Failed to set unit properties: Invalid argument`. Odtworzono to rzeczywistą komendą w menedżerze użytkownika, z programem CPU i bez dostępu do GPU. Dokumentacja systemd.exec na hoście opisuje `none` dla plików jednostek; interfejs transient na tym hoście tej wartości nie przyjmuje.

Nowa konfiguracja używa `AF_UNIX`, zachowując `PrivateNetwork=yes`, pozostałe ograniczenia i zamkniętą politykę urządzeń. Rzeczywisty test CPU potwierdził naturalne zakończenie 0, dozwolone gniazdo AF_UNIX i odmowę AF_INET/AF_INET6. Pełna konfiguracja User/Group oraz przestrzeni nazw wymaga root: próba całej konfiguracji w menedżerze użytkownika poprawnie przeszła parsowanie, ale zakończyła się 217/USER z powodu braku uprawnień. Nie zaliczono jej jako pełnego testu konfiguracji.

Supervisor zachowuje teraz ograniczony długością stderr błędów stałych poleceń administracyjnych. Argumenty żądań/lease nie są dołączane do komunikatu.

## Uproszczenie kontroli UID po odmowie z 11:05 CEST

Kontrola „dowolny proces UID 994 oznacza pracujący model” była błędna. Na hoście działa dziewięć zwykłych procesów sesji ai-vision, uruchomionych 17 października (systemd, sd-pam, D-Bus, PipeWire, WirePlumber i portale XDG). Próba operatora została zatrzymana w preflight, przed testem CPU i archiwizacją blokady.

Usunięto skan wszystkich procesów według UID. Nie dodano list wyjątków dla usług sesji. Tożsamość workera jest już określona przez przypięte ownership, konkretną jednostkę systemd, jej cgroup, journal i pliki sesji. Obowiązkowa, niezależna kontrola root FD/KFD nadal odrzuca każdego obcego właściciela GPU, także UID 994. Procedura zachowuje globalną blokadę przy niekompletnych dowodach. Istniejący RM i nadzorca pozostają jedyną ścieżką wykonywania zadania.

Na hoście odczytowo potwierdzono brak widocznej jednostki RADIO; KFD wskazuje wyłącznie dotychczasowy ComfyUI PID 267058. Pełna kontrola cross-UID FD wymaga roota i pozostaje obowiązkowym etapem komendy operatora. Testy poprawki: `VISION_RADIO_BACKGROUND_FIX_TESTS_2026-10-20.log` (844 PASS, 25 modułów). Testy obejmują brak fałszywej blokady od procesu CPU, odmowę dla pozostawionej cgroup workera i zachowanie odmowy po wykryciu obcego właściciela GPU.

## Test CPU przed kolejnym pilotem

Instalator przed archiwizacją ownership lub globalnej blokady uruchamia prawdziwą, osobną usługę CPU jako ai-vision UID 994, z tym samym interpreterem i dokładnie tymi samymi właściwościami sandboxa co worker. Sprawdza UID, sys.prefix, zapis do katalogu sesji, odczyt przypiętych wag i obrazu, dostępność uprawnień do urządzeń oraz odmowę IPv4/IPv6. Nie importuje Torch, nie otwiera urządzeń GPU i nie wykonuje inferencji. Zatrzymuje wyłącznie własną unikatową jednostkę testową. Wynik wymagany: `worker_config_cpu_probe=PASS`.

Ten uprzywilejowany test nie został jeszcze wykonany. Przy jego błędzie instalator zachowuje poprzednie dowody i blokadę; nie przechodzi do pilota GPU.

## Wznowienie dokładnie tej odrzuconej próby

Opcja `--resume-launch-rejected` wymaga root i interaktywnego terminala. Przed jakąkolwiek archiwizacją weryfikuje:

- Root-owned pakiet SHA256 `1a527a432f3181de0a5da60bfe11bd9a4d9eb7d7e1d11667ef3038368d51ae37`, wszystkie jego pliki i dokładną treść zatrzymanej jednostki wykonawcy.
- Raport operatora i LAST_ERROR zgodne z tą konkretną awarią `system command failed: systemd-run`.
- Jedną sesję zgodną z ownership, bieżący boot, poprawne lease/use/job, pusty katalog data i brak jakichkolwiek plików kontroli workera.
- Brak jednostek ai-radio, LoadState=not-found dla wskazanego workera, brak jego wpisów journal w bieżącym boot oraz brak cgroup tej jednostki.
- Pusty i zablokowany Gateway, bezczynne Ollama/ComfyUI, dokładny globalny marker, brak niezależnych markerów i obcych właścicieli GPU według rootowego kolektora FD/KFD; brak wykrytych błędów sterownika od awarii.

Po udanym teście CPU te warunki są ponownie sprawdzane. Ownership, LAST_ERROR oraz pusty katalog sesji są przenoszone do `/var/lib/ai-platform-radio/launch-rejection-recovery/` wraz z dowodami; globalna blokada wciąż obowiązuje. Następnie instalowany jest nowy pakiet, a znany globalny marker jest archiwizowany po powtórnej kontroli hosta. Przy nieznanym stanie procedura odmawia wznowienia. Nie resetuje sterownika, nie kasuje dowodów i nie zmienia zasad N1. Nie jest to ogólny mechanizm odzyskiwania po wykonanej inferencji.

## Walidacja i ograniczenia

- 842 testy CPU PASS, 25 modułów, 6,77 s; jedno dotychczasowe ostrzeżenie Starlette/httpx. Log: `VISION_RADIO_SYSTEMD_FIX_TESTS_2026-10-20.log`.
- Rzeczywisty test menedżera użytkownika: `REAL_CPU_AF_UNIX_ALLOWED_INET_INET6_DENIED=PASS`; log: `VISION_RADIO_SYSTEMD_CPU_PROBE_2026-10-20.log`.
- Manifest 177 plików: `SOURCE_SHA256_PASS`; SHA256 `7cec662df1089831571ef0184b2e256a56579100cba8e478bfa310fb2df2b0fe`.
- Stan GPU nie został zweryfikowany nową inferencją. Produkcyjne Vision nie jest włączone. GPU_REUSE_SAFE=NOT_VERIFIED; N1=NOT_ADMITTED; ComfyUI image generation=NOT_TESTED.

## Interpreter i pozostałość testu CPU — aktualizacja 11:18 CEST

Jednostka blokująca kolejne wznowienie to **ai-radio-config-641d732a3fc69a81c17223d715fbbf90.service**, czyli własny test CPU, nie worker RADIO. Dziennik z 11:12:59 potwierdza `203/EXEC`, `MainPID=0` i pusty ControlGroup. Interpreter nie został uruchomiony; test nie otwierał GPU. Jednostka pozostała jako failed mimo stop, co blokowało następne preflight. Instalator po zatrzymaniu własnego testu CPU czyści teraz również jego status failed; journal pozostaje zachowany.

Przyczyną 203/EXEC był link venv `bin/python3.11` prowadzący przez `/home/harrypotter/.local/bin/python3.11`, a następnie alias `cpython-3.11-linux-x86_64-gnu`. ProtectHome=tmpfs ukrywa te aliasy, a BindReadOnlyPaths udostępnia tylko właściwy katalog Pythona 3.11.16. W środowisku Vision zmieniono wyłącznie ten link na bezpośredni cel `/home/harrypotter/.local/share/uv/python/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11`. Przed i po zmianie resolve wskazuje ten sam plik wykonywalny; sys.prefix i sys.base_prefix pozostały prawidłowe. Pakiety i model nie były zmieniane. Instalator sprawdza teraz bezpośredni cel linku przed uruchomieniem usługi.

Rzeczywista usługa CPU w menedżerze użytkownika, z PrivateUsers=yes, ProtectHome=tmpfs, ProtectSystem=strict i tym samym BindReadOnlyPaths, uruchomiła interpreter i zakończyła się naturalnie statusem 0: `CANONICAL_VENV_WITH_HOME_HIDDEN=PASS`. Jest to potwierdzenie naprawy ścieżki w izolacji plików, nie test GPU ani pełny test UID 994. Pełny test CPU pod ai-vision nadal wykona komenda operatora.

**845 testów CPU PASS**, 25 modułów, 6,83 s. Log: `VISION_RADIO_RUNTIME_FIX_TESTS_2026-10-20.log`. Log rzeczywistego testu: `VISION_RADIO_CANONICAL_RUNTIME_CPU_2026-10-20.log`. Manifest 177 plików: SOURCE_SHA256_PASS.

Pierwsze polecenie poniżej czyści wyłącznie zachowany status wskazanego testu CPU. Nie zatrzymuje workerów, nie usuwa journal ani markerów GPU. Następnie uruchamiany jest dotychczasowy kontrolowany pilot.

## Komenda operatora na AI Platform

```bash
sudo systemctl reset-failed ai-radio-config-641d732a3fc69a81c17223d715fbbf90.service && \
sudo /usr/bin/python3 -I /srv/ai-data/evaluation/vision-engine-integration-20261020/tools/install_vision_radio_pilot.py --pilot --resume-launch-rejected --manifest-sha256 7cec662df1089831571ef0184b2e256a56579100cba8e478bfa310fb2df2b0fe
```

Wymagane etapy: `worker_config_cpu_probe=PASS`, `launch_rejection_recovery=PASS`, następnie wynik rzeczywistego pilota i `prior_gateway_restored=true`. Samo przejście testu CPU nie potwierdza GPU ani wdrożenia produkcyjnego. Narzędzie zdalne blokuje sudo, dlatego ten etap wymaga terminala operatora.
