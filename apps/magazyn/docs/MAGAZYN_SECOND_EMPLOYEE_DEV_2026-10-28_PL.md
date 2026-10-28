# Magazyn V1 — drugi użytkownik: konto pracownika (DEV)

Data: 2026-10-28. Gałąź: feature/magazyn-v1-dev-20261026.

## Stan wyjściowy

Rzeczywista baza DEV schemat 3, integrity_check=ok, 1 aktywny administrator, 0 pracowników, 2 produkty, 4 zdarzenia, 1 dokument. Istniejące API już obsługiwało utworzenie osobnego użytkownika z rolą "user", sól i scrypt, trwałe sesje i blokowanie konta. Żadna migracja SQL nie jest konieczna.

## Zrealizowana zmiana

W panelu administracyjnym Magazynu użytkownik administrujący widzi formularz **Dodaj pracownika**. Tworzy imienny login i hasło (co najmniej 12 znaków). Rola w formularzu jest na stałe "user", aby nie nadać przypadkowo uprawnień administratora. Lista kont czytelnie rozróżnia Administrator/Pracownik, umożliwia zmianę loginu oraz blokowanie/reaktywację konta.

Po wylogowaniu administratora formularz tworzenia pracownika jest resetowany, żeby na współdzielonym telefonie nie pozostawało wpisane hasło. Po pomyślnym utworzeniu również czyszczony jest formularz. Hasło użytkownika nie jest ujawniane w API listy kont ani logach. Nikt nie zna ani nie ustawia domyślnego hasła pracownika.

Zakres pracownika:
- Osobne logowanie na telefonie lub komputerze; własna sesja z HttpOnly i SameSite cookie.
- Zakładki Produkty, Do zamówienia, Inwentaryzacja i Historia.
- Wyszukiwanie produktów i odczyt stanów/dokumentacji; przyjęcia, wydania z obowiązkowym powodem, przesunięcia.
- W historii zapisywana jest tożsamość konkretnego operatora oraz jego działania.
- Brak dostępu do zarządzania kontami, lokalizacjami, zamówieniami administratora, stanami minimalnymi, korektami/inwentaryzacją zapisową, eksportem, backupami i konfiguracją komunikatorów. Każda blokada jest egzekwowana po stronie backendu, a nie jedynie ukryciem przycisku.
- Zablokowanie konta natychmiast unieważnia aktywne sesje i uniemożliwia ponowne logowanie. Po reaktywacji można ponownie zalogować się osobnym hasłem.

Wszystko działa na tej samej bazie SQLite DEV co dotychczas. Żadnego drugiego serwera, schedulera ani konta systemowego Linux.

## Odbiór

- Testy nowego przepływu API na izolowanej bazie SQLite: admin tworzy pracownika z unikalnym loginem, pracownik loguje się niezależnie, czyta dane, realizuje wydanie i przyjęcie, operacje są przypisane do niego w historii; zablokowane endpointy administratora zwracają 403, dezaktywacja natychmiast unieważnia sesję, aktywacja i reset hasła admina działają bez usuwania historii: PASS.
- Kontrakt HTML/JS: stała rola user, oddzielne pole hasła, brak przypadkowego wyboru roli admin, kasowanie formularza przy wylogowaniu: PASS.
- Firefox WebDriver BiDi (390×844 i 1440×900), izolowany test Synthetic SQLite: administrator z GUI tworzy pracownika, pracownik loguje się, widzi tylko cztery zakładki (bez Ustawień), backend odmawia dostępu do /api/users i /api/backup/status, pracownik wydaje 2 sztuki i zmiana w historii zawiera jego login, administrator blokuje konto; PASS.
- Wszystkie testy Magazynu: **210/210 PASS**, JS syntax, Python compile i git diff --check PASS.
- Nie wysłano żadnego powiadomienia do realnych użytkowników. Nie ujawniono haseł ani danych prywatnych. Kolory GUI, nawigacja mobilna i dotychczasowe dane bez zmian.

## Uruchomienie dla faktycznego drugiego pracownika

Na prawdziwym Magazynie DEV w przeglądarce administratora:

1. Zaloguj się jako administrator.
2. Otwórz **Ustawienia → Użytkownicy → Dodaj pracownika**.
3. Podaj wybrany login pracownika (3–40 znaków: litery, cyfry, _ . -) oraz silne unikalne hasło min. 12 znaków. Nie wysyłaj hasła przez ChatGPT.
4. Po utworzeniu pracownik otwiera swój Magazyn w drugim urządzeniu (adres Tailscale Serve HTTPS :8443), loguje się własnymi danymi i widzi cztery zakładki.
5. Administrator może później zablokować albo reaktywować konto oraz zmienić login. Stany/operacje pozostają przypisane do użytkownika.
6. Osobno **trzeba dopuścić urządzenie pracownika do Tailscale przez bezpieczne ACL/Grants**. Konta Magazynu i członkostwo w tailnecie są osobnymi warstwami. Dzisiaj nie tworzymy publicznego Funnel, nie wystawiamy publicznego portu.

Właściciel nie podał loginu ani hasła pracownika. **Nie tworzono w rzeczywistej bazie automatycznego konta "pracownik" z odgadnionym hasłem.** Wprowadzenie danych odbędzie się lokalnie w WebGUI administratora. Do odbioru produkcji pozostaje faktyczne zalogowanie urządzenia pracownika przez Tailscale i weryfikacja ACL/Grants.

## Rollback

Zmiana ograniczona do etykiet HTML/JS i kontraktu testowego. Nie ma migracji bazy, nowych jednostek ani zmiany tokenów botów. W razie problemów przywrócić poprzedni commit WebGUI i zrestartować tylko magazyn-webgui-dev.service. Konta stworzone później pozostają w SQLite; rollback GUI nie kasuje ani nie dezaktywuje ich automatycznie. Nie kasować historii, kont ani danych rzeczywistych.

Magazyn pozostaje w DEV; main i produkcja AI Platform bez zmian.

## Odbiór wdrożenia DEV na rzeczywistym serwerze

Commit funkcji: 49ab4d4 (branch feature/magazyn-v1-dev-20261026), push GitHub PASS, bez merge do main.

Zrestartowano wyłącznie magazyn-webgui-dev.service; Telegram DEV nie był restartowany. Rzeczywisty HTTPS Tailscale :8443 /healthz, aktualne HTML z nowym formularzem i role=user oraz aktualne JS wyświetlające Pracownik: PASS. API bez sesji (użytkownicy, backupy, produkty, lokalizacje) nadal HTTP 401. Weryfikacja PRAGMA integrity_check, foreign_key_check, SHA256 dokumentacji i liczby rekordów dziesięciu tabel przed/po restarcie: PASS, **bez zmian danych**. WebGUI i Telegram DEV aktywne. Faktycznie w bazie nadal jest tylko jeden administrator — konto drugiego pracownika czeka na wybrany login i hasło w panelu administratora. Odbiór na rzeczywistym urządzeniu pracownika/Tailscale ACL pozostaje PENDING.
