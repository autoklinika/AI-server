# Magazyn V1 — odzyskiwanie AES przez istniejący YubiKey 5C

**Data:** 27.10.2026. **Środowisko:** AI Platform / Magazyn V1 DEV.
**Status:** **REAL_YUBIKEY_RECOVERY_DRILL=PASS (27.10.2026)** — zaszyfrowanie klucza AES publicznym recipientem Stage K, zapis na GlobalNAS, fizyczne odszyfrowanie z YubiKey 5C/PIV, weryfikacja odzyskanego klucza, kontrola archiwum i odtworzenie bazy w RAM. Wynik potwierdzony przez użytkownika na podstawie pełnego logu skryptu, bez ujawnienia PIN-u ani sekretów.

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

## Zweryfikowana procedura awaryjnego odzyskania

1. Podłącz **ten sam** YubiKey 5C i przygotuj PIN PIV. PIN-u nie wpisuj w czacie, poleceniu, repozytorium ani logach.
2. Na kontrolowanym komputerze przywracającym użyj age + age-plugin-yubikey i odtwórz plik identity dla PIV 0x82.
3. Odszyfruj plik .age do prywatnego pliku z uprawnieniami 0600, najlepiej w /dev/shm podczas testu; nigdy nie wyświetlaj zawartości klucza na ekranie.
4. Zweryfikuj długość odzyskanego klucza (32 bajty), wykonaj verify zaszyfrowanego archiwum .mgzb z NAS i restore do **nowej**, pustej bazy.
5. Po zakończeniu testu usuń tymczasowy jawny klucz z RAM. Zarchiwizuj wynik operacji bez danych poufnych.

**Status procedury:** **PASS 27.10.2026.** YubiKey został poprawnie wykryty; PIV slot 0x82 ECC P-256 oraz publiczny recipient zgodny z użytym do szyfrowania. Początkowy licznik prób PIN-u wynosił 3/3. Użytkownik uruchomił skrypt z `--run` i przekazał jego kompletny wynik: odszyfrowanie rzeczywistego pliku `.age`, zgodność odzyskanego klucza AES, weryfikacja archiwum `.mgzb`, odtworzenie bazy w pamięci RAM oraz usunięcie danych tymczasowych — wszystkie etapy PASS.

### Procedura ponownego testu, gdy będzie potrzebny

Po podłączeniu YubiKeya uruchom jako użytkownik `harrypotter`, **bez sudo**, w interaktywnym terminalu SSH:

    bash /srv/ai-data/staging/magazyn-telegram-dev-20261027/verify-yubikey-recovery.sh --run

Skrypt ma zaliczony preflight `--check` oraz rzeczywisty test `--run`. Sprawdza YubiKey 5C, PIV RETIRED1/0x82 oraz zgodność publicznego odbiorcy Stage K. **Parametr pluginu `--slot 1` oznacza PIV RETIRED1/0x82; nie należy używać `--slot 82`**, ponieważ plugin wymaga numeru slotu 1–20.

Jeżeli pojawi się prośba o PIN PIV, wpisz go **bezpośrednio w tym terminalu**, nigdy w ChatGPT ani argumentach poleceń. Przy błędnym PIN-ie przerwij test zamiast ponawiać próbę wielokrotnie. Po odszyfrowaniu skrypt porówna odzyskany AES key bez jego ujawniania, zweryfikuje rzeczywisty zaszyfrowany backup Magazynu z GlobalNAS i wykona próbny restore do katalogu RAM `/dev/shm`. Katalog tymczasowy zostanie usunięty przy wyjściu. Nie nadpisuje bazy, nie zmienia Stage K, nie restartuje WebGUI/Telegrama.

Wynik pozytywny to wyświetlenie `MAGAZYN_REAL_YUBIKEY_RECOVERY_DRILL=PASS` wraz z `TEMPORARY_RAM_SECRETS_REMOVED=PASS`. **Wynik taki został potwierdzony w rzeczywistym teście 27.10.2026.**

## Formalny wynik rzeczywistego testu z PIN-em

Użytkownik uruchomił skrypt lokalnie na serwerze 27.10.2026 i przekazał następujące **bezpieczne znaczniki wyniku**, bez PIN-u, kluczy kryptograficznych ani identyfikatorów kont:

- `YUBIKEY_5C_PIV_82_MATCH=PASS`
- `PHYSICAL_YUBIKEY_AGE_DECRYPT=PASS`
- `YUBIKEY_RECOVERED_AES_KEY_MATCH=PASS`
- `RECOVERED_KEY_VERIFY_REAL_NAS_BACKUP=PASS`
- `YUBIKEY_RECOVERED_BACKUP_RESTORE_IN_RAM=PASS`
- `MAGAZYN_REAL_YUBIKEY_RECOVERY_DRILL=PASS`
- `LIVE_MAGAZYN_DATABASE=UNCHANGED`
- `STAGE_K_PIV_CONFIG=UNCHANGED`
- `TEMPORARY_RAM_SECRETS_REMOVED=PASS`

Po teście niezależnie sprawdzono na serwerze, że pozostały aktywne obie usługi Magazynu DEV (WebGUI i Telegram), archiwum `.age` nadal jest na GlobalNAS z prawami `0600`, brak pozostałych katalogów testu w `/dev/shm`, a niezalogowane wywołanie API zwraca HTTP 401. Nie wykonywano ponownego odszyfrowania ani nie żądano PIN-u przez czat.

**Zakres zatwierdzenia:** techniczny test awaryjnego odzyskania tej konkretnej kopii Magazynu jest zakończony PASS. Nie jest to zgoda na wdrożenie produkcyjne ani gwarancja odzyskania po jednoczesnej utracie hosta, NAS i jedynego YubiKeya.

## Ryzyka przed produkcją

- Jedno fizyczne urządzenie chroni klucz odzyskiwania zarówno Stage K, jak i Magazynu. To wspólny punkt awarii: utrata YubiKeya po utracie serwera może uniemożliwić odzyskanie. Zalecany drugi, niezależny YubiKey recovery albo oddzielna zasada offline escrow.
- **Nie usuwać lokalnego AES key:** obecne automatyczne backupy wymagają go do szyfrowania. Nie rotować klucza AES bez procedury rewrap dla nowych archiwów i zachowania kluczy dla archiwów historycznych.
- Nie resetować PIV ani nie nadpisywać slotu 0x82. Nie przesyłać PIN ani klucza w czacie.
- Nadal należy podłączyć cykliczny backup Magazynu do istniejącego Stage K, bez nowego niezależnego schedulera. Projekt nadal jest DEV.

**Odbiór funkcjonalny odzyskiwania AES z YubiKeya i rzeczywistego backupu GlobalNAS: PASS.** Magazyn pozostaje w DEV: brak nadal cyklicznej integracji ze Stage K, drugiego niezależnego mechanizmu odzyskiwania po utracie YubiKeya oraz końcowego odbioru produkcyjnego.
