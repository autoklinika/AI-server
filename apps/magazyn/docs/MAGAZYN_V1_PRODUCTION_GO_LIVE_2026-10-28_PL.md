# Magazyn V1 — produkcja uruchomiona 28.10.2026

**Wynik: PRODUKCJA AKTYWNA Z UDOKUMENTOWANYMI WYJĄTKAMI (nie pełne formalne GO).**

Wdrożenie na bezpośrednie polecenie właściciela: „Więc wdrażamy Magazyn do produkcji”.

**Data aktywacji:** 28.10.2026, 22:46 CET.
**Zamrożony commit:** 529af02029e1.
**Źródło:** feature/magazyn-v1-dev-20261026.
**Testy:** 220/220 PASS na gałęzi DEV i 220/220 PASS na zamrożonym wydaniu w osobnym runtime; pip check PASS.

## 1. Architektura produkcji

Kod: /srv/ai-data/magazyn-v1/releases/529af02029e1/apps/magazyn — wersjonowany, tylko do odczytu.

Python: /srv/ai-data/magazyn-v1/runtime/py314 — izolowany runtime, wersje zależności takie jak w odebranym DEV.

Baza SQLite: /srv/ai-data/magazyn-v1/private/magazyn.sqlite3 — osobny prywatny katalog 0700, plik 0600, schema 3.

Klucz AES-256 i token Telegram: prywatne pliki 0600 w katalogu /srv/ai-data/magazyn-v1/private; zachowano niezmienioną wartość istniejącego AES, aby wszystkie stare kopie pozostawały odtwarzalne. Nie ujawniono haseł użytkowników, tokenów ani kluczy.

Kopia bazy przez SQLite Backup API została wykonana po zatrzymaniu DEV WebGUI i Telegrama. Wymuszono nowe bezpieczne sesje przez usunięcie dotychczasowych ciasteczek sesyjnych WYŁĄCZNIE w nowej bazie; hasła kont i wszystkie tabele biznesowe zachowano.

WebGUI produkcyjne: jednostka użytkownika magazyn-webgui.service, aktywna i enabled, backend wyłącznie 127.0.0.1:18765, MAGAZYN_ENV=production i MAGAZYN_COOKIE_SECURE=1.

Bot: magazyn-telegram.service, aktywny i enabled, dokładnie jeden proces Telegram. Stare jednostki magazyn-webgui-dev.service i magazyn-telegram-dev.service zatrzymano; ich oryginalne definicje pozostawiono.

User-systemd ma Linger=yes, co umożliwia automatyczne uruchamianie obu aktywowanych jednostek po restarcie hosta.

Adres nadal: https://ai-server.tail759e12.ts.net:8443/ — wyłącznie tailnet, bez Funnel. Tailscale Serve i port 443 AI Platform pozostają bez zmian.

## 2. Kontrola po przełączeniu

- Produkcyjne /healthz: HTTP 200, TLS verify 0, service=magazyn, environment=production.
- HTML: oznaczenie MAGAZYN V1 · PRODUKCJA, bez widocznego badge DEV.
- Nieautoryzowane API użytkowników, backupów, produktów i sesji: HTTP 401.
- Baza: integralność SQLite OK, brak naruszonych kluczy obcych, SHA-256 załączników PASS.
- Dwa konta: jeden aktywny administrator i jeden aktywny pracownik.
- Produkty: 2, bilanse: 2, historia: 4, dokumenty: 1, lokalizacje: 1. Wszystkie tabele biznesowe zachowują tę samą zawartość co przed przełączeniem.
- Sesje: 0 bezpośrednio po przełączeniu — zamierzona operacja, użytkownicy muszą zalogować się ponownie, aby otrzymać Secure cookie.
- Nowy zaszyfrowany backup produkcji AES-256-GCM: wygenerowany, wysłany na GlobalNAS, ponownie odczytany i zweryfikowany, PASS. Lokalny backlog 0.
- Stage K: trzy istniejące drop-in Magazynu (daily, weekly, monitor) zmieniono na bazę i konfigurację produkcyjną. Nie tworzono nowych timerów. Test istniejącego monitora po przełączeniu: Result=success, Magazyn retry PASS, pending=0.
- Stage K daily/weekly/monitor jako całość nadal PASS.
- Kontrolny restart magazyn-webgui.service: PASS, HTTPS 200 po restarcie.
- Dotychczasowa usługa AI Platform na HTTPS 443 nadal odpowiada; pozostałe aplikacje i RM nie były restartowane.

## 3. Wyjątki bezpieczeństwa i formalny wynik

**Właściciel polecił produkcyjne uruchomienie pomimo dwóch niedokończonych etapów. Formalna bramka magazyn.release_gate po uruchomieniu nadal zwraca NO_GO.**

1. Drugi YubiKey 5C nie jest jeszcze fizycznie dopisany i sprawdzony. Działa pierwszy fizyczny YubiKey oraz kopia master AES dla niego na GlobalNAS. Ponieważ produkcja używa identycznego AES, istniejąca kopia recovery nadal odszyfrowuje nowe archiwa. Ryzyko pozostaje: utrata tego jednego YubiKeya po jednoczesnej utracie dysku serwera może uniemożliwić odzyskanie klucza. Dodać drugi YubiKey i wykonać niezależny decrypt/restore drill po dostawie. Wariant pendrive/age X25519 został wyraźnie odrzucony przez właściciela.
2. Telefon pracownika ma osobne konto Tailscale i rzeczywisty dostęp do Magazynu 8443, a nie może otworzyć panelu AI Platform 443. To potwierdza zachowanie praktyczne, nie zastępuje niezależnego audytu całej centralnej polityki Tailscale ACL/Grants i pozostałych portów. Nie zmieniano ACL ani istniejącego Serve.

**Automatyczna bramka formalna aktualnie zakłada wariant offline age X25519, którego użytkownik nie chce.** Po otrzymaniu drugiego YubiKeya należy zmienić bramkę na formalny test dwóch różnych sprzętowych recipientów i dwóch niezależnych fizycznych odtworzeń. Nie fałszować statusu przez tworzenie sztucznego pliku .age.

Wynik zachowano lokalnie: /srv/ai-data/magazyn-v1/reports/production-formal-go-no-go.json
PASS: sqlite, magazyn_backup, stage_k_daily, stage_k_weekly, pytest, https_tls, daily_timer.
BLOCKED: offsite_recovery, employee_access (pełna polityka sieciowa).

Stan produkcji: DZIAŁA. Status formalnej certyfikacji bezpieczeństwa: JESZCZE NIE GO.

## 4. Backup oraz punkt wycofania

Przed produkcją, przy zatrzymanych procesach zapisujących, wykonano prywatny, sprawdzony zaszyfrowany backup dotychczasowej bazy DEV: /srv/ai-data/magazyn-v1/rollback/pre-cutover/daily/.

Zachowano także oryginalne definicje systemd i Stage K drop-in, ich SHA-256 oraz zamrożony kod sprzed produkcji. Lokalny manifest: /srv/ai-data/magazyn-v1/config/production-cutover-manifest.json. Raport: /srv/ai-data/magazyn-v1/reports/cutover-result.json.

**Ważne:** nigdy nie przywracaj starej bazy DEV po rozpoczęciu normalnej pracy produkcyjnej; może ona nie zawierać nowych stanów, kont lub operacji.

Przygotowany został awaryjny POWRÓT TYLKO DO POPRZEDNIEGO KODU, BEZ COFANIA BAZY. W przypadku awarii operator wykonuje z uprawnieniami zwykłego użytkownika, po własnej decyzji:

    python3 /srv/ai-data/magazyn-v1/config/emergency_code_rollback.py --check
    python3 /srv/ai-data/magazyn-v1/config/emergency_code_rollback.py --activate

Skrypt zamienia kod usług, ale wykorzystuje bieżącą bazę produkcyjną i ten sam AES/token; nie przywraca starego stanu. Kiedy będzie można wrócić do nowej wersji:

    python3 /srv/ai-data/magazyn-v1/config/emergency_code_rollback.py --resume-production

Rollback skrypt przeszedł kontrolę składni i preflight, **nie uruchamiano faktycznego rollbacku** na działającej produkcji. Nie uruchamiaj polecenia --activate bez wyraźnej potrzeby.

## 5. Co dalej

Pracownik i administrator ponownie logują się przez dotychczasowy adres HTTPS (dotychczasowe hasła nie uległy zmianie). Sprawdzić pierwszy zwykły automatyczny backup produkcyjny z 29.10 o 02:30 CET. Po dostawie drugiego YubiKeya dopisać go jako niezależny klucz recovery i wykonać fizyczny test; zamknąć formalny audyt polityki Tailscale.

Nie scalono niepowiązanych zmian do main; zamrożona produkcja ma precyzyjny commit 529af02029e1 i nie zależy od ruchomego DEV.

## Audyt Tailscale z 28.10.2026 — ważna zmiana oceny ryzyka

Po wdrożeniu produkcji wykonano bezpieczny audyt rzeczywistej mapy ACL dostarczanej przez Tailscale do serwera. Wynik: **FAIL / HIGH**. Efektywny PacketFilter serwera dopuszcza szerokie zakresy adresowe tailnetu (w tym jedno udostępnione urządzenie) do wszystkich portów 0–65535 TCP/UDP/ICMP; nie dowiedziono ograniczenia pracownika wyłącznie do 8443. OpenSSH słucha na 22, Cockpit na 9090, AI Control Center na 443. UFW active, ale reguł nie można odczytać bez sudo. Nie stwierdzono publicznego Funnel.

Test użytkownika, w którym Magazyn :8443 działał, a AI Control Center :443 nie otwierał się, nadal jest ważny jako obserwacja z urządzenia, ale **nie pozwala uznać centralnej polityki ACL za bezpieczną**. Nie potwierdzono prób ani udanego dostępu pracownika do pozostałych usług. Żadnych reguł nie zmieniano. Formalny etap employee_access pozostaje BLOCKED. Raport: [Audyt Tailscale 28.10.2026](MAGAZYN_TAILSCALE_SECURITY_AUDIT_2026-10-28_PL.md).

## AKTUALIZACJA — Tailscale Grants po wdrożeniu poprawki

Właściciel zapisał nową centralną politykę Tailscale, a kontrola efektywnego PacketFilter na serwerze 28.10.2026 o 23:25 CET wykazała **PASS izolacji sieciowej shared peera**: tylko TCP 8443 do Magazynu, DENY 22/443/9090 i inne porty. Własne urządzenia zachowały dostęp. Produkcyjny Magazyn i Telegram bez przerw działają prawidłowo. Wcześniejsze ostrzeżenie o broad allow-all jest historyczne. Przed formalnym zamknięciem employee_access należy jeszcze potwierdzić działanie telefonu pracownika na NOWEJ polityce. Drugi YubiKey 5C wciąż niewdrożony. [Raport weryfikacyjny](MAGAZYN_TAILSCALE_AFTER_APPLY_2026-10-28_PL.md).
