# Magazyn / AI Platform — naprawa harmonogramu Stage K

Data: 27.10.2026 (Europe/Warsaw). Zakres: istniejące usługi user-systemd Stage K; nie instalujemy nowego schedulera.

## Diagnoza

- Daily: mechanizm restartu przy awarii jest już aktywny (Restart=on-failure, RestartSec=5min, StartLimitBurst=3); ostatnia kopia dzienna 27.10 o 02:30 CET zakończyła się PASS.
- Weekly: brak automatycznego ponowienia. Ostatni wynik 25.10: FAIL, faza knowledge_backup, rc=1, po około pięciu sekundach; monitor alarmował o braku pełnego tygodniowego restore.
- Podobny krótkotrwały błąd K2 20.10 po 0,62 s został naprawiony ponowieniem tej samej usługi. Szczegółowe stderr nie zachowało się w K5. Historyczna przyczyna obu awarii pozostaje NIEUSTALONA.
- W Polsce 25.10.2026 godzina 02:30 wystąpiła dwukrotnie wskutek przejścia z CEST na CET. Samo DST NIE dowodzi przyczyny błędu backupu; usuwamy jednak niejednoznaczną godzinę harmonogramu.
- Kontrola aktualnej konfiguracji PostgreSQL i metadanych Knowledge, CRT, ERS wyłącznie READ ONLY: PASS. GlobalNAS CIFS, marker i nietrwała próba odczytu/zapisu małego pliku: PASS. Nie stwierdzono trwałej awarii tych zależności.

## Minimalna naprawa

Zainstalowano WYŁĄCZNIE dwa prywatne pliki dodatkowe user-systemd:

1. ~/.config/systemd/user/ai-platform-stage-k-weekly.service.d/bounded-retry.conf

   [Unit] StartLimitIntervalSec=6h; StartLimitBurst=3

   [Service] Restart=on-failure; RestartSec=5min

2. ~/.config/systemd/user/ai-platform-stage-k-weekly.timer.d/dst-safe-hour.conf

   [Timer] OnCalendar= (reset); OnCalendar=Sun *-*-* 03:30:00

Maksymalnie trzy próby (pierwsza oraz dwa ponowienia). Następny termin: **niedziela 01.11.2026, 03:30 CET**. Godzina 03:30 jest jednoznaczna przy zmianie czasu.

Oryginalne definicje systemd i skrypty Stage K pozostały niezmienione. Dotychczasowe drop-in Magazynu cycle/retry, harmonogram dzienny i hourly monitor pozostają bez zmian. Nie utworzono nowego timera ani nie zmieniono tokenów, usług RM, GPU czy Telegram.

Odbiór: systemd-analyze --user verify PASS; daemon-reload PASS; aktywny manager systemd potwierdził Restart=on-failure, RestartUSec=5min, StartLimitBurst=3. Przez Persistent=true restart timera wykrył zaległe wywołanie nowej godziny i automatycznie uruchomił tygodniowy Stage K 27.10 około 23:44 CET. Etap tworzenia i weryfikacji zestawów został ukończony, potem rozpoczął się izolowany restore_validate (w odrębnej bazie PostgreSQL i środowisku Qdrant). Nie uruchomiono drugiego równoległego backupu.

## Rollback

Prywatny skrypt i manifest z SHA-256 oryginalnych definicji bez sekretów:

/srv/ai-data/staging/stage-k-weekly-harmonogram-fix-20261027/weekly_fix.py

Cofnięcie tylko dwóch znanych drop-in:

python3 /srv/ai-data/staging/stage-k-weekly-harmonogram-fix-20261027/weekly_fix.py rollback

Skrypt sprawdza zawartość, nie kasuje archiwów ani oryginalnych jednostek/timerów, wykonuje daemon-reload oraz restart samego tygodniowego timera.

## Warunki końcowego odbioru

- weekly.json: status=PASS i kompletne trzy walidacje przywrócenia: Knowledge, Domains, Adapters.
- hourly monitor: bez zgłoszenia brakującego weekly restore.
- rzeczywisty dzienny timer Magazynu po instalacji integracji: 28.10.2026 o 02:30 CET (jeszcze do odebrania); dziś test cycle/retry Magazynu i zaszyfrowany restore z GlobalNAS już PASS.
- niezależny fizyczny klucz odzyskania AES poza YubiKeyem i ACL pracowników pozostają odrębnymi blokadami produkcji Magazynu, niezwiązanymi z harmonogramem.

Wszelkie zmiany kodu GitHub trafiają wyłącznie do DEV; produkcyjny Magazyn nie jest uruchamiany.


## Potwierdzony rezultat końcowy — 27.10.2026, 23:52 CET

- **STAGE_K_WEEKLY_FULL_PASS:** status weekly.json = PASS; pełny czas cyklu 420,711 s.
- **K2 Knowledge backup i verify:** PASS. **WVC:** PASS. **ERS Case Store:** PASS.
- **K3 backupy domenowe i verify ERS/Hermes/Platform:** PASS.
- **K4 adapter backup i verify:** PASS.
- **Izolowany tygodniowy restore:** Knowledge = PASS, Domains = PASS, Adapters = PASS.
- **Retention:** PASS, wszystkie tablice removed_k2, removed_k3, removed_adapters, removed_restore_evidence mają 0 pozycji. Nie usunięto wcześniejszych zestawów.
- Po zakończeniu ręcznie uruchomiono istniejącą usługę monitorującą (bez nowego timera). **Stage K monitor = PASS, issues=[]**. Usługa tygodniowa systemd: Result=success, ExecMainStatus=0, NRestarts=0.
- Kontenery testowego Qdrant zamknięte. Oryginalne pliki Stage K .service/.timer mają identyczne SHA-256 co przed zmianą.
- Wszystkie trzy timery Stage K są active. Najbliższy: monitor ok. 00:00, daily **28.10 o 02:30 CET**, weekly **01.11 o 03:30 CET**.
- Po wykonaniu tygodniowego cyklu **Magazyn bridge_health=PASS, lokalny bufor oczekujący = 0**. Działająca baza Magazynu DEV ma niezmienione 2 produkty, 4 zdarzenia, 2 wiersze stanów i 1 dokument; SQLite quick_check=ok.
- Ponowny audit magazyn.release_gate: **stage_k_daily PASS, stage_k_weekly PASS, magazyn_backup PASS, sqlite PASS, https_tls PASS, pytest PASS**. Produkcja Magazynu nadal **NO_GO** wyłącznie z powodu nieodebranego regularnego daily timera po integracji, niezależnego recovery offline oraz uprawnień Tailscale ACL pracowników.

**Nie udowodniono historycznej przyczyny krótkotrwałego błędu K2; zabezpieczenie przed jego powtórzeniem polega na ograniczonym retry.** Realne wywołanie niedzielnego timera 01.11 pozostaje dodatkowym testem regularności. Stan weekly+restore z obecnego automatycznego nadrobienia został w pełni odebrany jako PASS.
