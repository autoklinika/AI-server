# Magazyn V1 — drugi YubiKey 5C i niezależne odzyskiwanie AES

Data: 29.10.2026.
Stan: ZAPASOWY YUBIKEY WYKRYTY; PRZYGOTOWANIE PIV CZEKA NA LOKALNY PIN/PUK.

## Weryfikacja środowiska

- Jeden podłączony YubiKey 5C, odrębny od pierwszego klucza Stage K. Brak recipienta age na nowym urządzeniu.
- Slot 0x82 (RETIRED1) jest pusty, a PIN, PUK i Management Key pozostają fabryczne.
- Narzędzia: YubiKey Manager 5.8.0, age 1.2.1, age-plugin-yubikey 0.5.1.
- Produkcyjna baza Magazynu pozostaje integralna, lokalny klucz AES ma 32 bajty i uprawnienia 0600.
- Pierwszy ciphertext na GlobalNAS magazyn-v1-aes256-key-yubikey.age istnieje i NIE ZOSTAŁ nadpisany.
- Produkcyjne WebGUI i Telegram pozostają aktywne. HTTPS TLS działa.

## Krok 1 — interaktywny terminal SSH

Podłącz tylko nowy YubiKey i uruchom jako użytkownik harrypotter, bez sudo:

    bash /srv/ai-data/magazyn-v1/config/second_yubikey_prepare.sh --prepare

Skrypt odróżnia drugą fizyczną tożsamość od pierwszego YubiKeya, nie nadpisuje istniejących kluczy PIV i nie resetuje PIV. Pyta o zmianę domyślnego PIN-u, PUK-u i generuje losowy PIN-protected Management Key. Wybierz 8-cyfrowy PIN i OSOBNY 8-cyfrowy PUK; PUK zapisz poza serwerem. Nowych sekretów NIE wpisuj w ChatGPT ani do argumentów poleceń. Przy błędnym PIN przerwij od razu, bez kilku prób.

Następnie skrypt tworzy nowy, niewyeksportowalny ECC P-256 w slocie PIV 0x82 (age-plugin-yubikey --slot 1), z PIN policy ONCE i touch policy ALWAYS. Tożsamość i recipient zapisywane są prywatnie (0600), poza repozytorium.

## Krok 2 — zaszyfrowanie TEGO SAMEGO AES również dla drugiego YubiKeya

Po pozytywnym kroku 1 asystent może wykonać:

    python3 /srv/ai-data/magazyn-v1/config/second_yubikey_seal.py --check
    python3 /srv/ai-data/magazyn-v1/config/second_yubikey_seal.py --seal

Powstaje osobny ciphertext Magazyn/recovery/magazyn-v1-aes256-key-yubikey-spare.age na GlobalNAS. Pierwszy ciphertext, produkcyjny klucz AES i wszystkie wcześniejsze archiwa .mgzb pozostają niezmienione.

## Krok 3 — interaktywny fizyczny test odzyskania produkcji w RAM

    bash /srv/ai-data/magazyn-v1/config/second_yubikey_drill.sh --check
    bash /srv/ai-data/magazyn-v1/config/second_yubikey_drill.sh --run

Wymaga lokalnego terminala SSH oraz poprawnego PIN-u i dotknięcia drugiego YubiKeya. Skrypt odszyfrowuje AES do tmpfs /dev/shm, porównuje z kluczem produkcyjnym, sprawdza realny backup GlobalNAS i odtwarza kopię bazy wyłącznie w RAM. Skrypt nie nadpisuje bazy ani nie modyfikuje usług, tworzy jedynie prywatny raport wyników po PASS.

## Pozostały formalny etap

Drugi YubiKey jest tylko wykryty; fizyczna konfiguracja i odzyskanie czekają na test użytkownika. Nie należy jeszcze nazywać dual-key recovery PASS. Formalna bramka magazyn.release_gate w istniejącej wersji zakłada odrzuconą ścieżkę pendrive/age X25519 i będzie wymagać przystosowania do dwóch fizycznych YubiKeyów po przejściu testu.

Wszystkie skrypty są przygotowane w lokalnym katalogu produkcji /srv/ai-data/magazyn-v1/config i można je wersjonować w repozytorium bez PIN, PUK, AES i identyfikatorów urządzenia.

Dokumentacja producenta:
https://developers.yubico.com/PIV/Guides/Device_setup.html
https://docs.yubico.com/software/yubikey/tools/ykman/PIV_Commands.html
https://github.com/str4d/age-plugin-yubikey
