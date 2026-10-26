# Magazyn V1 — aplikacja magazynowa (DEV)

**Status: etap rozwoju / niewdrożona.** Samodzielna aplikacja WebGUI, API i SQLite, odseparowana od produkcyjnej AI Platform. Nie jest podłączona do Gateway, RM, Ollamy, GPU ani Vision.

Pełna specyfikacja: ../../docs/reports/MAGAZYN_V1_RAPORT_USTALEN_2026-10-25_PL.md

## Zaimplementowane w pierwszym przyroście

- Indywidualne konta i sesje, scrypt z solą, HttpOnly/SameSite i token CSRF.
- Administrator zarządza użytkownikami, lokalizacjami, katalogiem, historią oraz minimami; pracownik wykonuje podstawowe operacje.
- Ewidencja ECU i elektroniki, stany Nowy/Używany oraz Sprawny/Uszkodzony/Nieznany dla ECU.
- Wielolokalizacyjne stany, atomowe przyjęcia, wydania, przenoszenia, korekty i rejestrowanie autora.
- Wiele numerów katalogowych i marek przypisanych do jednej pozycji. Wyszukiwarka toleruje spacje, myślniki i części numerów.
- Prosty responsywny panel WebGUI: katalog, wyszukiwanie, stany, historia, minima i podstawowa administracja.
- Zatwierdzony proces wydania z powodem, opcjonalnym numerem zlecenia i podglądem bilansu.
- Osobne API przygotowane pod kolejne interfejsy.

## Jeszcze NIE zaimplementowane

- Import/eksport CSV i XLSX oraz osobny ekran inwentaryzacji.
- Telegram i Discord: prywatne zapytania, parowanie kont, wysyłka alertów.
- Automatyczny backup do GlobalNAS, lokalny bufor, retencja 7/4/3, szyfrowanie i odtwarzanie.
- Szyfrowanie danych bazy i pełny audyt bezpieczeństwa, rate limiting logowania, HTTPS/reverse proxy.
- Wygodna edycja wszystkich danych i historii w WebGUI (część operacji admina jest już w API).
- Aplikacja Android, OCR i zdjęcia — świadomie poza V1.

## Uruchomienie tylko w DEV

Wymagany Python 3.12+, FastAPI, Pydantic 2, Uvicorn. Do testów: pytest, httpx.

Z katalogu apps/magazyn:

    export PYTHONPATH="$PWD"
    export MAGAZYN_DB_PATH="/prywatna/bezpieczna/sciezka/magazyn.sqlite3"
    python -m magazyn create-admin
    python -m pytest tests -q
    MAGAZYN_COOKIE_SECURE=0 python -m magazyn run --host 127.0.0.1 --port 18765

Używaj oddzielnego środowiska wirtualnego, nie modyfikuj systemowego lub produkcyjnego Pythona. Domyślnie ciasteczka mają flagę Secure (wymagają HTTPS); wyłączenie tylko jawnie na loopback przy testach. Nie publikować portu na LAN/Internet. Baza danych oraz sekrety muszą pozostawać poza repozytorium.

## Niezmienniki

- Przyjęcia i wydania nie mogą doprowadzić do ujemnych stanów.
- Operacja stanu oraz wpis historii są transakcyjne.
- Transfer między lokalizacjami nie zmienia sumy globalnej.
- Wpisy wielu marek nie podwajają fizycznej ilości.
- Bez sesji brak dostępu do stanów, zły CSRF blokuje zapisy.
- Administrator ma pełne prawa, w tym edycję/usuwanie historii.
- Brak integracji z produkcyjnym RM i jakichkolwiek usług systemd.

Przed produkcją należy wykonać kolejne etapy i testy odbiorowe z raportu.
