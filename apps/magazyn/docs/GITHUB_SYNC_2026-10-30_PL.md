# Magazyn V1 — synchronizacja kodu produkcyjnego z GitHub (30.10.2026)

## Zakres

Źródłem jest działający pakiet `catalog-suppliers-pdf-ui-20261030`. Gałąź `main` nie zawierała dotychczas `apps/magazyn`; historyczna gałąź `feature/magazyn-v1-dev-20261026` zawiera nieaktualny kod. Ten PR publikuje aktualny kod, a PR #192 pozostaje niezależną dokumentacją.

Zawartość: FastAPI, SQLite, interfejs, katalogi ECU/elektroniki, TME/Mouser, ceny i dostępność, dokumentacja PDF/OCR, Telegram, backup/DR i testy. Bez konfiguracji prywatnej, SQLite, kluczy, tokenów, danych pracowników i użytkowników, backupów, logów, certyfikatów i materiałów odzyskiwania.

## Różnice wymagane przez publiczny charakter repozytorium

- `MAGAZYN_EXPECTED_NAS_HOST` — zamiast ujawnienia prywatnego hosta NAS. Backup wymaga jawnego hosta i odrzuca brak ustawienia; weryfikacja CIFS i tożsamości markera pozostaje obowiązkowa.
- `--https-url` — wymagany jawny adres do audytu `release_gate`, bez prywatnej domeny zaszytej w źródle.

Te dwie różnice dotyczą wyłącznie wersji publikowanej w repozytorium. Działające wydanie produkcyjne nie zostało zmienione podczas synchronizacji.

## Niezmienniki bezpieczeństwa

Bezpośrednia praca z produkcyjną SQLite podczas testów jest zabroniona. Mechanizmy CSRF, role, ochrona haseł, odseparowanie sekretów, limit zapytań API Mouser oraz backup/restore pozostają zachowane. Katalogi logiczne nie są fizycznymi lokalizacjami, a zbliżone MPN i wyniki OCR nigdy nie upoważniają do automatycznej zamiany numeru części lub wpisania parametrów.

## Testy i wdrożenie

Testy należy uruchamiać w izolowanym środowisku testowym. Skany PDF w `tests/fixtures` są syntetyczne; żaden plik użytkownika nie został dołączony.

Scalenie PR do chronionego `main` **nie** stanowi kolejnego wdrożenia produkcyjnego. Każdy przyszły deploy wymaga odrębnego GO, zaszyfrowanego backupu, próbnego odtworzenia i rollbacku kodu bez cofania danych magazynowych.
