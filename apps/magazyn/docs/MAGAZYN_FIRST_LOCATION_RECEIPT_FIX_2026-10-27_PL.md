# Magazyn V1 DEV — naprawa pierwszego przyjęcia bez lokalizacji

Data: 27.10.2026. Gałąź: feature/magazyn-v1-dev-20261026.

## Przyczyna

W rzeczywistej bazie Magazynu DEV było **0 lokalizacji i 0 produktów**. Zarówno formularz ECU, jak i formularz elektroniki wyłączał przycisk dodawania, gdy lista lokalizacji była pusta. Użytkownik mógł uzupełnić parametry, lecz nie otrzymywał czytelnego wyjaśnienia blokady. Kod backendu wymagał zawsze istniejącego identyfikatora lokalizacji.

## Naprawa

- Administrator przy pierwszym dodawaniu produktu od razu widzi pole kodu lokalizacji (np. A1) i krótkie wyjaśnienie. Nie musi wychodzić z formularza.
- Jeden przycisk tworzy **lokalizację + produkt + przyjęcie na stan** w tej samej transakcji SQLite. Błąd w produkcie lub w przyjęciu wycofuje całą transakcję, także nową lokalizację.
- Dotyczy zarówno sterowników ECU, jak i elementów elektronicznych, bez zmiany ich odrębnych parametrów, dokumentacji i istniejących sposobów zapisu.
- Użytkownik bez roli Administrator nie może założyć lokalizacji przez API ani GUI.
- Przy istniejących lokalizacjach formularze zachowują dotychczasowy wybór miejsca, bez dodatkowych kroków.
- Nie ma domyślnie wymyślonego magazynu „A1”; administrator podaje rzeczywisty kod.
- Nie ma zmiany schematu bazy, nowych usług, zmian w Telegram, backupie, YubiKey lub w systemie zamówień.

## Testy

9 nowych testów regresyjnych na odrębnej syntetycznej SQLite: pierwsza lokalizacja z elektroniką oraz ECU, przyjęcie na stan, atomowy rollback przy niepoprawnych danych, blokada użytkownika, kolizja kodu lokalizacji, zgodność starej ścieżki z istniejącym miejscem. Wszystkie PASS.

Firefox/WebDriver przy mobilnym viewport 390 px na **pustej syntetycznej bazie**:
- pracownik bez lokalizacji nie może sam tworzyć miejsca — PASS;
- administrator widzi od razu formularz pierwszej lokalizacji i aktywny przycisk dodawania — PASS;
- wpisanie kodu miejsca i parametrów, kliknięcie jednego przycisku, potwierdzenie zapisu produktu, lokalizacji i historii — PASS;
- po przyjęciu ekran dodawania ECU widzi nową lokalizację na liście — PASS.

Cały pakiet Magazynu: **180/180 PASS**, Node.js syntax PASS, kompilacja Pythona PASS.
Dane testowe ani zrzuty ekranu nie zostały umieszczone w prawdziwym magazynie.

## Wdrożenie i rollback

Zmiana jest wyłącznie na gałęzi DEV. Aktywacja wymaga restartu tylko magazyn-webgui-dev.service; dotychczasowa baza SQLite v3 i produkcyjne aplikacje AI Platform pozostają bez zmian. Przed i po restarcie sprawdzić integralność SQLite, bieżące liczby rekordów oraz aktywność obu usług Magazynu DEV. W razie potrzeby wycofać commit frontend/backend (schemat bazy nie był zmieniany); nie odtwarzać starszej kopii bazy, jeżeli pojawiły się późniejsze rzeczywiste operacje.

Adres po aktywacji: https://ai-server.tail759e12.ts.net:8443/ (Tailscale). Dla aktualizacji JavaScript odświeżyć stronę w Safari.
