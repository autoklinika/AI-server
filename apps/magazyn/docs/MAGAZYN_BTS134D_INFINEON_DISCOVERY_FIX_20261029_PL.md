# Magazyn V1 — naprawa odkrywania dokumentacji BTS134D

29.10.2026. Zgłoszenie: po wpisaniu BTS134D w formularzu elementu elektronicznego nie było wyników, pomimo obecności w Mouser.

## Przyczyna

Dotychczasową automatyczną integrację z siecią ograniczono do publicznych PDF Texas Instruments. Mouser Search API jest dostępne tylko po podaniu osobnego klucza MAGAZYN_MOUSER_API_KEY, którego w produkcji nie skonfigurowano. Infineon BTS134D ma oficjalny datasheet i publiczną kartę produktu, ale serwerowy downloader PDF otrzymuje od Infineon HTTP 202/zero bajtów — nie jest to prawidłowo pobrany PDF.

## Rozwiązanie

- Dodatkowy dostawca Infineon nie wymaga klucza API. Obsługa rodzin BTS, BSP, BTF i innych znanych prefiksów oraz jawnie wybranego producenta Infineon. Nigdy nie zgadujemy wyniku po podobnym numerze.
- GET tylko z oficjalnego https://www.infineon.com/part/<MPN>; odczyt schema.org ProductGroup z HTML, weryfikacja pełnego SKU, ProductID, nazwy i URL. Maksymalny rozmiar HTML 3,5 MB, HTTPS, brak przekierowań.
- Analityka porównuje dokładny numer żądany z identyfikatorem ProductGroup. Odrzuca BTS134DX, BTS3134D i inne warianty o innych numerach.
- Sugerowane pola muszą mieć dosłowny dowód w właściwościach produktu: manufacturer, primary_number, category, spec_interface, spec_voltage (z opisem VDS max), spec_current (nominal), spec_power (Ptot max), spec_resistance (25°C), spec_temperature i package tylko jeżeli obudowa jest jednoznaczna dla wariantów.
- Strona Infineon podaje odnośnik do oryginalnego PDF. Gdy PDF nie jest dostępny do automatycznego pobrania, GUI pokazuje ten link, nie tworzy pustego załącznika i nie udaje analizy stron PDF.
- Automatycznie ładuje oficjalne dane jedynego znalezionego producenta, ale wypełnienie formularza wymaga Zastosuj zaznaczone pola, a dodanie magazynowe nadal wymaga Dodaj element.
- Nie zmieniamy Mouser API ani nie obchodzimy zabezpieczeń dostawcy. Użytkownik może dodać swój plik PDF ręcznie.

## BTS134D — zweryfikowane dane

Producent Infineon Technologies; DPAK; VDS max 42 V; prąd nominalny 3,5 A; Ptot max 43 W; RDS(on) 45 mΩ w temperaturze 25°C; temperatura -40 do 150°C. Wszystkie te wartości są udokumentowane na oficjalnej stronie producenta, nie wygenerowane przez LLM.

## Testy

- Rzeczywiste HTTPS Infineon: wyszukiwanie BTS134D ok. 0,35 s, ponowne pobranie i klasyfikacja ok. 0,30 s, bez klucza Mouser — PASS.
- Mobilny Firefox 390x844 + izolowany Magazyn FastAPI/SQLite: po wpisaniu BTS134D automatycznie pojawia się 10 propozycji pól i link do PDF. Po Zastosuj trafiają one do właściwych pól, bez fikcyjnego załącznika i bez zapisu produktu/stanu — PASS.
- Testy jednostkowe: fałszywe ProductGroup, błędne numery, różne obudowy, konflikt producenta, autoryzacja/CSRF oraz brak automatycznych zapisów — PASS.
- Pełna regresja Magazynu i CI GitHub Actions, finalny odbiór produkcyjny oddzielnie.

## Produkcja / rollback

Nowa implementacja to tylko part_infineon.py, integracja w part_datasheets.py oraz poprawki part_datasheets.js. Brak migracji i nowych usług, zmiany nie dotykają Telegrama, Resource Managera, danych magazynowych i aplikacji Android APK. Należy wykonać addytywny release i zachować poprzedni drop-in do rollbacku.
