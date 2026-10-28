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


## Aktywacja i test rzeczywistej instancji DEV

Commit funkcjonalny: 9b79c3e na gałęzi feature/magazyn-v1-dev-20261026. Po wykonaniu 216/216 testów PASS wykonano restart **wyłącznie** magazyn-webgui-dev.service, bez restartu Telegrama.

- HTTPS Tailscale Serve /healthz: HTTP 200, SSL verify 0.
- Rzeczywisty HTML: przycisk change-own-password, modale own-password-dialog i staff-password-dialog, defer script /static/account.js obecne.
- Rzeczywisty JS: nowy endpoint change-password, obsługa resetu administratora obecna.
- Anonimowe GET /api/users i GET /api/auth/me nadal dają HTTP 401; CSP same-origin zachowany.
- Baza realnego Magazynu DEV: schema 3, PRAGMA integrity_check=ok, foreign_key_check 0, SHA-256 dokumentów PASS.
- Istnieje jeden aktywny administrator i jeden aktywny pracownik; 2 produkty, 4 operacje, 2 rekordy stanów, 1 załącznik, 1 lokalizacja. Testy syntetyczne nie dopisały nic do realnego Magazynu. Realnego hasła pracownika ani administratora nie modyfikowano.
- Obie usługi WebGUI DEV i Telegram DEV aktywne; kod i dane produkcyjne niezmienione.

**PENDING / Windows 11:** fizyczne zalogowanie pracownika w Edge/Chrome, zmiana jego rzeczywistego hasła, ponowne logowanie i odczyt HTTP 403 dla API administratora. Nie oznaczać tego testu jako PASS na podstawie wyniku Firefox na serwerze.

## Odbiór użytkownika — Windows 11, 28.10.2026

Po udostępnieniu zmiany hasła i testów ról w Magazynie DEV użytkownik potwierdził w rozmowie: **„działa jak należy :)”**. Oznaczamy więc odbiór funkcjonalny WebGUI dla konta pracownika na Windows 11 jako **PASS — potwierdzenie użytkownika**. Wcześniej automatyczne testy backendu i Firefox były PASS (216/216).

To potwierdzenie **nie jest samodzielnym dowodem**, że wykonano wszystkie podtesty HTTP 403, sprawdzono wygaśnięcie wszystkich aktywnych sesji w różnych przeglądarkach ani że Tailscale ACL/Grants ograniczają użytkownika do portu 8443. Sieciowe ACL i formalny odbiór izolacji od AI Platform pozostają **PENDING**. Nie wymagamy ani nie odczytujemy w tym celu hasła pracownika, nie wykonujemy kolejnej rotacji hasła na serwerze.


## Odbiór rzeczywistego telefonu pracownika — 28.10.2026, wieczór

Właściciel potwierdził rzeczywisty test na telefonie pracownika zalogowanym do własnego konta Tailscale pracownika, nie do konta właściciela:

- HTTPS Magazynu V1, port 8443: **DZIAŁA** na urządzeniu pracownika.
- Próba otwarcia AI Platform pod /control, port 443: **NIE OTWIERA SIĘ** na urządzeniu pracownika.
- Osobne konto Magazynu i jego funkcje przeszły wcześniej odbiór na Windows 11 oraz testy syntetyczne uprawnień backendu.

**Wynik: potwierdzono PASS praktycznego testu dostępu pracownika i odmowy otwarcia panelu AI Platform.** Test nie identyfikuje mechanizmu odmowy (ACL/Grants, routing, uwierzytelnianie lub inna warstwa) i nie zastępuje niezależnego przeglądu rzeczywistej centralnej polityki Tailscale Grants/ACL oraz pozostałych portów serwera. Formalny audyt polityki nadal osobny; nie oznaczamy go jako niezależnie potwierdzonego.

Nie zmieniano konfiguracji Tailscale ani uprawnień, nie otwierano Funnel, nie przeprowadzano testów destrukcyjnych.

## Automatyczny dzienny cykl Magazynu — potwierdzenie z 28.10.2026

Rzeczywisty istniejący systemd user-timer wywołał ai-platform-stage-k-daily.service 28.10 o 02:30 CET, a jednostka zakończyła się o 02:31:26 CET: **Result=success, ExecMainStatus=0**. W dzienniku adapter Magazynu wykonał mode=cycle, created=1, uploaded=1, pending=0, status=PASS. Na GlobalNAS obecne jest archiwum dzienne Magazynu z 28.10. Bieżące statusy Stage K daily, weekly, monitor: **PASS**. Bramka rzeczywistego automatycznego uruchomienia daily Magazynu jest zatem zamknięta.

Przed produkcją pozostaje niezależne odzyskiwanie klucza po dostawie drugiego YubiKey 5C (wersja pendrive/age X25519 została odrzucona) i formalny audyt docelowej polityki Tailscale, jeżeli wymagana jest udowodniona izolacja wszystkich portów. Stare wpisy o przyszłym cyklu dziennym są historyczne.
