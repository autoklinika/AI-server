# Magazyn V1 — aplikacja magazynowa (DEV)

**Status: implementacja DEV, bez wdrożenia produkcyjnego.** Samodzielne WebGUI, FastAPI i SQLite. Nie jest podłączona do Gateway, RM, Ollamy, GPU ani Vision.

Źródło wymagań: [Raport Magazyn V1](../../docs/reports/MAGAZYN_V1_RAPORT_USTALEN_2026-10-25_PL.md).

## Aktualnie działające

- Konta i sesje: indywidualne loginy, scrypt+salt, ciasteczko HttpOnly, SameSite, CSRF. Administrator ma pełne funkcje administracyjne, w tym edycję/usuwanie historii. Pracownik ma operacje podstawowe.
- Sterowniki i elektronika: jedna pozycja, wiele marek i numerów, wiele lokalizacji. ECU: Nowy/Używany oraz stan techniczny (Sprawny/Uszkodzony/Nieznany).
- Przyjęcie, wydanie z obowiązkowym powodem, przesunięcie i korekta z atomowym zapisem ilości i historii.
- Wyszukiwarka po oznaczeniach i numerach z normalizacją spacji, myślników i wielkości liter; filtrowanie.
- Minimalne stany magazynowe i lista „Do zamówienia”. Ustawienia odbiorcy powiadomień są przechowywane, ale powiadomienia jeszcze **nie są wysyłane**.
- **Inwentaryzacja**: `GET /api/inventory?location_id=N`, `POST /api/inventory`. Pracownik może przeglądać, administrator wprowadza policzone stany. W jednej transakcji powstają korekty; parametr `expected_quantity` chroni przed nadpisaniem nowszego stanu (409 Conflict).
- **CSV/XLSX**: eksport katalogu `GET /api/export?format=csv|xlsx&kind=ecu|part&brand=...`, szablon nowych pozycji `GET /api/import/template?format=csv|xlsx`, podgląd `POST /api/import/preview`, zatwierdzenie `POST /api/import/apply`. Wszystkie endpointy transferu wymagają administratora; POST wymagają CSRF. Import ma ograniczenie 1 MB / 1000 wierszy, walidację numerów/OEM/HW/SW, konflikty blokują całą transakcję; potwierdzenie podglądu ma krótką ważność i jest związane z plikiem i użytkownikiem. Żadnego automatycznego scalania z istniejącymi produktami.
- Eksport w formie migawki z wszystkimi lokalizacjami i wariantami stanów, także o ilości 0. Eksport i szablon **mają celowo różne nagłówki** — migawka katalogu nie jest automatycznym importem/backupem.

## Sposób uruchamiania wyłącznie do testów

Wymagany Python 3.12+, FastAPI, Pydantic 2, Uvicorn; testy wymagają pytest i httpx, XLSX wymaga **openpyxl** z [requirements-xlsx.txt](requirements-xlsx.txt). Instalować zależności tylko w osobnym wirtualnym środowisku DEV, nie w systemowym lub produkcyjnym Pythonie.

Z katalogu `apps/magazyn`:

```bash
export PYTHONPATH="$PWD"
export MAGAZYN_DB_PATH="/prywatny/katalog/testowy/magazyn.sqlite3"
python -m magazyn create-admin
python -m pytest tests/test_magazyn.py tests/test_inventory_transfers.py -q
MAGAZYN_COOKIE_SECURE=0 python -m magazyn run --host 127.0.0.1 --port 18765
```

Domyślnie cookie ma flagę Secure (wymagane HTTPS). Wartość `MAGAZYN_COOKIE_SECURE=0` wolno stosować **wyłącznie na loopback podczas testów**, nigdy na interfejsie publicznym. Uruchomienie CLI z `create-admin` pyta o hasło bez ujawniania go w parametrach procesu. Baza i hasła nie należą do repozytorium — GitHub jest publiczny.

### Format importu

- Plik CSV UTF-8 (BOM dozwolony) lub XLSX **jeden arkusz**, pierwszy wiersz musi odpowiadać szablonowi `magazyn-new-v1`.
- Każdy wiersz = **nowy** produkt, istniejąca lokalizacja, stan i ilość. Inne numery w `numbers_json` jako lista obiektów `{"number":"...","number_type":"OEM"}`. Dodatkowe marki w `brands_json` jako lista napisów.
- Dla ECU: `kind=ecu`, `product_state=new|used`, `technical_state=working|faulty|unknown`. Dla elektroniki: `kind=part`, oba pola stanów `na`.
- `quantity` jest liczbą całkowitą 0–2 000 000 000.
- Nieznana lokalizacja, ten sam numer w innym produkcie, powtórzenie w pliku albo niezgodny wariant produktu = błąd; import **nie zapisuje części danych**.
- Dla podglądu i zastosowania identyczny JSON `{"format":"csv","content_base64":"..."}`; dla zastosowania dodatkowo `token` zwrócony przez podgląd. WebGUI przygotowuje tę strukturę automatycznie.
- Arkusze XLSX z makrami, formułami i zewnętrznymi odwołaniami są odrzucane. Eksport neutralizuje wartości mogące zostać zinterpretowane jako formuły przez programy biurowe.

## Wynik testów

W DEV 26.10.2026: **52 / 52 testów PASS**, wraz z XLSX w izolowanym środowisku testowym z `openpyxl 3.1.5`. Testy tworzą wyłącznie syntetyczne pliki i bazy w katalogach tymczasowych, nie używają rzeczywistych stanów użytkownika. Dodatkowo wykonano kontrolę składni JS i kompilację Pythona.

## Niezaimplementowane, wymagane przed produkcją

- Powiadomienia o niskim stanie wyłącznie do wskazanego odbiorcy oraz prywatne zapytania przez Telegram i Discord, wraz z weryfikacją i powiązaniem kont.
- **Backup do GlobalNAS**, szyfrowanie, lokalne kolejki kopii, retencja 7 dziennych / 4 tygodniowe / 3 miesięczne, odtwarzanie i testy DR.
- Szyfrowanie danych bazy i audyt bezpieczeństwa wdrożenia, ograniczanie prób logowania, gotowe HTTPS/reverse proxy.
- Wygodna pełna edycja administracyjna w GUI, dodatkowe filtry historii oraz pełna walidacja ergonomii interfejsu.
- Aplikacja Android/OCR/zdjęcia — celowo poza V1.

## Niezmienniki bezpieczeństwa i integracji

Nie można wydać ani przesunąć większej ilości niż dostępna. Operacje ilościowe i historia są zapisywane atomowo. Jeden produkt widoczny pod kilkoma markami nie jest podwójnie liczony. Admin ma pełne możliwości; użytkownik nie ma dostępu do endpointów administracyjnych. Import i eksport nie ujawniają kont, sesji ani haseł. Magazyn pozostaje niezależny od usług AI Platform, nie tworzy unitów systemd, timerów, crona ani otwartych portów podczas tej fazy.

**Nie wdrażać na produkcję** przed odbiorem brakujących funkcji i testem odtwarzania z GlobalNAS.
