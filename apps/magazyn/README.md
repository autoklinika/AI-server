# Magazyn V1 — Serwer AI

Aplikacja ewidencji sterowników ECU i elektroniki oparta na **FastAPI + SQLite**. Kod jest synchronizacją źródeł wydania produkcyjnego `catalog-suppliers-pdf-ui-20261030` z 30 października 2026 r.

## Funkcje

- Konta i role, sesje, CSRF, historia operacji, stany ilościowe i wiele lokalizacji fizycznych.
- Dwa osobne, hierarchiczne drzewa katalogów dla ECU i elektroniki; istniejące produkty można przypisywać do folderów bez modyfikowania stanów magazynowych.
- WebGUI po polsku, mobilny układ i jednakowe rozmiary okien modalnych.
- Aktywne hurtownie: **TME API v2 oraz Mouser Search API**; wyszukiwanie wariantów MPN, odczyt liczby dostępnych sztuk, progów cenowych, walut i odnośników do ofert/wyszukiwania.
- Dokumentacja elektroniczna PDF z dysku lub zatwierdzonego źródła HTTPS, lokalny OCR CPU skanów PDF i propozycje parametrów wymagające akceptacji.
- Prywatne powiadomienia Telegram, minima stanów, import/eksport CSV/XLSX, zaszyfrowany backup AES-GCM i odtworzenie przez GlobalNAS.

DigiKey i Farnell nie są włączone; Discord i Android pozostają osobnymi zakresami.

## Pochodzenie i bezpieczeństwo

Źródła katalogu `magazyn/` i zależności zostały pobrane z **uruchomionego, przetestowanego wydania produkcyjnego**. Repozytorium jest publiczne, więc **nie zawiera danych produkcyjnych, kluczy, certyfikatów, plików bazy, danych klientów ani rzeczywistych adresów prywatnej infrastruktury**.

Dwie zależne od infrastruktury wartości są w tej wersji repozytoryjnej **celowo parametryzowane** zamiast ujawniać konfigurację hosta:

1. `MAGAZYN_EXPECTED_NAS_HOST` — wymagany we wdrożeniach używających GlobalNAS. Backup odmawia zapisu na NAS bez tego ustawienia, nawet jeśli katalog jest zamontowany. Pozostałe kontrole tożsamości udziału i markera muszą przejść.
2. `--https-url` w audycie `magazyn.release_gate` — wymagany argument, bez zaszytego adresu hosta.

Uruchomiony na serwerze pakiet produkcyjny nie został zmieniony przy synchronizacji GitHub. Nie nadpisywać produkcji kodem z GitHub bez osobnego testu i procedury wydania.

**Dane uwierzytelniające** dla hurtowni należy konfigurować w chronionym katalogu poza repozytorium. Klucze API nigdy nie są wysyłane do WebGUI. Nie wolno używać prawdziwej SQLite produkcyjnej do testów.

## Testy i zależności

Moduły są w `magazyn/`, testy w `tests/`. `requirements-backup.txt`, `requirements-bots.txt` i `requirements-xlsx.txt` zawierają dodatkowe pakiety dla odpowiednich funkcji. FastAPI/Uvicorn, Pydantic, pytest i klient testowy należy instalować w oddzielnym środowisku wirtualnym.

Pakiet Magazynu utrzymuje ścisłe reguły lokalizacji dla konfiguracji hurtowni. Testy integracyjne należy uruchamiać **na izolowanej kopii kodu i z syntetyczną bazą**, w katalogu testowym o nazwie `magazyn-hurtownie-webgui-dev-20261029` (lub z odpowiednim mockiem konfiguracji), bez połączenia z produkcyjnym katalogiem sekretów. Testy PDF/OCR wymagają lokalnego Popplera i Tesseract; testy sprzętowe lub live API wykonuje się osobno, wyłącznie na autoryzowanym stanowisku.

## Dokumentacja zmian

- [Raport synchronizacji 30.10.2026](docs/GITHUB_SYNC_2026-10-30_PL.md)
- [Raport statusu Magazynu z PR #192](https://github.com/autoklinika/AI-server/pull/192) — osobny PR dokumentacyjny, którego nie należy utożsamiać ze zmianami źródeł

Wydanie produkcyjne ma osobne, niezmienne kopie kodu i mechanizm rollbacku bez przywracania wcześniejszej bazy SQLite.
