# Stage K — backup i monitor ponownie PASS

20.10.2026. **STAGE_K_RECOVERY_PASS**: istniejąca usługa daily wykonała nowy backup na GlobalNAS, wszystkie weryfikacje przeszły PASS, a monitor o 14:21:02 CEST zgłosił PASS bez problemów.

## Ustalenia

Dzisiejsza próba o 02:30 CEST zakończyła się po 0,62 s błędem `knowledge_backup failed rc=1`. Pozostał pusty katalog staging przed powstaniem zrzutu PostgreSQL. Orkiestrator nie zachował szczegółowego stderr procesu potomnego, dlatego **dokładna przyczyna tej nocnej próby pozostaje nieustalona**.

W trakcie interwencji poprawnie przeszły: identyfikacja udziału CIFS GlobalNAS i markera, próba zapis/odczyt, pobranie konfiguracji bazy bez ujawniania wartości, połączenie PostgreSQL, eksport snapshotu oraz odczyt metadanych Knowledge/CRT/ERS. Harmonogram był aktywny; NAS miał ponad 7 TB wolnego miejsca. Nie stwierdzono trwałej awarii konfiguracji bazy ani mountu.

Monitor pokazał 59,1 h od niedzielnego weekly, ponieważ plik daily z ostatnim PASS został zastąpiony dzisiejszym FAIL. Journal potwierdza również udany daily z 19.10 o 02:31 CEST. Wskazanie wieku i rzeczywista nieudana dzisiejsza próba są odrębnymi ustaleniami.

## Wykonana naprawa

Ponowiono istniejącą usługę użytkownika `ai-platform-stage-k-daily.service`, z jej zwykłym kodem i ustawieniami. Pracowała od 14:13:18 do 14:21:00 CEST, 461,861 s. Dłuższą część zajęło zapisanie i sprawdzenie adapterów na NAS.

| Zakres | Backup ID | Weryfikacja |
|---|---|---|
| Knowledge, WVC i ERS Case Store | `20261020T121318Z` | PASS |
| ERS, Hermes i PlatformConfig | `20261020T121409Z` | PASS |
| Adaptery automotive i WVC | `20261020T121428Z` | PASS, 2 adaptery |

Knowledge: 128 obiektów kanonicznych, 129 wersji dokumentów, 12 283 chunków; dump PostgreSQL 41 761 495 B. Adaptery: 438 928 584 B archiwów źródeł i 467 048 864 B runtime. Retencja PASS; w tej próbie nie usunięto żadnego wcześniejszego zestawu. Automatyzacja secrets pozostaje w dotychczasowym stanie DEFERRED.

Do istniejącej jednostki daily dodano standardowe ustawienia systemd:

- `Restart=on-failure`, `RestartSec=5min`;
- `StartLimitIntervalSec=6h`, `StartLimitBurst=3`.

To pierwsza próba i maksymalnie dwa ponowienia w tym oknie. Dotychczasowy timeout jednej próby wynosi 1 h. Blokada Stage K nadal zapobiega równoległym kopiom. Zmianę zainstalowano atomowo po potwierdzeniu zgodności poprzedniej jednostki z repo; kopia poprzedniej jednostki jest w `/srv/ai-data/evaluation/stage-k-recovery-20261020/before-ai-platform-stage-k-daily.service`. Przeładowanie konfiguracji nie przerwało trwającego backupu. Usługi AI i sterownik nie były restartowane w ramach tej interwencji.

## Odbiór

`systemd-analyze --user verify`: exit 0. Menedżer użytkownika potwierdził aktywne ustawienia ponowień i limitu. Daily zakończył się `Result=success`, `ExecMainStatus=0`, bez potrzeby automatycznego ponowienia tej próby (`NRestarts=0`).

Monitor uruchomiony po backupie: PASS, `issues=[]`, wiek kopii 0,001 h, stan alarmu PASS z pustym digestem. Wszystkie trzy timery pozostają enabled. Następny daily: **21.10.2026 o 02:30 CEST**; weekly: 25.10 o 02:30 CEST. Ostatni pełny weekly restore z 18.10 pozostaje PASS; obecna interwencja wykonała daily z kontrolami integralności.

[Dowody przed i po naprawie oraz ustawienia systemd](STAGE_K_BACKUP_RECOVERY_2026-10-20.json).
