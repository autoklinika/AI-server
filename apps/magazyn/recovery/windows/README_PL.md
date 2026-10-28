# Magazyn V1 — szyfrowany pendrive odzyskiwania (Windows)

Data: 2026-10-28. Repo: feature/magazyn-v1-dev-20261026.

**Cel:** trzecia, niezależna metoda odzyskania danych Magazynu, bez zmian w obecnym YubiKey 5C. Drugi zamówiony YubiKey 5C zostanie dodany jako osobny odbiorca później.

## Wymagania

- Pendrive 16–32 GB (lub większy), najlepiej nowy.
- Windows 10/11 Pro, Enterprise lub Education z BitLocker To Go.
- Instalacja age: winget install --id FiloSottile.age --exact
- Python 3.11+ i biblioteka cryptography do testu odzyskiwania (zainstaluj ją na Windows teraz, zanim wystąpi awaria).
- Cztery narzędzia z tego folderu: prepare_usb.ps1, sync_offline_copy.ps1, test_recovery.ps1, portable_restore.py.

## 1. Zaszyfruj fizyczny pendrive na Windows

1. Podłącz USB; wcześniej zachowaj w innym miejscu ważne pliki, które już na nim są.
2. Otwórz **Zarządzaj funkcją BitLocker** -> **Wymienne dyski danych (BitLocker To Go)**.
3. Upewnij się, że wybierasz pendrive, a NIE dysk systemowy.
4. Włącz BitLocker, zdefiniuj silne unikalne hasło.
5. **Klucz odzyskiwania BitLocker** zapisz lub wydrukuj w osobnym bezpiecznym miejscu: NIE na tym pendrivie, nie tylko na serwerze/NAS i nie w czacie.
6. Wybierz szyfrowanie **całego dysku**, tryb zgodności dla nośników wymiennych. Poczekaj na 100% zakończenia.
7. Wyłącz automatyczne odblokowywanie. Zanotuj literę USB, np. E:.

Nie ma tutaj żadnego skryptu formatującego dysk ani automatycznie włączającego BitLocker. Jeżeli Windows to Home, przygotuj pendrive na komputerze z Pro/Enterprise/Education. Nie uruchamiaj generowania identity na nieszyfrowanym nośniku.

## 2. Utwórz age X25519 na zaszyfrowanym USB

W PowerShell (w katalogu z tym pakietem):

    winget install --id FiloSottile.age --exact

Po instalacji otwórz nową sesję PowerShell i uruchom:

    .\prepare_usb.ps1 -DriveLetter E

Skrypt sprawdzi, czy E: jest prawdziwym wymiennym, w pełni zaszyfrowanym i chronionym pendrivem BitLocker To Go. Jeśli nie, odmówi pracy. Prywatny klucz powstaje bezpośrednio na pendrivie (nigdy na dysku serwera).

Struktura USB:

    E:\MAGAZYN_RECOVERY\
      private\identity.txt       TAJNE, pozostaje tylko na zaszyfrowanym USB
      public\recipient.txt       publiczny odbiorca age1...
      backups\                   zaszyfrowane archiwa .mgzb
      recovery\                  zaszyfrowany .age zawierający AES
      tools\portable_restore.py  program do offline DR
      tools\age.exe              uruchamianie age bez instalacji na nowym PC
      tools\*.ps1                narzędzia i instrukcje
      recovered\                 opcjonalna jawna SQLite po próbie restore

Wysyłasz do serwera / ChatGPT WYŁĄCZNIE publiczną wartość age1... z recipient.txt. Nigdy nie wysyłaj private/identity.txt, hasła USB ani klucza odzyskiwania BitLocker.

## 3. Serwer szyfruje istniejący AES do klucza publicznego

Po otrzymaniu publicznego recipienta użyjemy istniejącego, już przetestowanego modułu magazyn.offline_escrow. Powstanie nowy plik na NAS:

    /mnt/AI_Platform/Magazyn/recovery/magazyn-v1-aes256-key-offline.age

To jest szyfrowana kopia istniejącego klucza AES (nie jawny AES). Nie nadpisuje istniejącej kopii dla YubiKeya:

    magazyn-v1-aes256-key-yubikey.age

Etap nie został jeszcze wykonany na prawdziwym AES; do jego uruchomienia potrzebny jest recipient z fizycznego pendrive'a.

## 4. Skopiuj kompletne zaszyfrowane dane z GlobalNAS na USB

Z Windows mającego dostęp do udziału GlobalNAS:

    .\sync_offline_copy.ps1 -DriveLetter E

Skrypt skopiuje tylko zaszyfrowany .age i najnowszy .mgzb z GlobalNAS, porówna sumy SHA-256, nie nadpisze innych plików. Nie przenosi jawnego AES ani jawnej bazy. Pendrive musi mieć także co najmniej jedną zaszyfrowaną kopię .mgzb; inaczej nadal zależy od dostępności NAS.

## 5. Rzeczywisty test bez serwera i NAS

Na komputerze Windows z Pythonem i age, po zainstalowaniu biblioteki:

    py -3 -m pip install cryptography
    .\test_recovery.ps1 -DriveLetter E

Jeżeli chcesz przygotować komputer na awarię Internetu, po zaszyfrowaniu USB
zachowaj na nim również instalator Pythona i lokalne paczki cryptography:

    py -3 -m pip download --dest E:\MAGAZYN_RECOVERY\tools\wheels cryptography

Pakiety muszą być zgodne z wersją Pythona i architekturą komputera odzyskującego.

Odszyfrowanie klucza AES i archiwum wykonuje się w RAM; skrypt sprawdza integralność SQLite, klucze obce, tabele i SHA-256 dokumentacji. W domyślnym trybie nie powstaje plik jawnego AES ani jawnej SQLite.

Dodatkowy test zapisu pełnej odzyskanej bazy na szyfrowanym USB:

    .\test_recovery.ps1 -DriveLetter E -RestoreToUsb

Uwaga: nowy recovered/*.sqlite3 jest jawną bazą, gdy USB jest odblokowany; nadal chroni go szyfrowanie całego nośnika BitLocker. Usuń ten plik po sprawdzeniu, jeżeli nie jest potrzebny. Nigdy nie umieszczaj jawnej bazy na nieszyfrowanym dysku systemowym.

Najlepszy odbiór: odłącz sieć Windows i NAS, uruchom test ponownie, potwierdź PASS. Dopiero wtedy oznaczamy niezależny recovery jako gotowy.

## Utrzymanie i niezależność

- Aktualizuj zaszyfrowany .mgzb na USB co najmniej raz w miesiącu oraz po ważnych zmianach magazynowych.
- Pendrive przechowuj odłączony, fizycznie poza serwerem i GlobalNAS, najlepiej w innej lokalizacji.
- Hasło BitLocker i recovery password przechowuj osobno. Rozważ drugą zaszyfrowaną kopię USB w innym miejscu.
- Po dostawie drugiego YubiKeya 5C utworzymy mu OSOBNY sprzętowy recipient i kolejną zaszyfrowaną kopię AES, bez zmiany oryginalnego YubiKeya.
- Skrypty nie tworzą nowego harmonogramu, nie dotykają usług Magazynu ani nie uruchamiają GPU.
- Windows Home nie obsługuje zarządzania BitLocker To Go tak jak Pro. W takim przypadku ustalimy wariant VeraCrypt lub użyjemy komputera z Pro.

## Status i źródła

Przygotowanie kodu i testy syntetyczne nie oznaczają fizycznego zakończenia odzyskiwania. Przy prawdziwym AES etap pozostaje PENDING do wygenerowania klucza na fizycznym USB, kopiowania danych i offline restore PASS.

Microsoft BitLocker To Go:
https://support.microsoft.com/pl-pl/windows/security/encryption/bitlocker-drive-encryption

Projekt age:
https://github.com/FiloSottile/age
