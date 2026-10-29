# Magazyn V1 — naprawa częściowo utworzonego zapasowego YubiKeya

Data: 29.10.2026. Produkcja Magazynu i Stage K pozostały nietknięte.

## Co się stało

Na drugim YubiKey 5C poprawnie zmieniono PIN, PUK i management key na losowy TDES chroniony PIN-em. age-plugin-yubikey 0.5.1 rozpoczął generowanie nowej tożsamości, zapisał w slocie PIV 0x82 klucz ECC P-256, ale podczas generowania certyfikatu X.509 po komunikacie o dotknięciu urządzenia zwrócił authentication error.

Wyniki kontroli read-only wykonanych na rzeczywistym YubiKeyu:
- PIV slot 0x82: istniejący klucz ECCP256, Origin GENERATED, PIN policy ONCE, Touch policy ALWAYS.
- Management key: TDES, chroniony PIN-em.
- PIV PIN oraz PUK: zmienione, nie fabryczne.
- PIN 3/3 prób. Nie wystąpiła blokada PIN-u.
- Certyfikat w 0x82 nie istnieje; ykman piv certificates export 82 zwrócił brak certyfikatu.
- Klucz publiczny w 0x82: eksport read-only przez ykman piv keys export i walidacja SECP256R1 (prime256v1) PASS.
- age-plugin-yubikey --list nie zwraca nowego recipienta, gdy certyfikat jest nieobecny.
- Katalog spare nie zawiera identity ani recipient; nie było powtórnego nadpisania slotu.
- Proces scdaemon nie został wykryty w chwili diagnostyki. Nie rozstrzygnięto, czy wcześniejszy błąd wynikał z czasowego konfliktu smartcard/scdaemon, obsługi dotyku lub przerwania sesji PIN. Nie zgadujemy przyczyny bez dodatkowego logu.
- Pierwszy YubiKey, produkcyjny AES, GlobalNAS, Magazyn WebGUI i Telegram pozostają bez zmian.

## Naprawa niedestrukcyjna

Nie uruchamiać ponownie pierwotnego second_yubikey_prepare.sh --prepare, nie używać --force i nie resetować PIV. Slot 0x82 jest zajęty.

Przygotowano odrębny skrypt:
 /srv/ai-data/magazyn-v1/config/second_yubikey_complete_certificate.py

Uruchom w terminalu SSH użytkownika harrypotter z tylko drugim YubiKeyem:

    /srv/ai-data/magazyn-v1/runtime/py314/bin/python /srv/ai-data/magazyn-v1/config/second_yubikey_complete_certificate.py --run

Skrypt kontroluje PIN retries, rodzaj i właściwości istniejącego klucza i brak certyfikatu. Nie wywołuje keygen, delete ani PIV reset. Eksportuje tylko klucz PUBLICZNY do prywatnego katalogu /dev/shm i przy użyciu ykman piv certificates generate tworzy certyfikat samopodpisany dla już istniejącego klucza w slocie 82. Pytania o PIN i dotyk obsługiwane są wyłącznie w terminalu użytkownika, nie w ChatGPT.

Po wydaniu certyfikatu weryfikuje zgodność jego klucza publicznego z kluczem PIV oraz podpis certyfikatu. Ustawia subject z O=age-plugin-yubikey i wersją OU=0.5.1 zgodnie z konwencją pluginu. Następnie odczytuje recipient z age-plugin-yubikey --list i identity z age-plugin-yubikey --identity --slot 1. Zapisuje je jako pliki 0600 wyłącznie po sukcesie.

Preflight skryptu read-only (plus tymczasowy publiczny plik w RAM) wykonał się poprawnie: SECOND_YUBIKEY_CERT_REPAIR_PREFLIGHT=PASS. Fizyczne generowanie certyfikatu jeszcze nie zostało wykonane. Jeśli certyfikat okaże się niekompatybilny z pluginem, skrypt przerwie i NIE będzie kasował klucza.

Dopiero po otrzymaniu niezależnego recipienta drugi etap pozwoli opakować istniejący AES na GlobalNAS (second_yubikey_seal.py), a po tym właściciel wykona rzeczywisty decrypt/restore z drugiego YubiKeya (second_yubikey_drill.sh). Do tego czasu formalne offsite_recovery jest BLOCKED.

Dokumentacja źródłowa:
https://github.com/str4d/age-plugin-yubikey/issues/206
https://github.com/str4d/age-plugin-yubikey
https://docs.yubico.com/software/yubikey/tools/ykman/PIV_Commands.html
