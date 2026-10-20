# RADIO — naprawa odrzucenia właściwości transient systemd

Data: 20.10.2026. Dotyczy próby operatora z 08:50:30 UTC, po udanym `prelaunch_recovery=PASS`. PR #174; baza tej poprawki `c110835`.

## Potwierdzona przyczyna

Zainstalowany interfejs transient `systemd-run --property=RestrictAddressFamilies=none` odrzuca żądanie: `Failed to set unit properties: Invalid argument`. Odtworzono to rzeczywistą komendą w menedżerze użytkownika, z programem CPU i bez dostępu do GPU. Dokumentacja systemd.exec na hoście opisuje `none` dla plików jednostek; interfejs transient na tym hoście tej wartości nie przyjmuje.

Nowa konfiguracja używa `AF_UNIX`, zachowując `PrivateNetwork=yes`, pozostałe ograniczenia i zamkniętą politykę urządzeń. Rzeczywisty test CPU potwierdził naturalne zakończenie 0, dozwolone gniazdo AF_UNIX i odmowę AF_INET/AF_INET6. Pełna konfiguracja User/Group oraz przestrzeni nazw wymaga root: próba całej konfiguracji w menedżerze użytkownika poprawnie przeszła parsowanie, ale zakończyła się 217/USER z powodu braku uprawnień. Nie zaliczono jej jako pełnego testu konfiguracji.

Supervisor zachowuje teraz ograniczony długością stderr błędów stałych poleceń administracyjnych. Argumenty żądań/lease nie są dołączane do komunikatu.

## Test CPU przed kolejnym pilotem

Instalator przed archiwizacją ownership lub globalnej blokady uruchamia prawdziwą, osobną usługę CPU jako ai-vision UID 994, z tym samym interpreterem i dokładnie tymi samymi właściwościami sandboxa co worker. Sprawdza UID, sys.prefix, zapis do katalogu sesji, odczyt przypiętych wag i obrazu, dostępność uprawnień do urządzeń oraz odmowę IPv4/IPv6. Nie importuje Torch, nie otwiera urządzeń GPU i nie wykonuje inferencji. Zatrzymuje wyłącznie własną unikatową jednostkę testową. Wynik wymagany: `worker_config_cpu_probe=PASS`.

Ten uprzywilejowany test nie został jeszcze wykonany. Przy jego błędzie instalator zachowuje poprzednie dowody i blokadę; nie przechodzi do pilota GPU.

## Wznowienie dokładnie tej odrzuconej próby

Opcja `--resume-launch-rejected` wymaga root i interaktywnego terminala. Przed jakąkolwiek archiwizacją weryfikuje:

- Root-owned pakiet SHA256 `1a527a432f3181de0a5da60bfe11bd9a4d9eb7d7e1d11667ef3038368d51ae37`, wszystkie jego pliki i dokładną treść zatrzymanej jednostki wykonawcy.
- Raport operatora i LAST_ERROR zgodne z tą konkretną awarią `system command failed: systemd-run`.
- Jedną sesję zgodną z ownership, bieżący boot, poprawne lease/use/job, pusty katalog data i brak jakichkolwiek plików kontroli workera.
- Brak jednostek ai-radio, LoadState=not-found dla wskazanego workera, brak jego wpisów journal w bieżącym boot oraz brak procesów UID 994.
- Pusty i zablokowany Gateway, bezczynne Ollama/ComfyUI, dokładny globalny marker, brak niezależnych markerów i obcych właścicieli GPU według rootowego kolektora FD/KFD; brak wykrytych błędów sterownika od awarii.

Po udanym teście CPU te warunki są ponownie sprawdzane. Ownership, LAST_ERROR oraz pusty katalog sesji są przenoszone do `/var/lib/ai-platform-radio/launch-rejection-recovery/` wraz z dowodami; globalna blokada wciąż obowiązuje. Następnie instalowany jest nowy pakiet, a znany globalny marker jest archiwizowany po powtórnej kontroli hosta. Przy nieznanym stanie procedura odmawia wznowienia. Nie resetuje sterownika, nie kasuje dowodów i nie zmienia zasad N1. Nie jest to ogólny mechanizm odzyskiwania po wykonanej inferencji.

## Walidacja i ograniczenia

- 842 testy CPU PASS, 25 modułów, 6,77 s; jedno dotychczasowe ostrzeżenie Starlette/httpx. Log: `VISION_RADIO_SYSTEMD_FIX_TESTS_2026-10-20.log`.
- Rzeczywisty test menedżera użytkownika: `REAL_CPU_AF_UNIX_ALLOWED_INET_INET6_DENIED=PASS`; log: `VISION_RADIO_SYSTEMD_CPU_PROBE_2026-10-20.log`.
- Manifest 177 plików: `SOURCE_SHA256_PASS`; SHA256 `a44297bf997757991e8f53a8f70ce7a7031219b5d9155fc6b71fb334a2cbf032`.
- Stan GPU nie został zweryfikowany nową inferencją. Produkcyjne Vision nie jest włączone. GPU_REUSE_SAFE=NOT_VERIFIED; N1=NOT_ADMITTED; ComfyUI image generation=NOT_TESTED.

## Komenda operatora na AI Platform

```bash
sudo /usr/bin/python3 -I /srv/ai-data/evaluation/vision-engine-integration-20261020/tools/install_vision_radio_pilot.py --pilot --resume-launch-rejected --manifest-sha256 a44297bf997757991e8f53a8f70ce7a7031219b5d9155fc6b71fb334a2cbf032
```

Wymagane etapy: `worker_config_cpu_probe=PASS`, `launch_rejection_recovery=PASS`, następnie wynik rzeczywistego pilota i `prior_gateway_restored=true`. Samo przejście testu CPU nie potwierdza GPU ani wdrożenia produkcyjnego. Narzędzie zdalne blokuje sudo, dlatego ten etap wymaga terminala operatora.
