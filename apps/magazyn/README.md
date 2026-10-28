# Magazyn V1 — aplikacja magazynowa (DEV)

**Status: implementacja DEV, bez wdrożenia produkcyjnego.** Samodzielne WebGUI, FastAPI i SQLite. Nie jest podłączona do Gateway, RM, Ollamy, GPU ani Vision.

Źródło wymagań: [Raport Magazyn V1](../../docs/reports/MAGAZYN_V1_RAPORT_USTALEN_2026-10-25_PL.md).

**Motyw WebGUI (27.10.2026):** pomarańczowy akcent `#B74B0D`, grafitowa nawigacja `#282D33` i neutralne szarości. Zmiana dotyczy wyłącznie stylów CSS oraz `theme-color`; układ, dane, konta i logika magazynu pozostają bez zmian. Kolory istotnych kontrolek mają test kontrastu WCAG AA.

## Aktualnie działające

- Konta i sesje: indywidualne loginy, scrypt+salt, ciasteczko HttpOnly, SameSite, CSRF. WebGUI ogranicza błędne logowania (5 na konto i połączenie / 5 min → 10 min przerwy; dodatkowy limit źródła 30 prób), przechowując w bazie wyłącznie skróty kluczy kontroli. Chroni przed przypadkowym usunięciem ostatniego aktywnego administratora. Administrator ma pełne uprawnienia funkcjonalne, w tym edycję/usuwanie historii. Pracownik ma operacje podstawowe.
- Sterowniki i elektronika: odrębne formularze, jedna pozycja, wiele marek/numerów i lokalizacji. ECU zachowuje HW/SW, Nowy/Używany oraz stan techniczny. Elektronika ma własne pola parametrów, obudowę i dokumentację techniczną PDF/PNG/JPG dołączaną do SQLite. Stan zakupu Zamówione nie zwiększa stanów towaru.
- Przyjęcie, wydanie z obowiązkowym powodem, przesunięcie i korekta z atomowym zapisem ilości i historii.
- Wyszukiwarka po oznaczeniach i numerach z normalizacją spacji, myślników i wielkości liter; filtrowanie.
- Minimalne stany magazynowe i lista „Do zamówienia”. **Prywatne alerty** są atomowo zapisywane w kolejce dla konkretnie przypisanego użytkownika oraz Telegrama albo Discorda; brak dziedziczenia ustawień z kategorii i brak broadcastu. Wysyłka sieciowa jest w DEV domyślnie **wyłączona**.
- **Inwentaryzacja**: `GET /api/inventory?location_id=N`, `POST /api/inventory`. Pracownik może przeglądać, administrator wprowadza policzone stany. W jednej transakcji powstają korekty; parametr `expected_quantity` chroni przed nadpisaniem nowszego stanu (409 Conflict).
- **CSV/XLSX**: eksport katalogu `GET /api/export?format=csv|xlsx&kind=ecu|part&brand=...`, szablon nowych pozycji `GET /api/import/template?format=csv|xlsx`, podgląd `POST /api/import/preview`, zatwierdzenie `POST /api/import/apply`. Wszystkie endpointy transferu wymagają administratora; POST wymagają CSRF. Import ma ograniczenie 1 MB / 1000 wierszy, walidację numerów/OEM/HW/SW, konflikty blokują całą transakcję; potwierdzenie podglądu ma krótką ważność i jest związane z plikiem i użytkownikiem. Żadnego automatycznego scalania z istniejącymi produktami.
- Eksport w formie migawki z wszystkimi lokalizacjami i wariantami stanów, także o ilości 0. Eksport i szablon **mają celowo różne nagłówki** — migawka katalogu nie jest automatycznym importem/backupem.
- **Backup DEV:** szyfrowane archiwa SQLite AES-256-GCM, prywatny klucz, lokalny bufor, odtwarzanie offline i zabezpieczone sprawdzanie prawdziwego GlobalNAS przed wysyłką. Panel administratora pozwala podejrzeć kolejkę oraz wykonać ręczny lokalny backup. Instrukcja: [BACKUP_DEV.md](BACKUP_DEV.md). **27.10.2026: rzeczywisty zapis zaszyfrowanego archiwum na GlobalNAS i pełne odtworzenie z NAS do RAM PASS. Fizyczny test odzyskania AES key przez YubiKey/PIN PASS. Adapter Magazynu DEV jest podłączony do istniejących user-service Stage K; test ręczny i usługi monitora PASS, daily/weekly z timera oczekują na potwierdzenie. Nie instalowano nowego timera.** Szczegóły: [Stage K DEV](docs/MAGAZYN_STAGE_K_BACKUP_INTEGRATION_DEV_2026-10-27_PL.md).
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

W DEV 27.10.2026, po wdrożeniu obsługi drugiego pracownika: **210 / 210 testów PASS** (w tym testy Stage K, offline escrow, historii, DR i mobilnego WebGUI), wraz z XLSX w izolowanym środowisku testowym z `openpyxl 3.1.5` i backupem AES-GCM z `cryptography 47.0.0`. Testy tworzą wyłącznie syntetyczne pliki i bazy w katalogach tymczasowych, nie używają rzeczywistych stanów użytkownika. Dodatkowo wykonano kontrolę składni JS i kompilację Pythona.

## Niezaimplementowane, wymagane przed produkcją

- **Telegram:** zakończono funkcjonalny test rzeczywistej wysyłki alertu do powiązanego konta, odbiór potwierdzony przez użytkownika. Zostaje odbiór operacyjny i zabezpieczenie danych przed produkcją. Discord jest odrębnym, opcjonalnym etapem.
- **Backup/DR:** rzeczywisty zapis, odczyt i restore z GlobalNAS zakończony PASS. Zaszyfrowana publicznym kluczem istniejącego YubiKeya 5C kopia AES key jest na NAS; **fizyczne odszyfrowanie YubiKey/PIN, weryfikacja klucza i ponowny restore z backupu — PASS 27.10.2026**. Magazyn DEV jest podłączony do istniejących timerów Stage K, przy czym odbiór automatycznych uruchomień daily/weekly wciąż trwa. Nadal brak niezależnego klucza awaryjnego na wypadek utraty jedynego YubiKeya. [Raport YubiKey](docs/MAGAZYN_YUBIKEY_RECOVERY_2026-10-27_PL.md).
- Ocena szyfrowania działającej bazy i końcowy przegląd bezpieczeństwa. HTTPS Tailscale Serve DEV działa na :8443 bez dostępu publicznego, lecz docelowe uprawnienia sieciowe pracowników i wybór dostępu z LAN wymagają zatwierdzenia. Ograniczanie prób logowania w DEV już działa.
- Edycja wpisów historii, filtry po użytkowniku/produkcie/datach oraz wybór kopii do bezpiecznego testu odtworzenia w RAM są już w DEV i testowane. Pozostaje pełna walidacja ergonomii i właściwa procedura przełączenia po katastrofalnym restore.
- Aplikacja Android/OCR/zdjęcia — celowo poza V1.

## Niezmienniki bezpieczeństwa i integracji

Nie można wydać ani przesunąć większej ilości niż dostępna. Operacje ilościowe i historia są zapisywane atomowo. Jeden produkt widoczny pod kilkoma markami nie jest podwójnie liczony. Admin ma pełne możliwości; użytkownik nie ma dostępu do endpointów administracyjnych. Import i eksport nie ujawniają kont, sesji ani haseł. Magazyn pozostaje niezależny od RM i modeli AI. W DEV istnieją dwie odrębne jednostki użytkownika systemd (WebGUI localhost i Telegram), bez autostartu i bez nowych timerów/crona. WebGUI nasłuchuje wyłącznie na 127.0.0.1:18765, dostęp przez tunel SSH.

**Nie wdrażać na produkcję** przed ukończeniem odbioru bezpieczeństwa, niezależnej strategii na utratę jedynego YubiKeya, automatycznego backupu przez Stage K i HTTPS. Testy fizycznego odzyskania klucza przez YubiKey i odtworzenia bazy z GlobalNAS już zakończono PASS.


## Integracja DEV — aktualizacja 27.10.2026

- Automatyczne kopie Magazynu DEV są podłączone do istniejących timerów Stage K przez trzy izolowane drop-in; monitor godzinny wywołany przez timer zakończył się PASS. Na odbiór automatycznego daily/weekly trzeba poczekać do ich rzeczywistych uruchomień. Bez nowych schedulerów.
- **HTTPS DEV dostępne w Tailscale:** https://ai-server.tail759e12.ts.net:8443/ — port oddzielny od dotychczasowego panelu AI Platform. Sieć LAN bez Tailscale nie uzyska dostępu tą drogą; obowiązuje konto Magazynu i odpowiednie zasady dostępu tailnet.
- Panel administratora obsługuje filtry i edycję historii oraz test odtworzenia archiwum z NAS w RAM, bez nadpisywania działającej bazy.
- Zaimplementowano szyfrowanie kopii AES key do **zewnętrznego publicznego recipienta age X25519**; odbiór kryptograficzny na syntetycznych danych PASS. Faktyczny test niezależnego urządzenia wymaga dostarczenia publicznego odbiorcy z tego urządzenia — prywatnego klucza nie wprowadzamy na AI Server.
- Raport i rollback: [DEV release readiness 27.10.2026](docs/MAGAZYN_DEV_RELEASE_READINESS_2026-10-27_PL.md).


## Mobilne WebGUI — etap DEV 27.10.2026

Dotychczasowy WebGUI jest responsywny pod telefon (bez osobnej aplikacji):
dolna nawigacja z właściwą widocznością roli, wyszukiwarka i szybkie operacje dostępne przed statystykami, widoczne przyciski „+ Przyjmij” i „− Wydaj”, większe kontrolki iOS, mobilne karty historii i inwentaryzacji, bez poziomego przewijania. Formularz wydania nadal wymaga powodu, a zmiana użytkownika czyści dane wcześniejszego logowania. Kolorystyka i układ desktop pozostały bez zmian.

Testy: Firefox headless + WebDriver BiDi na odrębnej syntetycznej SQLite (390×844, 320×700 i 1440×900), 4 testy kontraktu UI, pełny pytest 163/163 PASS. Realne Safari iOS wymaga jeszcze krótkiego odbioru użytkownika. Zrzuty wyłącznie syntetycznych danych trzymane są poza repozytorium.

Raport: [Mobilne WebGUI DEV](docs/MAGAZYN_MOBILE_WEBGUI_DEV_2026-10-27_PL.md).


## Elektronika — dokumenty i status zakupu (DEV, 27.10.2026)

- Dwa osobne okna dodawania: ECU (marka, HW/SW, Nowy/Używany, sprawność) oraz Elektronika (kategoria, obudowa, napięcie, prąd, moc, rezystancja, pojemność, tolerancja, liczba pinów, temperatura, interfejs).
- Załączniki elektroniki: karty katalogowe i schematy PDF/PNG/JPG, przechowywane w tym samym SQLite, atomowo uwzględniane w zaszyfrowanych kopiach. Limit 8 MiB pliku, 6 dokumentów/element, 256 MiB magazynu.
- Status „Zamówione” z ilością i notatką, bez zwiększania stanu magazynu, widoczny przy produkcie i na liście „Do zamówienia”. Zmianę statusu wykonuje administrator.
- Addytywny schemat v3, istniejące produkty pozostają nienaruszone. Raport: [Elektronika / Dokumenty / Zamówione](docs/MAGAZYN_ELECTRONICS_DOCS_ORDER_DEV_2026-10-27_PL.md).
- Testy całej aplikacji: **183/183 PASS** na syntetycznych bazach. Firefox mobile 390 px: rzeczywiste utworzenie elementu z parametrami, załącznikiem i statusem Zamówione oraz sprawdzenie listy zakupów PASS. Nie wprowadzono syntetycznych produktów do rzeczywistego magazynu.

## Poprawka pierwszego przyjęcia (DEV, 27.10.2026)

W pustym magazynie przycisk zapisu był niedostępny, ponieważ nie istniała lokalizacja. Administrator może obecnie podać kod pierwszego miejsca (np. A1) bezpośrednio w formularzu ECU lub elektroniki, a kliknięcie **Dodaj** tworzy miejsce, produkt i przyjęcie w jednej transakcji. Nie powstaje automatycznie wymyślona lokalizacja. Użytkownik bez roli administratora nadal nie tworzy miejsc. Przypadki błędne nie pozostawiają osieroconych lokalizacji. Testy Magazynu 183/183 PASS, browser Firefox mobile 390 px PASS. [Raport poprawki](docs/MAGAZYN_FIRST_LOCATION_RECEIPT_FIX_2026-10-27_PL.md).

## Podgląd dokumentów w modalu (DEV, 27.10.2026)

W szczegółach elektroniki można kliknąć **Podgląd** przy dokumentacji PDF/PNG/JPG bez opuszczania Magazynu. Natywna przeglądarka PDF działa wewnątrz modalu, a obrazy można powiększać; **Pobierz** jest nadal dostępne. Plik jest odczytywany przez zabezpieczone API do tymczasowego blob: przeglądarki, usuwanego po zamknięciu okna. Brak zmian bazy, Telegrama i backupów. Testy całego Magazynu: **183/183 PASS**; Firefox mobile PDF + PNG i zwolnienie zasobów: PASS. Safari iPhone do odbioru użytkownika. [Szczegóły i rollback](docs/MAGAZYN_DOCUMENT_MODAL_PREVIEW_DEV_2026-10-27_PL.md).

## UAT operacji, zamówień, DR i bramka produkcyjna — 27.10.2026

Magazyn DEV ma zweryfikowany pełny obieg operacji magazynowych oraz **atomowe częściowe i pełne przyjęcie zamówionej dostawy** z poziomu panelu administratora (stan magazynowy, historia i zamówienie w jednej transakcji). Testy backendu, uprawnień, prywatnych alertów i przeglądarki mobilnej PASS, łącznie **198/198 testów PASS**. Rzeczywisty szyfrowany backup danych i załączników z GlobalNAS odtworzono w RAM i porównano ze źródłem (PASS).

**Produkcja: NO-GO do zamknięcia trzech warunków**: drugi fizyczny niezależny klucz odzyskiwania, potwierdzenie rzeczywistego automatycznego wywołania daily Magazynu po integracji oraz sprawdzenie Tailscale ACL pracowników. Tygodniowy Stage K został naprawiony 27.10: pełny backup, trzy restore i monitor PASS; kolejne regularne wywołanie w niedzielę 01.11 o 03:30 CET. Raport: [Naprawa harmonogramu Stage K](docs/MAGAZYN_STAGE_K_SCHEDULE_REPAIR_2026-10-27_PL.md). Automatyczny audyt bez możliwości wykonania wdrożenia: `python -m magazyn.release_gate`. Rozdział szczegółowy: [Etapy 1–4: testy, bramki produkcyjne i rollback](docs/MAGAZYN_V1_STAGE_1_4_RELEASE_UAT_2026-10-27_PL.md).

## Niezależne odzyskiwanie przez szyfrowany USB — pakiet Windows (2026-10-28)

Przygotowano jeden pakiet [MAGAZYN_RECOVERY_USB_WINDOWS.zip](recovery/windows/MAGAZYN_RECOVERY_USB_WINDOWS.zip) do wykonania na komputerze Windows Pro/Enterprise/Education: BitLocker To Go, generowanie nowego age X25519 wyłącznie na fizycznym pendrivie, kopiowanie zaszyfrowanych archiwów .mgzb i escrow .age z GlobalNAS, niezależny test i opcjonalne odtworzenie SQLite na USB. [Instrukcja krok po kroku](recovery/windows/README_PL.md). Pełna regresja Magazynu i narzędzi: **210/210 PASS**, w tym 10 testów offline kit (syntetyczny AES, prawdziwe age CLI, restore SQLite z dokumentacją). **Fizyczny pendrive: PENDING**, Windows/BitLocker nie testowano jeszcze na komputerze użytkownika. Dotychczasowy YubiKey 5C i automatyczny backup pozostają niezmienione; drugi YubiKey 5C zostanie dodany osobno po dostawie.

## Drugie konto pracownika — DEV 28.10.2026

Panel administracyjny Ustawienia → Użytkownicy → **Dodaj pracownika** tworzy oddzielne konto z rolą `user` i własnym hasłem. Nie ma przypadkowego wyboru roli administratora. Pracownik widzi Produkty, Do zamówienia, Inwentaryzację i Historię; może przyjmować, wydawać i przesuwać towar, ale backend odrzuca operacje administracyjne, backupy i zmianę kont. Historia zapisuje login pracownika. Administrator może zablokować/reaktywować konto i zmienić login; blokada natychmiast unieważnia sesję.

Testy: **210/210 PASS**, w tym rzeczywisty Firefox 390×844 i 1440×900 (admin tworzy pracownika → pracownik loguje się → wykonuje wydanie → admin blokuje). Bez zmian schematu SQLite ani usług Telegram. Nie dodano prawdziwego pracownika, bo jego login i hasło należy utworzyć bezpośrednio w WebGUI administratora. Dostęp pracownika przez własne urządzenie Tailscale/ACL pozostaje do odbioru. [Raport i instrukcja](docs/MAGAZYN_SECOND_EMPLOYEE_DEV_2026-10-28_PL.md).

## Zmiana hasła pracownika i testy dostępu Windows 11 — 28.10.2026

W górnym pasku WebGUI dostępna jest kłódka **Zmień moje hasło**. Endpoint wymaga obecnego hasła, sesji oraz CSRF; po zmianie hasła kasowane są wszystkie dotychczasowe sesje użytkownika. Administrator może użyć przy pracowniku **Resetuj hasło** z potwierdzeniem; reset też kończy sesje tego konta. Role i konta innych użytkowników pozostają nienaruszone. [Instrukcja odbioru Windows 11 i rollback](docs/MAGAZYN_EMPLOYEE_PASSWORD_WIN11_TESTS_2026-10-28_PL.md). Pełny zestaw testów Magazynu: **216/216 PASS**. Przeglądarka Firefox 390×844, 320×700 i 1440×900: oba modale i uprawnienia PASS. **Win11 Edge/Chrome na prawdziwym koncie: oczekuje na odbiór pracownika.**

## Magazyn V1 — produkcja uruchomiona 28.10.2026

Na wyraźne polecenie właściciela Magazyn został przełączony z DEV na **wersjonowane usługi produkcyjne**. Zamrożony kod: commit `529af02029e1`; 220/220 testów PASS, nowy izolowany runtime; `magazyn-webgui.service` i `magazyn-telegram.service` aktywne i enabled, stare DEV zatrzymane. Baza produkcyjna zachowuje dwa konta, stany, dokumenty i historię; stare sesje wygaszono w celu wymuszenia cookies Secure. Adres HTTPS Tailscale :8443 bez zmian. Backup AES-256 na GlobalNAS, restore/verify i monitor Stage K PASS; nie tworzono nowych schedulerów.

**Ważne:** Produkcja działa operacyjnie, ale formalna bramka pozostaje `NO_GO` przez brak drugiego fizycznego YubiKeya 5C i niedokończony niezależny audyt Tailscale ACL/Grants. Nie nazywaj wydania w pełni certyfikowanym przed ich zaliczeniem. [Pełny raport, wyjątki i rollback bez cofania danych](docs/MAGAZYN_V1_PRODUCTION_GO_LIVE_2026-10-28_PL.md).
