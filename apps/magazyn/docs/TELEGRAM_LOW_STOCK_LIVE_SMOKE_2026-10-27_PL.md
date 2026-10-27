# Magazyn V1 — rzeczywisty test powiadomienia Telegram (DEV)

**Data:** 27.10.2026, AI Platform `harrypotter-AI-Series`.
**Wynik:** **PASS END-TO-END** — wysyłka jednego alertu do pojedynczego, zweryfikowanego odbiorcy, brak duplikacji, usunięcie danych testowych oraz potwierdzony przez użytkownika odbiór wiadomości na urządzeniu.
**Zakres:** oddzielna baza DEV Magazynu i aktywny bot Telegram, bez ingerencji w Hermes, RM i produkcję.

## Warunki wejściowe

- Przed testem baza DEV była pusta: **0 pozycji, 0 sztuk, 0 lokalizacji**.
- Istniało **jedno aktywne, zweryfikowane powiązanie Telegram** z kontem administratora Magazynu.
- Kolejka powiadomień była pusta.
- Bot Telegram miał status `active/running`, `NRestarts=0`.
- Nie odczytywano ani nie wypisywano tokenów, kodów parowania, ID komunikatora czy danych użytkownika.

## Test end-to-end

1. Utworzono wyraźnie oznaczony **tymczasowy produkt testowy** w lokalizacji testowej; nie była to rzeczywista część magazynowa użytkownika.
2. Wprowadzono **2 sztuki**, ustawiono minimum **1** i wskazano tylko jednego, zweryfikowanego odbiorcę przez Telegram. Przy 2 sztukach nie było alertu.
3. Wydano 1 sztukę (2 → 1). Powstało dokładnie **jedno** powiadomienie w SQLite `message_outbox` dla wybranego użytkownika i `telegram`. Wynik: `TARGETED_ALERT_ENQUEUED_PASS`.
4. Działający bot wywołał Telegram API i otrzymał pozytywną odpowiedź. Kolejka zapisała status `sent`. Wynik: `REAL_TELEGRAM_SEND_CONFIRMED_PASS`.
5. Wydano kolejną sztukę (1 → 0). Dodatkowy alert nie powstał. Wynik: `NO_DUPLICATE_LOW_STOCK_ALERT_PASS`.
6. Skrypt usunął **wyłącznie testową** pozycję, stany, historię, outbox i lokalizację. Wynik: `TEST_INVENTORY_CLEANUP_PASS`.

## Kontrola końcowa

| Kontrola | Wynik |
|---|---|
| Pojedynczy odbiorca / przypisany produkt | PASS |
| Jedno powiadomienie o osiągnięciu minimum | PASS |
| Telegram API przyjął wiadomość / status sent | PASS |
| Użytkownik potwierdził wyświetlenie testowego alertu w prywatnym czacie | **PASS — potwierdzenie użytkownika 27.10.2026** |
| Brak duplikatu przy dalszym spadku | PASS |
| Usunięcie danych testowych | PASS |
| Produkty / sztuki / lokalizacje po teście | **0 / 0 / 0** |
| Outbox po teście | **pusty** |
| Usługa Telegram po teście | **active/running**, 0 restartów |
| Produkcja, Hermes, RM, inne aplikacje | **bez zmian** |

**Weryfikacja po stronie odbiorcy:** sam status `sent` oznaczał tylko przyjęcie przez Telegram API. Użytkownik dodatkowo potwierdził w rozmowie 27.10.2026, że otrzymał na swoim urządzeniu wiadomość zaczynającą się od „Magazyn — niski stan” z oznaczeniem `TEST`. Tym samym odbiór jednej wiadomości w prywatnym czacie został potwierdzony. Nie jest to osobna weryfikacja dostarczenia na inne konta ani test wszystkich możliwych awarii.

## Stan projektu

Integracja Telegram pozostaje DEV. Nie wdrożono Magazynu produkcyjnie, nie scalono kodu do `main`. Przed produkcją pozostają m.in. testy bezpieczeństwa WebGUI oraz rzeczywisty test backupu/odtworzenia GlobalNAS. Dokument nie zawiera sekretów, ID użytkowników Telegram ani rzeczywistych stanów magazynowych.
