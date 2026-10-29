# Magazyn V1 — poprawa mapowania pól etykiet ECU

Data: 2026-10-29. Zakres: Android WebView + parser transkrypcji na serwerze; bez migracji SQLite.

## Problem wykryty w kodzie

- Model Qwen3-VL poprawnie transkrybował etykiety, ale mostek Androida automatycznie wypełniał jedynie pięć pól: numer główny, producent, model, HW, SW.
- Pomijał obowiązkową nazwę/oznaczenie produktu, markę pojazdu (nawet gdy jawnie występowała na etykiecie) i dodatkowe numery OEM.
- Seryjny, numer główny i OEM nie miały wystarczająco odrębnych reguł klasyfikacji.
- Po kolejnym skanie helper fillWhenEmpty odmawiał aktualizacji istniejących wartości, bez podglądu i poprawnej kontroli użytkownika.
- W mobilnym dialogu przyciski podglądu potrafiły zostać zasłonięte dolnym sticky footer.

## Naprawa

- Nowy moduł ecu_label_fields.py: typowane wyodrębnienie Bosch / P-N / OEM / HW / SW / serial; wykrywanie konfliktów, zachowanie numerów w kandydatach, bez zgadywania znaków.
- Producent sterownika jest oddzielony od marki pojazdu; marka może zostać zasugerowana jedynie po bezpośredniej, jednoznacznej informacji na etykiecie.
- Nazwa/oznaczenie produktu powstaje z jawnego producenta i rozpoznanego typu ECU (np. Bosch EDC17C46), bez wnioskowania o zastosowaniu pojazdu.
- Dodatkowe OEM tylko z jawnych oznaczeń OEM; numery seryjne i kody bez typu nie są automatycznie aliasami produktu.
- Nowy ecu-form-mapping.js rozdziela dane na faktyczne nazwy pól obecnego WebGUI; obsługuje wielowierszowe OEM i zachowuje ręczne wpisy.
- Android nie wpisuje propozycji automatycznie. Pokazuje podgląd z zaznaczanymi polami, możliwością edycji i wyborem numeru głównego spośród kandydatów; dopiero Zastosuj przenosi zatwierdzone pola.
- Gdy pole miało wcześniejszą wartość, sugerowane nadpisanie jest domyślnie odznaczone; zapis magazynowy jest blokowany, dopóki użytkownik nie zastosuje lub nie odrzuci wyniku.
- Zatwierdzenie przeniesione na początek podglądu, nad dolnym paskiem formularza.
- Endpointy AI wymagają mapping_version=2. Starsze APK nie aktywują RTX i wracają do lokalnego OCR, zamiast używać starych zasad mapowania.

## Testy

- Python: test_ecu_label_fields.py obejmuje Bosch, Continental, OEM, HW/SW na jednej linii, S/N, konflikty cyfr, brand tylko jawny i brak domysłów.
- Node: test-ecu-form-mapping.cjs sprawdza mapowanie do istniejących pól, aliasy OEM, ochronę wpisanych danych, brak seryjnego oraz brak sklejenia OCR z następną linią.
- Rzeczywisty Firefox 158, ekran mobilny 390x844, izolowany FastAPI i SQLite: BEFORE_APPLY puste pola, podgląd wszystkich odpowiednich wartości, AFTER_APPLY właściwe pola, blokada zapisu przed weryfikacją, drugi skan nie nadpisuje danych: PASS.
- Wszystkie testy Magazynu na odizolowanym środowisku testowym: PASS; GitHub Actions kompiluje APK i uruchamia testy parsera.

## Bezpieczeństwo i wdrożenie

- Brak zmian w RM, Ollamie, GPU, Tailscale, Telegramie, backupach i schemacie bazy.
- Backend: nowy release serwera wyłącznie z modułem klasyfikacji, ecu_ai.py i minimalną zmianą server.py; pozostaje możliwość powrotu do poprzedniej wersji przez pojedynczy systemd drop-in.
- Android: nowy testowy APK z podglądem; odinstalowanie starszego debug APK może być wymagane z powodu podpisu wydawniczego.
- Nie deklarować skuteczności na każdej naklejce, dopóki nie wykonamy testów na rzeczywistych fotografiach. OCR/VLM może nadal błędnie odczytać znak; dlatego użytkownik zatwierdza proponowane pola.
