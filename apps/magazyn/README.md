# Magazyn V1 — aplikacja magazynowa (DEV)

**Status: implementacja DEV, bez wdrożenia produkcyjnego.** Samodzielne WebGUI, FastAPI i SQLite. Nie jest podłączona do Gateway, RM, Ollamy, GPU ani Vision.

Źródło wymagań: [Raport Magazyn V1](../../docs/reports/MAGAZYN_V1_RAPORT_USTALEN_2026-10-25_PL.md).

**Motyw WebGUI (27.10.2026):** pomarańczowy akcent `#B74B0D`, grafitowa nawigacja `#282D33` i neutralne szarości. Zmiana dotyczy wyłącznie stylów CSS oraz `theme-color`; układ, dane, konta i logika magazynu pozostają bez zmian. Kolory istotnych kontrolek mają test kontrastu WCAG AA.

## Aktualnie działające

- Konta i sesje: indywidualne loginy, scrypt+salt, ciasteczko HttpOnly, SameSite, CSRF. WebGUI ogranicza błędne logowania (5 na konto i połączenie / 5 min → 10 min przerwy; dodatkowy limit źródła 30 prób), przechowując w bazie wyłącznie skróty kluczy kontroli. Chroni przed przypadkowym usunięciem ostatniego aktywnego administratora. Administrator ma pełne uprawnienia funkcjonalne, w tym edycję/usuwanie historii. Pracownik ma operacje podstawowe.
- Sterowniki i elektronika: jedna pozycja, wiele marek i numerów, wiele lokalizacji. ECU: Nowy/Używany oraz stan techniczny (Sprawny/Uszkodzony/Nieznany).
- Przyjęcie, wydanie z obowiązkowym powodem, przesunięcie i korekta z atomowym zapisem ilości i historii.
- Wyszukiwarka po oznaczeniach i numerach z normalizacją spacji, myślników i wielkości liter; filtrowanie.
- Minimalne stany magazynowe i lista „Do zamówienia”. **Prywatne alerty** są atomowo zapisywane w kolejce dla konkretnie przypisanego użytkownika oraz Telegrama albo Discorda; brak dziedziczenia ustawień z kategorii i brak broadcastu. Wysyłka sieciowa jest w DEV domyślnie **wyłączona**.
- **Inwentaryzacja**: `GET /api/inventory?location_id=N`, `POST /api/inventory`. Pracownik może przeglądać, administrator wprowadza policzone stany. W jednej transakcji powstają korekty; parametr `expected_quantity` chroni przed nadpisaniem nowszego stanu (409 Conflict).
- **CSV/XLSX**: eksport katalogu `GET /api/export?format=csv|xlsx&kind=ecu|part&brand=...`, szablon nowych pozycji `GET /api/import/template?format=csv|xlsx`, podgląd `POST /api/import/preview`, zatwierdzenie `POST /api/import/apply`. Wszystkie endpointy transferu wymagają administratora; POST wymagają CSRF. Import ma ograniczenie 1 MB / 1000 wierszy, walidację numerów/OEM/HW/SW, konflikty blokują całą transakcję; potwierdzenie podglądu ma krótką ważność i jest związane z plikiem i użytkownikiem. Żadnego automatycznego scalania z istniejącymi produktami.
- Eksport w formie migawki z wszystkimi lokalizacjami i wariantami stanów, także o ilości 0. Eksport i szablon **mają celowo różne nagłówki** — migawka katalogu nie jest automatycznym importem/backupem.
- **Backup DEV:** szyfrowane archiwa SQLite AES-256-GCM, prywatny klucz, lokalny bufor, odtwarzanie offline i zabezpieczone sprawdzanie prawdziwego GlobalNAS przed wysyłką. Panel administratora pozwala podejrzeć kolejkę oraz wykonać ręczny lokalny backup. Instrukcja: [BACKUP_DEV.md](BACKUP_DEV.md). **27.10.2026: rzeczywisty zapis zaszyfrowanego archiwum na GlobalNAS i pełne odtworzenie z NAS do RAM PASS. Nie instalowano żadnego nowego timera; kopia klucza poza serwerem nadal wymagana.**
- **Komunikatory DEV:** osobne, domyślnie wyłączone adaptery Telegram polling i Discord Gateway, tylko prywatne wiadomości i tylko odczyt. Administrator generuje 10-minutowe, jednorazowe kody powiązania kont; powiązania można odwołać. Potwierdzone konta otrzymują powiadomienia z trwałej kolejki (retry po błędzie), bez wpływu na pracę magazynu. Instrukcja: [BOTS_DEV.md](BOTS_DEV.md). **Dedykowany Telegram DEV został już skonfigurowany, uruchomiony i odebrany w teście rzeczywistej wysyłki prywatnego alertu; nadal nie jest wdrożeniem produkcyjnym.** Bezpieczny instalator: [TELEGRAM_SETUP_DEV.md](TELEGRAM_SETUP_DEV.md).

## Sposób uruchamiania wyłącznie do testów

Wymagany Python 3.12+, FastAPI, Pydantic 2, Uvicorn; testy wymagają pytest i httpx, XLSX wymaga **openpyxl** z [requirements-xlsx.txt](requirements-xlsx.txt), a backup wymaga **cryptography** z [requirements-backup.txt](requirements-backup.txt). Integracje komunikatorów wymagają odrębnych pakietów wskazanych w [requirements-bots.txt](requirements-bots.txt). Instalować zależności tylko w osobnym wirtualnym środowisku DEV, nie w systemowym lub produkcyjnym Pythonie.

Z katalogu `apps/magazyn`:

```bash
export PYTHONPATH="$PWD"
export MAGAZYN_DB_PATH="/prywatny/katalog/testowy/magazyn.sqlite3"
python -m magazyn create-admin
python -m pytest tests -q
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

W DEV 27.10.2026: **132 / 132 testy PASS**, wraz z XLSX w izolowanym środowisku testowym z `openpyxl 3.1.5` i backupem AES-GCM z `cryptography 47.0.0`. Testy tworzą wyłącznie syntetyczne pliki i bazy w katalogach tymczasowych, nie używają rzeczywistych stanów użytkownika. Dodatkowo wykonano kontrolę składni JS i kompilację Pythona.

## Niezaimplementowane, wymagane przed produkcją

- **Telegram:** zakończono funkcjonalny test rzeczywistej wysyłki alertu do powiązanego konta, odbiór potwierdzony przez użytkownika. Zostaje odbiór operacyjny i zabezpieczenie danych przed produkcją. Discord jest odrębnym, opcjonalnym etapem.
- **Backup/DR:** rzeczywisty zapis, odczyt i restore z GlobalNAS zakończony PASS. Brakuje bezpiecznej kopii klucza poza serwerem, cyklicznej realizacji kopii przez istniejący mechanizm Stage K (bez nowego schedulera), monitoringu i procedury DR na produkcję.
- Ocena szyfrowania działającej bazy, przegląd bezpieczeństwa wdrożenia (w tym polityki loginów, sesji, sekretów), gotowe HTTPS/reverse proxy i dostęp do aplikacji dla pracowników. Ograniczanie prób logowania w DEV już działa.
- Wygodna pełna edycja administracyjna w GUI, dodatkowe filtry historii oraz pełna walidacja ergonomii interfejsu.
- Aplikacja Android/OCR/zdjęcia — celowo poza V1.

## Niezmienniki bezpieczeństwa i integracji

Nie można wydać ani przesunąć większej ilości niż dostępna. Operacje ilościowe i historia są zapisywane atomowo. Jeden produkt widoczny pod kilkoma markami nie jest podwójnie liczony. Admin ma pełne możliwości; użytkownik nie ma dostępu do endpointów administracyjnych. Import i eksport nie ujawniają kont, sesji ani haseł. Magazyn pozostaje niezależny od RM i modeli AI. W DEV istnieją dwie odrębne jednostki użytkownika systemd (WebGUI localhost i Telegram), bez autostartu i bez nowych timerów/crona. WebGUI nasłuchuje wyłącznie na 127.0.0.1:18765, dostęp przez tunel SSH.

**Nie wdrażać na produkcję** przed ukończeniem odbioru bezpieczeństwa, niezależnej kopii klucza szyfrowania, polityki harmonogramu przez Stage K i HTTPS. Sam test odtwarzania z GlobalNAS już zakończono PASS.
