# Magazyn V1 / Android — inteligentny odczyt etykiet ECU (DEV)

**Data:** 2026-10-29. **Stan:** przygotowana implementacja i APK w GitHub. Serwer produkcyjny Magazynu nie jest zmodyfikowany.

## Architektura

1. Kamera Androida robi zdjęcie; ML Kit rozpoznaje tekst i kody kreskowe jako awaryjne źródło.
2. Aplikacja przygotowuje JPEG do 2400 px (z rotacją EXIF) i przekazuje go przez zaufane WebGUI/Tailscale HTTPS.
3. FastAPI Magazynu wymaga sesji, nagłówka X-CSRF-Token, ogranicza JPEG do 3,5 MB i dopiero wtedy kieruje model do istniejącego AI Gateway.
4. AI Gateway 127.0.0.1:11435/api/chat prowadzi inferencję przez globalny Resource Manager. **Brak bezpośredniego dostępu do GPU, Ollamy ani nowego schedulera.**
5. Odpowiedź AI jest sprawdzana z danymi ML Kit i kodami kreskowymi. Konflikt numerów blokuje automatyczne wypełnianie numeru głównego.
6. Formularz uzupełnia tylko puste pola, pokazuje wszystkie kandydatury oraz ostrzeżenia i wymaga ręcznego zapisu. Skaner niczego nie zapisuje w SQLite.

## Modele

- MiniCPM-OCR 1.0 Q8 + projector zostały pobrane do staging i sprawdzone SHA-256 (PASS). Import modelu do katalogu Ollama PASS, ale inferencja 29.10.2026 FAIL: `unknown projector type: minicpm_ocr_1_0`. Nie aktualizować Ollamy produkcyjnej tylko dla tego modelu.
- Qwen3-VL 8B domyślnie emituje myślenie i przy małym limicie tokenów potrafi zwrócić puste `message.content`. Do zadania OCR wykorzystujemy wariant **qwen3-vl:8b-instruct**, bez myślenia; wymaga odrębnego smoke testu przez AI Gateway.
- Docelowy model ustawia wyłącznie administrator serwera przez `MAGAZYN_ECU_AI_MODEL`, nie aplikacja.

## Flagi i endpointy

- Domyślnie `MAGAZYN_ECU_AI_ENABLED=0`; w kontrolowanym DEV: `MAGAZYN_ECU_AI_ENABLED=1` i `MAGAZYN_ECU_AI_MODEL=qwen3-vl:8b-instruct`.
- `GET /api/ecu-label/status`: tylko uwierzytelniony użytkownik.
- `POST /api/ecu-label/analyze`: wymagane zalogowanie, CSRF, JPEG, limit obrazu i danych OCR; odpowiedź wyłącznie z sugestiami.
- Fallback na Androidzie działa przy błędzie 404/429/503/timeout; nie powstaje zapis magazynowy ani nowy użytkownik.

## Testy i wdrożenie

- CI: testy izolowane Pythona (brak GPU, auth, CSRF, duplikaty numeryczne, stan wyłączony, brak zapisu), JUnit Android, Gradle build APK, node --check mostka WebView.
- Przed produkcją: przynajmniej kilka realnych etykiet Bosch/Continental/Delphi; wynik znak po znaku, test sesji pracownika, brak automatycznego przyjęcia i potwierdzenie poprawnego rollbacku.
- Produkcja: nie wdrażać bez fizycznych testów telefonu i świadomego przełączenia kodu/flag Magazynu; nie dotykać globalnego RM, Telegrama, Tailscale ani produkcyjnej bazy danych.

## Prywatność

Zdjęcie przechodzi wyłącznie przez Tailscale/HTTPS do lokalnego Serwera AI, nie jest przesyłane do chmury. Pozostaje w pamięci podczas analizy; nie zapisuje się w SQLite ani w logach. Przechowywanie zdjęć przy konkretnym przyjęciu to osobny etap.

## Ryzyka

Model może popełniać błędy w pojedynczych cyfrach. Wymagana kontrola operatora; nie zgadywać braków, nie utożsamiać numeru seryjnego z OEM, nie blokować produkcyjnego Magazynu, jeżeli AI chwilowo nie działa.
