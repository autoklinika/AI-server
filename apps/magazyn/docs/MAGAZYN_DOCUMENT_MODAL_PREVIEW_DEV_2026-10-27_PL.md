# Magazyn V1 — podgląd dokumentacji w oknie modalnym (DEV)

**Data:** 27.10.2026. **Gałąź:** feature/magazyn-v1-dev-20261026. **Zakres:** wyłącznie podgląd już istniejących załączników elektroniki w WebGUI, bez nowych usług i bez zmian bazy.

## Funkcjonalność

W szczegółach elementu elektronicznego przy każdym załączniku PDF, JPG i PNG są dwa działania:

- **Podgląd**: otwiera osobne, natywne okno modalne wewnątrz Magazynu, ponad oknem produktu. Obrazy JPG/PNG można powiększać (100–400%) i dopasować. PDF wyświetlany jest przez wbudowaną przeglądarkę dokumentów. Okno zawiera nazwę pliku i przycisk zamykania.
- **Pobierz**: pozostaje dotychczasowy przycisk pobierający załącznik przez chronione API. W podglądzie również jest „Pobierz plik” jako rozwiązanie awaryjne, gdy przeglądarka nie obsługuje osadzania PDF.

Nie zmieniono sposobu przesyłania i przechowywania dokumentacji. PDF i obrazy pozostają w BLOB SQLite, automatyczny zaszyfrowany backup Stage K nadal obejmuje pliki. Nie użyto zewnętrznego serwisu PDF, CDN, modeli LLM, GPU ani nowej biblioteki.

## Bezpieczeństwo i prywatność

- Podgląd korzysta z istniejącego endpointu uwierzytelnionego GET /api/items/{item_id}/documents/{document_id}; niezalogowani otrzymują HTTP 401. Nadal stosowane są nosniff, no-store i Content-Disposition: attachment.
- Klient pobiera dokument przez same-origin fetch z aktualną sesją, weryfikuje dopuszczalny MIME (application/pdf, image/png, image/jpeg) oraz rozmiar, tworzy tymczasowy adres blob:, a po zamknięciu usuwa go przez URL.revokeObjectURL.
- Oczekujące pobranie jest anulowane przez AbortController, także przy zamknięciu lub zmianie sesji. Dane nie są zapisywane w nowym katalogu ani lokalnym magazynie przeglądarki.
- CSP nadal blokuje obiekty i zewnętrzne źródła skryptów. Dozwolono blob: jedynie dla ramek podglądu i obrazów; API nie wymaga trybu „inline”.
- Ramka PDF używa sandbox z allow-scripts oraz allow-same-origin, ponieważ browser-native PDF renderer bez tych uprawnień nie renderował stron w Firefox. Nie dopuszcza nawigacji najwyższego poziomu, popupów ani formularzy. Pliki PDF są wcześniej walidowane przy zapisie. Funkcja nie zastępuje pełnego skanowania bezpieczeństwa PDF.

## Testy

- Nowe testy backendu oraz HTML/CSS/JS: 3 PASS (modal, sterowanie, reguły CSP, zachowanie uwierzytelniania i możliwości pobierania).
- Pełny pakiet Magazynu: **183/183 PASS**. Składnia JS/Python oraz git diff check: PASS.
- Browser Firefox headless / WebDriver BiDi na syntetycznej SQLite: otwarcie PDF w modalu 390 px, rzeczywiste wyświetlenie zawartości PDF, pobranie PNG i powiększanie, zamykanie modalów, czyszczenie obu adresów blob:, pozostawienie niezmienionych danych magazynowych, test desktop — PASS.
- Zrzuty z danymi syntetycznymi przechowywane poza repozytorium: /srv/ai-data/staging/magazyn-mobile-ui-dev-20261027/screenshots/ (pliki document-preview-*).
- Safari iPhone: **do ręcznego potwierdzenia** w rzeczywistym środowisku przez użytkownika, szczególnie przewijanie wielostronicowego PDF. W razie ograniczeń przeglądarki zawsze można użyć „Pobierz plik”.

## Uruchomienie DEV i rollback

Statyczne pliki WebGUI są podawane przez istniejącą usługę magazyn-webgui-dev.service, bez dodatkowego procesu. Zmiana nagłówka CSP w Python wymaga restartu **tylko tej usługi**. Potwierdzić po restarcie HTTPS, działający Telegram DEV, zdrową bazę (SQLite integrity_check) i obecność nowego przycisku. Nie wykonywać operacji na produktach i załącznikach testowych w realnym Magazynie.

W razie problemów można cofnąć wyłącznie commit WebGUI/CSP i zrestartować magazyn-webgui-dev.service. Nie ma migracji bazy ani dodatkowej konfiguracji sieci do wycofania. Repozytorium main i produkcja AI Platform pozostają bez zmian.

**Adres:** https://ai-server.tail759e12.ts.net:8443/ — z włączonym Tailscale.
