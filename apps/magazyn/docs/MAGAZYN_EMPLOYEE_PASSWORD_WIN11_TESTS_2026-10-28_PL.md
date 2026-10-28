# Magazyn V1 — zmiana hasła pracownika i test na Windows 11

28.10.2026 | Środowisko DEV | gałąź feature/magazyn-v1-dev-20261026

## Wdrożone funkcje

- W górnym pasku przy nazwie użytkownika jest nowy przycisk kłódki. Po kliknięciu otwiera okno Zmień moje hasło.
- Pracownik lub administrator wprowadza dotychczasowe hasło, nowe (co najmniej 12 znaków) oraz jego potwierdzenie.
- Endpoint POST /api/auth/change-password wymaga sesji, tokenu CSRF i prawidłowego poprzedniego hasła. Nietrafione próby podlegają tej samej kontroli limitu co logowanie (HTTP 429 po zbyt wielu próbach).
- Nowy skrót hasła (scrypt) oraz unieważnienie WSZYSTKICH sesji użytkownika są zapisane atomowo w SQLite. Zmieniający hasło musi zalogować się ponownie.
- Administrator, w Ustawienia → Użytkownicy, ma przy kontach roli Pracownik przycisk Resetuj hasło i formularz z potwierdzeniem. Wykorzystuje on istniejący administracyjny endpoint PATCH /api/users/{id}, który unieważnia wszystkie sesje resetowanego pracownika.
- Zamykanie okien usuwa wpisane hasła z pól formularza. Nie ma haseł w localStorage, sessionStorage ani logach.
- Zachowano kolorystykę i dotychczasową nawigację; na 320 px kłódka mieści się bez poziomego przewijania.
- Pracownik nadal nie ma dostępu do kont, kopii zapasowych, korekt, lokalizacji i ustawień.

Nie zmieniano realnego hasła pracownika, zawartości magazynu, dokumentów, Telegrama ani schematu bazy danych.

## Odbiór automatyczny

- test_password_change.py: 6 PASS (dwie jednoczesne sesje, wycofanie obu sesji, błędne stare hasło, wymagane CSRF, blokada wielokrotnych prób, reset przez administratora, niezmieniona rola).
- Firefox: modal zmiany hasła 390×844, modal resetu administratora 1440×900, widoczna kłódka 320×700, konto pracownika bez zakładki Ustawienia, backend API admin daje 403: PASS.
- Pełna regresja: 216/216 PASS; składnia JS i Python, git diff check PASS.
- Zastrzeżenie: przeglądarka testowa to Linux Firefox; prawdziwy Edge/Chrome Windows 11 musi zostać odebrany osobno przez użytkownika.

## Odbiór na prawdziwym Windows 11

1. Na komputerze z włączonym Tailscale otwórz w Microsoft Edge albo Chrome: https://ai-server.tail759e12.ts.net:8443/ . Certyfikat HTTPS musi przejść bez ostrzeżeń.
2. Zaloguj się JAKO PRACOWNIK własnym loginem i hasłem. Nie wpisuj ani nie przesyłaj hasła do czatu.
3. Powinny być cztery zakładki: Produkty, Do zamówienia, Inwentaryzacja, Historia. Brak Ustawień.
4. Kliknij kłódkę w prawym górnym rogu. Podaj obecne hasło, nowe silne hasło i potwierdzenie. Po zatwierdzeniu oczekuj automatycznego wylogowania.
5. Zaloguj się ponownie nowym hasłem. Poprzednie nie może działać. Nie powtarzaj wielu celowo nieudanych prób: istnieje limiter logowania (5 błędów może zablokować na 10 minut).
6. Jako zalogowany pracownik otwórz w nowej karcie adres https://ai-server.tail759e12.ts.net:8443/api/users oraz https://ai-server.tail759e12.ts.net:8443/api/backup/status . Oba powinny zwrócić HTTP 403. Nawigacja powinna pozostać dostępna po powrocie do Magazynu.
7. Zaloguj się jako ADMINISTRATOR. W Ustawienia → Użytkownicy sprawdź przy pracowniku przycisk Resetuj hasło. Nie resetuj rzeczywistego hasła bez uzgodnienia z pracownikiem, bo natychmiast unieważni to jego sesje.
8. Nie zmieniaj prawdziwych stanów magazynowych podczas tego testu. Sprawdź tylko odczyt produktów i dokumentacji.

## Dostęp sieciowy pozostaje osobnym odbiorem

Role Magazynu zabezpieczają /api/users i /api/backup, lecz to nie dowodzi sieciowego odizolowania innego portu serwera AI Platform. Reguły Tailscale ACL/Grants dla użytkownika pracownika muszą zostać niezależnie sprawdzone z jego urządzenia. Brak Funnel i brak zmian sieciowych w tym etapie.

## Rollback

Kod zmienia endpoint sesji, funkcję sklepu i formularze WebGUI. Nie ma nowej migracji bazy. Można przywrócić poprzedni commit DEV i zrestartować jedynie magazyn-webgui-dev.service. Zmienionych przez użytkowników haseł NIE cofamy automatycznie; pozostają zapisane w SQLite. Wszystkie rzeczywiste konta i stany pozostają zachowane.
