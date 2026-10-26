# Magazyn V1 — instrukcja backupu DEV

**Status: kod i testy syntetyczne, bez realnego zapisu na GlobalNAS, bez timera i bez wdrożenia.**

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

**Automatyczny timer raz dziennie nie został jeszcze zainstalowany**, bo to środowisko DEV. Będzie wymagał osobnego wdrożenia, monitoringu niesynchronizowanych backupów i potwierdzenia uprawnień do markera Stage K.

## Odtworzenie

    python -m magazyn.backup restore --archive "/PRIVATE/BACKUP/FILE.mgzb" --destination "/PRIVATE/RECOVERY/magazyn-restored.sqlite3" --key-file "/PRIVATE/KEYS/magazyn.key"

Odtworzenie wymaga nieistniejącego pliku docelowego i prywatnego katalogu. Nie nadpisuje działającej bazy, nie restartuje usług, nie uruchamia migracji. Przy późniejszym wdrożeniu produkcyjnym należy najpierw zatrzymać operacje zapisu, przetestować dane z przywróconej kopii i przygotować możliwość rollbacku.

## Panel administratora

GET /api/backup/status zwraca lokalny stan bufora i daty kopii; POST /api/backup/manual tworzy zaszyfrowaną lokalną kopię, gdy MAGAZYN_BACKUP_SPOOL i MAGAZYN_BACKUP_KEY_FILE są skonfigurowane. Endpoint zapisu wymaga sesji administratora i CSRF. Przycisk w WebGUI wyraźnie informuje, że kopia może jeszcze oczekiwać na NAS.

## Nadal brak

- Weryfikacji rzeczywistego GlobalNAS i realnego testu odtworzenia z NAS.
- Instalacji dziennego timera, monitorowania błędów i powiadomień o zaległościach.
- Obsługi przyszłych zdjęć/załączników, polityki przechowywania klucza i zweryfikowanego dostępu do markera Stage K.

Nie umieszczać danych magazynowych, archiwów, kluczy ani kont pracowników w publicznym repozytorium GitHub.
