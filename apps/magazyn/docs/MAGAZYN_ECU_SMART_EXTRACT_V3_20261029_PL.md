# Magazyn V1 Android — szersza ekstrakcja danych ECU, V3

Data: 2026-10-29. Status: addytywny backend produkcyjny + Android APK z nowym podglądem.

## Dlaczego poprzednia wersja odrzucała dane

Pierwszy Qwen3-VL 8B Instruct OCR często zwracał prawidłową transkrypcję, lecz parser oparty głównie na regexach rozpoznawał tylko typowe Bosch/P-N/OEM i krótką listę modeli ECU. Numery bez opisów, zastosowanie, daty produkcji i numer seryjny nie trafiały do pól formularza. Przy samym numerze OEM dotychczasowe reguły wybierały go jako numer główny, nawet gdy osobny numer producenta widniał na etykiecie.

## Nowy schemat — dwa kroki na tym samym RTX

1. Vision OCR: zdjęcie z aparatu Android trafia przez Tailscale/HTTPS do Magazynu i istniejącego RM, a następnie do Qwen3-VL 8B Instruct na RTX 5060 Ti.
2. Drugi, tekstowy przebieg Qwen3-VL (na tym samym załadowanym modelu i dzierżawie RM) interpretuje transkrypcję jako JSON: producent, marka pojazdu, typ ECU, zastosowanie, numer główny, numery OEM i dostawcy, HW/SW, S/N, data produkcji i numery nieopisane.
3. Wszystkie numery sugerowane przez model muszą dosłownie występować w transkrypcji (z tolerancją spacji/myślników). Nieznane, niepewne lub niepotwierdzone etykietą powiązania zostają propozycjami wymagającymi zatwierdzenia.
4. Gdy drugi przebieg AI zwróci błąd lub niepoprawny JSON, działa wcześniejszy bezpieczny parser; nie dopisujemy sztuk i nie zmieniamy bazy bez zatwierdzenia.

## Rozszerzenie mobilnego formularza

- Po skanowaniu użytkownik widzi listę sugerowanych pól: numer katalogowy, producent ECU, nazwa produktu, marka pojazdu (tylko jawnie z etykiety), typ/model, zastosowanie, HW i SW.
- Przy jawnie opisanym OEM numer może trafić do dodatkowych numerów po zaakceptowaniu propozycji.
- Przy nieopisanych numerach dostępna jest osobna lista z podpowiedzią roli (producent/OEM/niezidentyfikowany), ale nie tworzy automatycznych aliasów.
- S/N i data produkcji mogą po potwierdzeniu trafić do Uwagi. Nie wpisujemy jednego S/N w historię wszystkich egzemplarzy ewidencji ilościowej bez ostrzeżenia.
- Pozycje z polem confidence=suggestion pozostają DOMYŚLNIE ODZNACZONE (np. kategoria z tekstu lub nieopisany numer katalogowy). Przyciski zatwierdzenia i odrzucenia są nad długą listą, a dolny pasek Zapisu jest ukryty podczas przeglądu.
- Formularz nigdy nie zapisuje samodzielnie operacji na stan magazynu.

## Testy i ograniczenia

- Prawdziwy RTX: dwa przebiegi Qwen3-VL w jednej rezerwacji RM. Test na dwóch poprawnych tekstowych transkrypcjach Bosch/Continental wykazał więcej sklasyfikowanych oznaczeń (HW, SW, OEM, typ ECU, marka gdy jawna, S/N i data). Drugi przebieg był osobnym wywołaniem modelu i podnosi latencję skanowania.
- Test obrazu 9-liniowej syntetycznej etykiety pokazał, że Vision OCR potrafi popełnić błędy na gęstym obrazie, co wpływa również na drugi przebieg. Nowa klasyfikacja NIE usuwa błędów samej transkrypcji; wymagane są rzeczywiste zdjęcia do walidacji.
- Testy Python (grounding, niedopuszczenie S/N jako numeru katalogowego, fallback, niestandardowe formaty) oraz JS mapping PASS.
- Firefox 158, mobilne 390×844, izolowane API i SQLite: nowe pole Zastosowanie, notes S/N/data, ręczne dodawanie nieopisanych numerów, ochrona przed nadpisaniem i zero zapisów bazy: PASS.
- Pełny zestaw testów Magazynu w izolacji: PASS. Build APK/Testy automatyczne: patrz workflow GitHub Actions.

## Produkcja i rollback

Nowy release produkcyjny: /srv/ai-data/magazyn-v1/releases/ecu-smart-extract-v3-20261029. Tylko nowy moduł ecu_smart_extract.py i zmiana ecu_rtx.py (dodatkowy przebieg na tym samym Qwen3-VL). Nie zmieniano innych endpointów, schematu SQLite, globalnego RM, usług Ollama, Telegrama i Tailscale. Po przełączeniu localhost i Tailscale HTTPS /healthz PASS, nieautoryzowany /api/ecu-label/status HTTP 401.

Poprzedni drop-in: /srv/ai-data/magazyn-v1/rollback/ecu-smart-extract-v3-20261029/80-ecu-ai-ocr.conf.before. Przy rollbacku przywrócić go do /home/harrypotter/.config/systemd/user/magazyn-webgui.service.d/80-ecu-ai-ocr.conf i wykonać systemctl --user daemon-reload oraz restart tylko magazyn-webgui.service (XDG_RUNTIME_DIR=/run/user/1000). NIE przywracać starej bazy SQLite.

## Dalsza weryfikacja

Potrzebny zestaw rzeczywistych naklejek ECU: co najmniej Bosch, Continental, Delphi oraz etykiety starte/małe. Porównać znak po znaku surową transkrypcję, wynik klasyfikacji i zatwierdzone pola formularza. Nie uznawać modelowych zgadywanek za rzeczywiste numery katalogowe.
