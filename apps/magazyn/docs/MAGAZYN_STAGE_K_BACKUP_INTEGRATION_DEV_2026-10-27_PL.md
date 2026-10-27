# Magazyn V1 — integracja backupu z istniejącym Stage K (DEV)

**Data:** 2026-10-27
**Aktualizacja 27.10.2026:** trzy drop-in zostały aktywowane dla bazy Magazynu DEV w istniejących user-service Stage K; rzeczywisty start monitora PASS. Brak nowego timera, brak wdrożenia Magazynu na produkcję.

## Założenia i granica zmian

- Tylko Magazyn V1. Nie zmieniamy produkcyjnych backupów Knowledge, WVC, ERS, Hermes, Platform, adapterów ani ich konfiguracji i retencji.
- Zero nowych timerów/crona, dodatkowego daemonu, GPU/LLM/RM.
- Wykorzystujemy trzy **istniejące** usługi user-systemd Stage K: daily (pon.–sob., 02:30), weekly (niedziela, 02:30), monitor (co godzinę).
- Zmiany nie są częścią Stage K w obecnej produkcji. Kod adaptera jest wyłącznie w aplikacji Magazyn, a dwa pliki .conf.in są **szablonami, nieaktywnymi konfiguracjami**.
- Administrator ma w WebGUI wgląd do stanu lokalnego bufora, ostatniej synchronizacji, kontroli i błędów; role i zasady Telegrama pozostają bez zmian.

## Minimalna integracja

Tryb **cycle**: python -m magazyn.stage_k_bridge cycle --config PRIVATE_CONFIG

1. Pobiera blokadę flock w prywatnym buforze kopii.
2. Sprawdza, czy danego dnia UTC wykonał już zaplanowany snapshot; nie duplikuje go przy powtórzeniu.
3. Wywołuje istniejący backup.daily_local() z SQLite Backup API, szyfrowaniem AES-256-GCM i limitem bufora 2 GB. W niedzielę UTC powstaje kopia weekly, pierwszego dnia miesiąca UTC — monthly.
4. Wywołuje istniejący backup.flush_to_nas(): sprawdza realny CIFS i marker GlobalNAS, weryfikuje szyfrowane archiwa po zapisaniu, usuwa bezpiecznie dosłane pliki lokalne. Retencja **7 daily / 4 weekly / 3 monthly** dotyczy wyłącznie podkatalogów Magazyn.
5. Publikuje wynik PASS/DEGRADED/FAIL, liczbę oczekujących archiwów, wiek najstarszego, błąd i datę ostatniego wywołania w istniejącym backup-status.json. Awaria NAS nie usuwa kopii lokalnej.

Tryb **retry**: python -m magazyn.stage_k_bridge retry --config PRIVATE_CONFIG

- Przy istniejącym godzinnym monitorze Stage K ponawia **jedynie wysyłkę** zaległych archiwów; nie generuje zbędnych kopii.
- Sygnalizuje brak snapshotu z harmonogramu oraz stan starszy niż 36 godzin; oznacza zaległe archiwum starsze niż 24 godziny.
- Nie ma własnego procesu w tle ani harmonogramu.

Dostęp do prywatnego pliku konfiguracji JSON ma wyłącznie właściciel (0600). Pola: db, spool, key_file, mount — wszystkie jako ścieżki bezwzględne; plik **nie zawiera klucza AES**, tokenu Telegrama ani PIN-u. Baza, spool i klucz muszą być lokalne.

## Podłączenie do Stage K — wykonane dla Magazynu DEV, bez wdrożenia produkcyjnej aplikacji

Szablony: apps/magazyn/deploy/stage-k/.

- magazyn-cycle.conf.in: do *obu* istniejących ai-platform-stage-k-daily.service i ai-platform-stage-k-weekly.service.
- magazyn-retry.conf.in: do ai-platform-stage-k-monitor.service.
- Na potrzeby bieżącego testu automatyzacji zastosowano sprawdzone ścieżki aktywnego Magazynu DEV; docelowa produkcja będzie wymagać oddzielnego pakietu stabilnego, poza worktree DEV. Tokeny szablonów @MAGAZYN_PACKAGE_ROOT@, @MAGAZYN_PYTHON@ i @MAGAZYN_PRIVATE_CONFIG@ należy w produkcji zastąpić ścieżkami zatwierdzonej instalacji.
- Zachowaj pliki systemd Stage K bez zmian. Nową konfigurację umieść tylko jako osobne, nazwane magazyn.conf w drop-in tych trzech jednostek user-systemd.
- Dyrektywy ExecStartPre=-... wykonują Magazyn **przed** Stage K, nawet jeśli zadanie Stage K później się nie powiedzie. Prefiks - każe systemd nie przerywać Stage K przy błędzie Magazynu. Timeout ogranicza czas do 90 s dla cyklu i 45 s dla retry.
- Przed aktywacją: weryfikacja podstawień, uprawnień, sprawności DB/key, systemd-analyze verify, kontrola systemctl --user cat, daemon-reload, izolowany test Magazynu i obserwacja następnego realnego harmonogramu.
- Po aktywacji: porównać czas i wynik user-systemd ze stanami bridge_last_cycle_at, bridge_last_retry_at, bridge_health, pending oraz aktualnym stanem magazynu. Sam PASS ręcznego testu nie jest dowodem wykonania przez timer.

**Uwaga o produkcji:** 2026-10-27 Stage K daily ma ostatni wynik PASS (z 27.10), ale ostatni weekly z 25.10 ma **FAIL** w fazie knowledge_backup (rc=1); monitor Stage K zgłasza brak PASS tygodniowego restore. Ta awaria poprzedza integrację i NIE jest naprawiana w tym zakresie. Pre-hook Magazynu może wykonać snapshot niezależnie od późniejszego wyniku weekly.

## Rollback po ewentualnym zatwierdzonym wdrożeniu

1. Usunąć wyłącznie trzy pliki drop-in **magazyn.conf**, bez kasowania istniejących jednostek Stage K i bez wyłączania ich timerów.
2. Wykonać systemctl --user daemon-reload; sprawdzić systemctl --user cat dla trzech usług.
3. Potwierdzić pozostawienie nienaruszonych archiwów Magazynu, Stage K, bazy SQLite, AES key i danych użytkowników.
4. W razie błędu aplikacji przywrócić zatwierdzoną wersję kodu Magazynu. Nie usuwać bufora z zaległymi szyfrowanymi archiwami.
5. Nigdy nie czyścić statusu failed tygodniowego Stage K jako substytutu diagnozy backupu/restore.

## Testy — stan 2026-10-27

- Baseline Magazyn przed zmianami: **138/138 PASS**.
- Testy adaptera na syntetycznych bazach i sztucznym NAS: **9/9 PASS** (niedostępność NAS, bufor, automatyczne dosłanie, idempotencja, niedziela/pierwszy dzień miesiąca, nieudany snapshot, stale 36 h, konfiguracja 0600, współbieżność, CLI).
- Rzeczywisty **DEV DB -> szyfrowany snapshot -> GlobalNAS/Magazyn/daily -> verify -> restore do /dev/shm -> integrity_check**: **PASS**.
- Powtórzenie cycle w tym samym dniu: utworzono **0** nowych kopii, wysłano **0** ponownie: **PASS**.
- Następne ręczne retry: backlog **0**, wynik **PASS**.
- Nie zmieniano danych produktów, kont, bota, YubiKeya, kodu produkcyjnego Stage K, harmonogramów ani istniejących kopii Stage K.
- Uruchomienie usługi Stage K monitor z nowym drop-in: PASS. Automatyczny daily/weekly pozostaje do odbioru po faktycznym uruchomieniu z timera.

## Otwarte warunki produkcyjne

- Podłączenie i odbiór faktycznego wywołania z Stage K po zgodzie.
- Rozwiązanie osobnej awarii weekly Stage K (nie należy maskować).
- HTTPS/LAN-VPN, końcowa kontrola uprawnień, osobna niezależna ścieżka odzyskania klucza po utracie YubiKeya, akceptacja DR i rollback.
- Opcjonalny Discord i zwykłe załączniki zdjęciowe są odrębnymi zagadnieniami funkcjonalnymi; nie należą do niniejszego backupu.
