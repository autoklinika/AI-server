# Magazyn V1 / Android — inteligentny odczyt etykiet ECU (DEV)

**Data:** 2026-10-29. **Stan:** Android APK i API PASS; produkcyjny Magazyn ma addytywne API OCR aktywowane w kontrolowanym przełączeniu usługi. Baza SQLite, Gateway i RM pozostały bez zmian.

## Architektura

1. Kamera Androida robi zdjęcie; ML Kit rozpoznaje tekst i kody kreskowe jako awaryjne źródło.
2. Aplikacja przygotowuje JPEG do 2400 px (z rotacją EXIF) i przekazuje go przez zaufane WebGUI/Tailscale HTTPS.
3. FastAPI Magazynu wymaga sesji, nagłówka X-CSRF-Token, ogranicza JPEG do 3,5 MB i dopiero wtedy kieruje model do istniejącego AI Gateway.
4. AI Gateway 127.0.0.1:11435/api/chat prowadzi inferencję przez globalny Resource Manager. **Brak bezpośredniego dostępu do GPU, Ollamy ani nowego schedulera.**
5. Odpowiedź AI jest sprawdzana z danymi ML Kit i kodami kreskowymi. Konflikt numerów blokuje automatyczne wypełnianie numeru głównego.
6. Formularz uzupełnia tylko puste pola, pokazuje wszystkie kandydatury oraz ostrzeżenia i wymaga ręcznego zapisu. Skaner niczego nie zapisuje w SQLite.

## Modele

- MiniCPM-OCR 1.0 Q8 + projector zostały pobrane do staging i sprawdzone SHA-256 (PASS). Import modelu do katalogu Ollama PASS, ale inferencja 29.10.2026 FAIL: `unknown projector type: minicpm_ocr_1_0`. Nie aktualizować Ollamy produkcyjnej tylko dla tego modelu.
- Qwen3-VL 8B domyślnie emituje myślenie i przy małym limicie tokenów potrafi zwrócić puste `message.content`. Do zadania OCR wykorzystujemy wariant **qwen3-vl:8b-instruct**, bez myślenia; testowany przez AI Gateway: PASS 8,8 s; także TestClient API z sesją/CSRF i izolowaną bazą: HTTP 200, numer Bosch/HW/SW poprawny, brak zapisu magazynowego.
- Docelowy model ustawia wyłącznie administrator serwera przez `MAGAZYN_ECU_AI_MODEL`, nie aplikacja.

## Flagi i endpointy

- Domyślnie `MAGAZYN_ECU_AI_ENABLED=0`; w kontrolowanym DEV: `MAGAZYN_ECU_AI_ENABLED=1` i `MAGAZYN_ECU_AI_MODEL=qwen3-vl:8b-instruct`.
- `GET /api/ecu-label/status`: tylko uwierzytelniony użytkownik.
- `POST /api/ecu-label/analyze`: wymagane zalogowanie, CSRF, JPEG, limit obrazu i danych OCR; odpowiedź wyłącznie z sugestiami.
- Fallback na Androidzie działa przy błędzie 404/429/503/timeout; nie powstaje zapis magazynowy ani nowy użytkownik.

## Testy i wdrożenie

- CI: testy izolowane Pythona (brak GPU, auth, CSRF, duplikaty numeryczne, stan wyłączony, brak zapisu), JUnit Android, Gradle build APK, node --check mostka WebView.
- Przed produkcją: przynajmniej kilka realnych etykiet Bosch/Continental/Delphi; wynik znak po znaku, test sesji pracownika, brak automatycznego przyjęcia i potwierdzenie poprawnego rollbacku.
- Produkcyjny backend API został uruchomiony na dodatnim release: /srv/ai-data/magazyn-v1/releases/ecu-ai-087ad211-20261029. Zmiany tylko w server.py (+24 linie), nowym ecu_ai.py i systemd drop-in. Produkcyjny GET /healthz lokalny i HTTPS Tailscale PASS; endpoint status bez uwierzytelnienia 401 PASS; usługa active, RM LLM/nieblokowany. Nie dotykano danych SQLite, Telegrama, Tailscale ani modeli globalnych.
- Pozostaje test fizycznego Androida na rzeczywistych etykietach przed formalnym odbiorem jakości i merge PR. Nie instalować dodatkowych serwisów ani timerów.

## Prywatność

Zdjęcie przechodzi wyłącznie przez Tailscale/HTTPS do lokalnego Serwera AI, nie jest przesyłane do chmury. Pozostaje w pamięci podczas analizy; nie zapisuje się w SQLite ani w logach. Przechowywanie zdjęć przy konkretnym przyjęciu to osobny etap.

## Ryzyka

Model może popełniać błędy w pojedynczych cyfrach. Wymagana kontrola operatora; nie zgadywać braków, nie utożsamiać numeru seryjnego z OEM, nie blokować produkcyjnego Magazynu, jeżeli AI chwilowo nie działa.

## Rollback produkcyjnego API OCR (bez ruszania bazy)

1. Usuń tylko plik `/home/harrypotter/.config/systemd/user/magazyn-webgui.service.d/80-ecu-ai-ocr.conf`.
2. Wykonaj `XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload` oraz `XDG_RUNTIME_DIR=/run/user/1000 systemctl --user restart magazyn-webgui.service`.
3. Zweryfikuj GET `http://127.0.0.1:18765/healthz` i HTTPS Magazyn :8443. Wróci zamrożony release 529af02029e1, ponieważ plik bazowej jednostki nie był modyfikowany.
4. Nie przywracaj starej kopii SQLite po normalnej pracy użytkowników. Pliki modeli pozostają zarejestrowane, ale nie będą używane przez Magazyn.
