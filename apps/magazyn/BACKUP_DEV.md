# Magazyn V1 — instrukcja backupu DEV

**Status 27.10.2026: rzeczywisty szyfrowany backup Magazynu DEV zapisano i odtworzono z GlobalNAS (PASS). Kopię klucza AES zaszyfrowano dla istniejącego YubiKeya 5C i zapisano na NAS. Fizyczne odszyfrowanie tego pliku z YubiKey/PIN, weryfikacja klucza, archiwum i restore bazy w RAM oraz usunięcie danych tymczasowych: PASS. Brak automatycznego harmonogramu i wdrożenia produkcyjnego.**

## Zasada działania

- SQLite Backup API wykonuje spójny snapshot do pamięci, bez kopiowania aktywnego pliku SQLite/WAL.
- Archiwum jest szyfrowane AES-256-GCM, klucz ma 32 losowe bajty. Zależność: requirements-backup.txt (cryptography).
- Archiwa nie zawierają jawnych informacji o produktach, pracownikach ani ilościach; nazwy zawierają datę UTC i poziom retencji.
- Jawny AES key pozostaje prywatny (0600), katalog klucza i bufora ma 0700. Zaszyfrowana przez publiczny YubiKey PIV kopia klucza znajduje się na NAS w Magazyn/recovery. **Fizyczny decrypt drill z YubiKey i PIN-em przeszedł 27.10.2026 (PASS)**. Nadal niezbędna jest niezależna ścieżka odzyskiwania na wypadek utraty jedynego YubiKeya.
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

- **Drugiego niezależnego sposobu odzyskania** po jednoczesnej utracie hosta i obecnego YubiKeya; fizyczny test odszyfrowania kopii recovery z istniejącym YubiKeyiem został już zaliczony 27.10.2026.
- Powtarzalnego uruchamiania kopii w zgodzie z Stage K, bez nowego niezależnego schedulera, oraz monitorowania zaległości i błędów.
- Obsługi przyszłych zdjęć/załączników i końcowego odbioru uprawnień DR. Rzeczywisty marker Stage K, CIFS GlobalNAS, zapis i odtworzenie z NAS były pozytywnie sprawdzone 27.10.2026.

### Potwierdzony test DEV z 27.10.2026

- Jawny klucz AES pozostaje wyłącznie lokalnie, w prywatnym pliku 0600. Jego zaszyfrowana kopia YubiKey/age jest na GlobalNAS w Magazyn/recovery. Odszyfrowanie wymaga YubiKeya i PIN-u; fizyczny test odzyskania i użycia klucza do restore zakończył się PASS.
- Lokalny bufor kopii: `/srv/ai-data/staging/magazyn-telegram-dev-20261027/private/backup-spool` (0700).
- Tożsamość montowania CIFS i znacznik `.ai-platform-backup-target.json` sprawdzono bez zmiany Stage K. Na tym hoście systemd automount ujawnia **dwie warstwy**, `autofs` oraz faktyczny `cifs`: weryfikator wymaga ostatniej poprawnej warstwy CIFS, nie ufa samemu `autofs`.
- Wysłano **jedno** zaszyfrowane archiwum do `/mnt/AI_Platform/Magazyn/daily/`, ponownie odczytano, odszyfrowano i zweryfikowano (PASS).
- Wykonano pełny **restore bezpośrednio z archiwum na NAS** do prywatnego katalogu w `/dev/shm` (RAM), `PRAGMA integrity_check=ok`, a katalog po teście został usunięty (PASS).
- Nie zmieniano backupów Stage K ani konfiguracji YubiKey PIV. Na NAS trafiła wyłącznie zaszyfrowana, 242-bajtowa kopia klucza odzyskiwania AES; nigdy jawny klucz. Nie instalowano nowych timerów ani crona. Magazyn pozostaje **DEV**. Szczegóły: [YubiKey recovery](docs/MAGAZYN_YUBIKEY_RECOVERY_2026-10-27_PL.md).

Nie umieszczać danych magazynowych, archiwów, kluczy ani kont pracowników w publicznym repozytorium GitHub.


## Integracja Stage K — dodatkowy etap DEV 27.10.2026

Na istniejącym worktree DEV przygotowano moduł magazyn.stage_k_bridge. Wykorzystuje istniejące usługi daily, weekly i hourly-monitor Stage K poprzez opcjonalne drop-in ExecStartPre, bez zmiany kodu Stage K, nowych timerów i usług. Szablony drop-in **nie zostały zainstalowane**. Wymagane jest osobne zatwierdzenie uruchomienia automatycznego harmonogramu.

Rzeczywisty ręczny cykl DEV na istniejącej bazie i GlobalNAS: snapshot + wysyłka + weryfikacja + restore w RAM = **PASS**. Ponowne uruchomienie tego samego dnia i retry nie tworzą duplikatów; backlog = 0. Status health oraz ostatni błąd są dostępne administratorowi w WebGUI. Pełny opis wdrożenia i rollback: [Magazyn Stage K DEV](docs/MAGAZYN_STAGE_K_BACKUP_INTEGRATION_DEV_2026-10-27_PL.md).

Ostatni weekly Stage K z 25.10 ma odrębny, wcześniejszy wynik FAIL (knowledge_backup). Nie zmieniano tego mechanizmu ani archiwów Stage K.
