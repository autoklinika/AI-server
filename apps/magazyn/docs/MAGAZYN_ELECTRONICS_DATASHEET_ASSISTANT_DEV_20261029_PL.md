# Magazyn V1 — asystent dokumentacji elektroniki (DEV)

29.10.2026. Status: kod na gałęzi DEV, bez wdrażania do produkcji.

## Jak działa

Po wpisaniu pełnego oznaczenia (np. LM358) asystent w istniejącym formularzu elektroniki po 1,1 s automatycznie wyszukuje kartę. Użytkownik wybiera zweryfikowanego producenta i dokument, a następnie poleca jego analizę. Program pokazuje propozycje uzupełnienia: producent, numer katalogowy, kategoria, obudowa, napięcie, prąd, moc, rezystancja, pojemność, tolerancja, liczba pinów, temperatura i interfejs. Każda propozycja zawiera fragment i numer strony PDF. Operator zaznacza pola, po czym zatwierdza zastosowanie. Nie ma samoczynnych zapisów stanów magazynowych.

Po zatwierdzeniu pobrany PDF można dołączyć do obecnego pola Dokumentacja techniczna. Samo dodanie dokumentacji i towaru nadal następuje normalnym przyciskiem Dodaj element. Nie modyfikujemy istniejącej bazy, mechanizmu duplikatów ani historii.

## Źródła dokumentacji

- Texas Instruments: bezpośredni oficjalny adres datasheet dla wspieranych rodzin, np. LM358. Źródło weryfikowane przy pobieraniu.
- Mouser: oficjalny Search API, jeżeli właściciel ustawi prywatny MAGAZYN_MOUSER_API_KEY na serwerze. Dla API nie skonfigurowanego prezentujemy brak wyniku, nie zgadujemy.
- LCSC: nieoficjalny interfejs sklepu wyłącznie dla kodów LCSC typu C668215, wyłączony domyślnie (MAGAZYN_DATASHEET_LCSC_EXPERIMENTAL=1). Może przestać działać.
- Własny PDF: przycisk Analizuj wybrany PDF z telefonu, bez pośrednika ani klucza API.
- Pozostali producenci: planowane źródła przez oficjalne API. Nie deklarujemy uniwersalnego wyszukiwania wszystkich elementów bez skonfigurowanych źródeł.

## Ograniczenia i zabezpieczenia

- PDF maksymalnie 8 MB, analiza tekstu pierwszych 6 stron, wymagane pełne oznaczenie MPN w dokumencie; skan bez warstwy tekstowej wymaga osobnego OCR.
- Jeden datasheet może opisywać rodzinę i odmiany o różnym napięciu/mocy/obudowie: parametry wariantowe nie są zaznaczane automatycznie (np. LM358 i LM358B).
- Wyszukiwanie wyłącznie po pełnym kodzie, bez zgadywania wartości na podstawie nadruków 10k/0603.
- Wszystkie zewnętrzne PDF wyłącznie z zatwierdzonych domen producentów/dystrybutorów, przez HTTPS, bez przekierowań lub dostępu do wewnętrznych adresów. Źródło wybierane przez token sesji użytkownika (TTL 10 min), nie dowolny URL od klienta.
- PDF analizowany w pamięci, nie zapisywany do bazy przed normalnym dodaniem części. Autoryzacja sesji i CSRF Magazynu obowiązują.
- Opcjonalny drugi przebieg AI na istniejącym AI Gateway i globalnym Resource Managerze: MAGAZYN_DATASHEET_AI_ENABLED=1 i MAGAZYN_DATASHEET_AI_MODEL=qwen3.8:27b. Wyłączony domyślnie. Wartości AI muszą mieć dosłowny dowód i zgodność cyfr z PDF.
- Brak nowych usług, schedulerów, migracji SQLite, zmian produkcyjnego RM i Telegrama.

## Testy

- Faktyczny PDF Texas Instruments LM358 (68 stron, ok. 4,15 MB), potwierdzenie, że doc opisuje także odmiany LM358B/BA i nie należy automatycznie przepisywać ich parametrów: PASS.
- Rzeczywisty Firefox na układzie 390x844 i odizolowana SQLite: LM358 -> auto wyszukiwanie -> analiza PDF -> potwierdzenie producenta/kategorii/oznaczenia -> dołączenie PDF do formularza -> brak zapisu bazy: PASS.
- Testy odrzucania złych URL, niezgodnych PDF, tokenów, CSRF, danych rodziny i braku mutacji magazynu: PASS.
- Odbiór na telefonie i sprawdzenie większej liczby prawdziwych części do wykonania przed produkcyjnym GO.

## Wdrożenie

Projekt wyłącznie na feature/magazyn-electronics-datasheets-dev-20261029. Zatwierdzony Magazyn Android V1.0.0 nadal działa bez zmian. Najpierw pilot na wielu prawdziwych oznaczeniach, potem ewentualne dołączenie licencjonowanego API dostawcy w prywatnej konfiguracji serwera.
