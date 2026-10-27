# Magazyn V1 — odzyskiwanie AES przez istniejący YubiKey 5C

**Data:** 27.10.2026. **Środowisko:** AI Platform / Magazyn V1 DEV.
**Status:** zaszyfrowanie klucza AES przy użyciu publicznego recipienta Stage K, zapis do GlobalNAS i odczyt ciphertext — PASS. Fizyczny test odszyfrowania tego nowego pliku — NIEZWERYFIKOWANY, wymaga YubiKeya i PIN-u.

## Istniejący klucz Stage K — niezmieniony

W istniejącej konfiguracji AI Platform klucz YubiKey 5C ma PIV ECC P-256, slot 0x82 (RETIRED1), PIN policy ONCE, touch NEVER. Niewyeksportowany klucz prywatny przeszedł rzeczywisty decrypt drill Stage K dnia 25.09.2026. Obecny plik publicznych recipientów Stage K to:

    /srv/ai-data/platform/recovery/stage-k/age-recipients.txt

Zawiera jednego recipienta age-plugin-yubikey; zgadza się z plikiem age-recipients-yubikey.txt. Wykorzystywane narzędzia: age 1.2.1 oraz age-plugin-yubikey 0.5.1. Nie zmieniono slotów PIV, PIN, PUK ani management key.

## Architektura: hybrydowa, bez przerwy w backupach

- Archiwa Magazynu .mgzb nadal są szyfrowane AES-256-GCM.
- Jawny 32-bajtowy AES key, wymagany do automatycznego szyfrowania archiwów, pozostaje w prywatnym pliku 0600 na działającym serwerze. Codzienne szyfrowanie **nie wymaga podłączonego YubiKeya**.
- **Dodatkowa kopia klucza AES do odzyskiwania** jest szyfrowana narzędziem age do publicznego odbiorcy istniejącego YubiKeya Stage K. Szyfrowanie działa bez urządzenia; odszyfrowanie wymaga fizycznego YubiKeya oraz jego PIN-u.

**Ograniczenie:** rozwiązanie nie chroni przed odczytaniem klucza przez atakującego z pełnym dostępem do działającego serwera, ponieważ serwer zachowuje jawny klucz AES. Zapewnia natomiast możliwość odzyskania AES key z GlobalNAS po utracie dysku serwera.

## Wykonane testy DEV

1. Potwierdzono lokalny AES key 32 bajty / 0600, katalog prywatny 0700.
2. Test szyfrowania syntetycznego 32-bajtowego klucza publicznym recipientem Stage K bez fizycznego YubiKeya: PASS.
3. Zaszyfrowano **rzeczywisty klucz AES Magazynu** przez age -R. Sekret przekazano do subprocess przez stdin; bez umieszczania w argumentach, logach ani jawnym pliku tymczasowym.
4. Potwierdzono tożsamość GlobalNAS CIFS i marker Stage K. Zapis dotyczył wyłącznie wydzielonego katalogu Magazyn/recovery; nie zmieniono Platform/secrets ani innych kopii Stage K.
5. Plik zaszyfrowanego klucza został zapisany:

       /mnt/AI_Platform/Magazyn/recovery/magazyn-v1-aes256-key-yubikey.age

6. Odczytano plik z NAS i zweryfikowano identyczność ciphertext, nagłówek age-encryption.org/v1 oraz brak jawnego AES key w zaszyfrowanym pliku.
7. Lokalne AES key i istniejące archiwa .mgzb pozostały niezmienione.

**Wyniki:** YUBIKEY_AES_RECOVERY_KEY_WRAP_PASS i RECOVERY_KEY_YUBIKEY_CIPHERTEXT_ON_GLOBALNAS_PASS.

## Procedura odzyskania — kolejny krok odbioru

1. Podłącz **ten sam** YubiKey 5C i przygotuj PIN PIV. PIN-u nie wpisuj w czacie, poleceniu, repozytorium ani logach.
2. Na kontrolowanym komputerze przywracającym użyj age + age-plugin-yubikey i odtwórz plik identity dla PIV 0x82.
3. Odszyfruj plik .age do prywatnego pliku z uprawnieniami 0600, najlepiej w /dev/shm podczas testu; nigdy nie wyświetlaj zawartości klucza na ekranie.
4. Zweryfikuj długość odzyskanego klucza (32 bajty), wykonaj verify zaszyfrowanego archiwum .mgzb z NAS i restore do **nowej**, pustej bazy.
5. Po zakończeniu testu usuń tymczasowy jawny klucz z RAM. Zarchiwizuj wynik operacji bez danych poufnych.

**Status procedury:** 27.10.2026 YubiKey został następnie **podłączony i poprawnie wykryty**, PIV slot 0x82 ECC P-256, licznik PIN 3/3. Plugin zwrócił jedną pasującą identity, a publiczny recipient jest identyczny z tym użytym do szyfrowania. Niezmienna konfiguracja YubiKey i preflight `YUBIKEY_RECOVERY_PREFLIGHT=PASS`. **Fizyczny decrypt tego pliku nadal oczekuje na lokalne podanie PIN-u.** Wcześniejszy decrypt drill Stage K nie zastępuje tego sprawdzenia.

### Bezpieczny test jedną komendą na serwerze

Po podłączeniu YubiKeya uruchom jako użytkownik `harrypotter`, **bez sudo**, w interaktywnym terminalu SSH:

    bash /srv/ai-data/staging/magazyn-telegram-dev-20261027/verify-yubikey-recovery.sh --run

Skrypt ma wcześniej zaliczony preflight `--check` i sprawdza prawdziwy YubiKey 5C, PIV RETIRED1/0x82 oraz zgodność publicznego odbiorcy Stage K. **Parametr pluginu `--slot 1` oznacza PIV RETIRED1/0x82; nie należy używać `--slot 82`**, ponieważ plugin wymaga numeru slotu 1–20.

Jeżeli pojawi się prośba o PIN PIV, wpisz go **bezpośrednio w tym terminalu**, nigdy w ChatGPT ani argumentach poleceń. Przy błędnym PIN-ie przerwij test zamiast ponawiać próbę wielokrotnie. Po odszyfrowaniu skrypt porówna odzyskany AES key bez jego ujawniania, zweryfikuje rzeczywisty zaszyfrowany backup Magazynu z GlobalNAS i wykona próbny restore do katalogu RAM `/dev/shm`. Katalog tymczasowy zostanie usunięty przy wyjściu. Nie nadpisuje bazy, nie zmienia Stage K, nie restartuje WebGUI/Telegrama.

Wynik pozytywny to wyświetlenie `MAGAZYN_REAL_YUBIKEY_RECOVERY_DRILL=PASS` wraz z `TEMPORARY_RAM_SECRETS_REMOVED=PASS`. **Nie ogłaszamy pełnego PASS przed faktycznym wynikiem tej operacji.**

## Ryzyka przed produkcją

- Jedno fizyczne urządzenie chroni klucz odzyskiwania zarówno Stage K, jak i Magazynu. To wspólny punkt awarii: utrata YubiKeya po utracie serwera może uniemożliwić odzyskanie. Zalecany drugi, niezależny YubiKey recovery albo oddzielna zasada offline escrow.
- **Nie usuwać lokalnego AES key:** obecne automatyczne backupy wymagają go do szyfrowania. Nie rotować klucza AES bez procedury rewrap dla nowych archiwów i zachowania kluczy dla archiwów historycznych.
- Nie resetować PIV ani nie nadpisywać slotu 0x82. Nie przesyłać PIN ani klucza w czacie.
- Nadal należy podłączyć cykliczny backup Magazynu do istniejącego Stage K, bez nowego niezależnego schedulera. Projekt nadal jest DEV.

Ten dokument potwierdza zabezpieczenie kopii AES key i zapis na realnym NAS, **nie** pełen odbiór odzyskiwania z YubiKeya.
