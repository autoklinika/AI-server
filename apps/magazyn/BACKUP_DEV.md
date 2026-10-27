# Magazyn V1 — instrukcja backupu DEV

**Status 27.10.2026: rzeczywisty szyfrowany backup Magazynu DEV zapisano na GlobalNAS i pomyślnie odtworzono z NAS do tymczasowego katalogu w RAM (PASS). Brak automatycznego timera, bez wdrożenia produkcyjnego.**

## Zasada działania

- SQLite Backup API wykonuje spójny snapshot do pamięci, bez kopiowania aktywnego pliku SQLite/WAL.
- Archiwum jest szyfrowane AES-256-GCM, klucz ma 32 losowe bajty. Zależność: requirements-backup.txt (cryptography).
- Archiwa nie zawierają jawnych informacji o produktach, pracownikach ani ilościach; nazwy zawierają datę UTC i poziom retencji.
- Klucz musi być prywatny (0600), a katalog klucza i bufora musi mieć tryb 0700. Trzeba zrobić osobną, bezpieczną kopię klucza poza NAS: jego utrata uniemożliwia odzyskanie danych.
- Obecnie kopia obejmuje całą bazę danych (produkty, użytkownicy, role, sesje, historia, minima). Załączniki nie istnieją jeszcze w Magazynie V1; po ich dodaniu wymagane będzie rozszerzenie backupu.

## Wywołania CLI po utworzeniu prywatnych katalogów

W osobnym środowisku aplikacji z pakietami FastAPI i cryptography, mając Magazyn na PYTHONPATH:

    python -m magazyn.backup init-key --key-file "/PRIVATE/KEYS/magazyn.key"
    python -m magazyn.backup snapshot --db "/PRIVATE/DATA/magazyn.sqlite3" --spool "/PRIVATE/SPOOL/magazyn" --key-file "/PRIVATE/KEYS/magazyn.key"
    python -m magazyn.backup status --spool "/PRIVATE/SPOOL/magazyn"
    python -m magazyn.backup verify --archive "/PRIVATE/SPOOL/magazyn/daily/FILE.mgzb" --key-file "/PRIVATE/KEYS/magazyn.key"

Dopiero po osobnym odbiorze montowania GlobalNAS:

    python -m magazyn.backup flush --spool "/PRIVATE/SPOOL/magazyn" --mount "/mnt/AI_Platform" --key-file "/PRIVATE/KEYS/magazyn.key"

Weryfikacja przed kopiowaniem wymaga prawdziwego udziału CIFS AI_Platform i istniejącego markera .ai-platform-backup-target.json (schema_version=1, purpose=ai-platform-stage-k, nas=GlobalNAS). Nie są montowane zasoby ani modyfikowana konfiguracja Stage K. Backup trafi do podkatalogu Magazyn/daily, Magazyn/weekly lub Magazyn/monthly. Jeżeli NAS jest niedostępny, zaszyfrowana kopia pozostaje w lokalnym buforze i nie jest uznawana za kopię zewnętrzną. Kopia wysyłana na NAS jest ponownie odczytywana, odszyfrowywana i sprawdzana przed usunięciem oczekującej kopii lokalnej.

## Retencja i harmonogram

Procedura dzienna tworzy jedną kopię daily. W niedzielę UTC powstaje również weekly, pierwszego dnia miesiąca UTC również monthly. Retencja na GlobalNAS: 7 daily, 4 weekly, 3 monthly. Usuwane są tylko najstarsze poprawne pliki w podkatalogu Magazyn, po pozytywnym kopiowaniu. Lokalny bufor ma domyślny limit 2 GB; przekroczenie limitu nie wpływa na pracę aplikacji.

**Automatyczny timer nie został zainstalowany.** Zgodnie z architekturą AI Platform nie dodajemy drugiego schedulera bez decyzji o integracji z istniejącym mechanizmem Stage K. Jednorazowy zapis na NAS i odczyt/restore zakończył się sukcesem; nie oznacza to jeszcze automatycznego wykonywania kopii ani kompletnej procedury DR.

## Odtworzenie

    python -m magazyn.backup restore --archive "/PRIVATE/BACKUP/FILE.mgzb" --destination "/PRIVATE/RECOVERY/magazyn-restored.sqlite3" --key-file "/PRIVATE/KEYS/magazyn.key"

Odtworzenie wymaga nieistniejącego pliku docelowego i prywatnego katalogu. Nie nadpisuje działającej bazy, nie restartuje usług, nie uruchamia migracji. Przy późniejszym wdrożeniu produkcyjnym należy najpierw zatrzymać operacje zapisu, przetestować dane z przywróconej kopii i przygotować możliwość rollbacku.

## Panel administratora

GET /api/backup/status zwraca lokalny stan bufora i daty kopii; POST /api/backup/manual tworzy zaszyfrowaną lokalną kopię, gdy MAGAZYN_BACKUP_SPOOL i MAGAZYN_BACKUP_KEY_FILE są skonfigurowane. Endpoint zapisu wymaga sesji administratora i CSRF. Przycisk w WebGUI wyraźnie informuje, że kopia może jeszcze oczekiwać na NAS.

## Nadal brak

- Osobnej, bezpiecznej kopii klucza AES-256 poza serwerem i NAS. **Bez klucza nie ma możliwości odszyfrowania archiwum.** Nie wolno wysyłać klucza do GitHub ani w czacie.
- Powtarzalnego uruchamiania kopii w zgodzie z Stage K, bez nowego niezależnego schedulera, oraz monitorowania zaległości i błędów.
- Obsługi przyszłych zdjęć/załączników i końcowego odbioru uprawnień DR. Rzeczywisty marker Stage K, CIFS GlobalNAS, zapis i odtworzenie z NAS były pozytywnie sprawdzone 27.10.2026.

### Potwierdzony test DEV z 27.10.2026

- Prywatny klucz istnieje tylko lokalnie: `/srv/ai-data/staging/magazyn-telegram-dev-20261027/private/backup-keys/magazyn-dev.key`, prawa 0600, katalog 0700. Wymaga niezależnej kopii offline przed produkcją.
- Lokalny bufor kopii: `/srv/ai-data/staging/magazyn-telegram-dev-20261027/private/backup-spool` (0700).
- Tożsamość montowania CIFS i znacznik `.ai-platform-backup-target.json` sprawdzono bez zmiany Stage K. Na tym hoście systemd automount ujawnia **dwie warstwy**, `autofs` oraz faktyczny `cifs`: weryfikator wymaga ostatniej poprawnej warstwy CIFS, nie ufa samemu `autofs`.
- Wysłano **jedno** zaszyfrowane archiwum do `/mnt/AI_Platform/Magazyn/daily/`, ponownie odczytano, odszyfrowano i zweryfikowano (PASS).
- Wykonano pełny **restore bezpośrednio z archiwum na NAS** do prywatnego katalogu w `/dev/shm` (RAM), `PRAGMA integrity_check=ok`, a katalog po teście został usunięty (PASS).
- Nie zmieniano backupów Stage K, nie kopiowano klucza na NAS, nie instalowano systemd timer ani cron. Mimo testu pozostaje **DEV**, bez zapewnionej kopii klucza offsite.

Nie umieszczać danych magazynowych, archiwów, kluczy ani kont pracowników w publicznym repozytorium GitHub.
