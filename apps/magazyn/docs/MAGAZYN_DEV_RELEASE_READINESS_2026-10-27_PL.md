# Magazyn V1 — DEV: Stage K, HTTPS, administracja i offline recovery

Data: 2026-10-27. Repo: feature/magazyn-v1-dev-20261026.
**Status:** zmiany DEV na prawdziwym serwerze, bez wdrożenia Magazynu na produkcję i bez merge do main.

## 1. Stage K — automatyzacja backupu Magazynu DEV

Zachowano wszystkie trzy istniejące user-systemd timery Stage K:
- ai-platform-stage-k-daily.timer: poniedziałek–sobota 02:30.
- ai-platform-stage-k-weekly.timer: niedziela 02:30.
- ai-platform-stage-k-monitor.timer: godzinny monitor.

Dodano jedynie trzy własne drop-in o nazwie magazyn.conf w katalogach ~/.config/systemd/user/ai-platform-stage-k-[daily|weekly|monitor].service.d/.
Nie zmieniono oryginalnych jednostek, kodu Stage K, timerów, retencji Stage K ani mechanizmów Hermes, Knowledge i RM. Nie utworzono nowych timerów i procesów. ExecStartPre=-... uruchamia adapter Magazynu przed Stage K, a kod błędu Magazynu nie przerywa działania Stage K. Osobny limit czasu: 90 s cyklu, 45 s dla godzinnego retry.

Bieżąca kopia: rzeczywista baza Magazynu DEV, jej niezmieniony lokalny klucz AES i zaszyfrowane archiwa we własnym katalogu Magazyn na GlobalNAS. Retencja Magazynu: **7 daily / 4 weekly / 3 monthly**, bufor lokalny do 2 GB. Dzienny snapshot jest idempotentny w obrębie dnia UTC; w niedzielę UTC także weekly, pierwszego dnia miesiąca także monthly. Retry jedynie wysyła zaległe archiwa.

### Test i wynik

- Preflight potwierdził bazę DEV, AES key i montowanie GlobalNAS: PASS.
- Wszystkie trzy jednostki rozpoznają drop-in, systemd-analyze verify: PASS.
- Faktyczne uruchomienie istniejącej usługi monitorującej ai-platform-stage-k-monitor.service: Result=success, bridge_last_result=retry, bridge_health=PASS.
- Timer uruchomił monitor 27.10 o 18:00:55 CET. Dziennik usługi potwierdził uruchomienie adaptera Magazynu retry PASS, pending=0. Niezależny monitor Stage K nadal zgłasza FAIL dotyczący wcześniejszego weekly Knowledge.
- Ręczne: lokalny snapshot, wysyłka, odczyt i restore SQLite w RAM: PASS.
- **Brak jeszcze zaliczonego automatycznego cyklu daily/weekly przez timer; do obserwacji przy najbliższym uruchomieniu.**
- Niezależny problem: weekly Stage K z 2026-10-25 zakończył się FAIL w knowledge_backup rc=1; monitor Stage K zgłasza brak tygodniowego restore PASS. Nie maskowano i nie naprawiano tego błędu w projekcie Magazyn.

Rollback: usunąć wyłącznie trzy nowe pliki magazyn.conf, a potem systemctl --user daemon-reload. Nie usuwać oryginalnych jednostek, timerów ani archiwów.

## 2. HTTPS DEV — Tailscale Serve, osobny port

Istniejący host posiadał HTTPS Tailscale Serve na porcie 443 z trasą /control do AI Platform. Dodano wyłącznie port HTTPS 8443 proxy do dotychczasowego localhost 127.0.0.1:18765 Magazynu.

Adres: https://ai-server.tail759e12.ts.net:8443/

Dostęp wyłącznie w tailnet, nie Funnel i nie publiczny Internet. Backend nadal nasłuchuje tylko na localhost. Konta Magazynu pozostają obowiązkowe. Pracownik musi być dopuszczony do tailnetu przez ACL/Grants i mieć indywidualne konto Magazynu. Dostęp z samej LAN bez Tailscale nie jest zapewniony; docelowy model dostępu pracowników wymaga potwierdzenia.

Realny test certyfikatu bez pomijania TLS: ssl_verify_result=0, healthz HTTP 200, niezalogowane zapytania o dane HTTP 401. Poprzednie HTTPS :443 /control pozostało nienaruszone. Dla HTTPS aplikacja ustawia sesyjny cookie Secure; DEV zachowuje dotychczasowy tryb HTTP jedynie na loopback/tunelu SSH. Produkcja musi wymuszać Secure+HTTPS bezwarunkowo.

Rollback: tailscale serve --https=8443 off. Nie wykonywać tailscale serve reset, ponieważ usunęłoby poprzednią trasę /control. Kopia bezpiecznej konfiguracji bazowej znajduje się w prywatnym pliku https-rollback/tailscale-serve-before.json w staging DEV (0600).

## 3. Administracja WebGUI i odtwarzanie

- Historia: filtry produkt, użytkownik, przedział dat UTC; administrator widzi Edytuj oraz dotychczasowe Usuń. Edycja wpisu nie zmienia bieżących ilości.
- Backup: lista wyłącznie bezpiecznie rozpoznanych plików .mgzb z bufora i zweryfikowanego udziału GlobalNAS. Klient nie może wskazać dowolnej ścieżki.
- Akcja Testuj odtworzenie jest dostępna jedynie administratorowi z sesją i CSRF: odszyfrowanie, odtworzenie do tymczasowego katalogu w RAM (/dev/shm), integrity_check i automatyczne usunięcie. Nie zwraca danych produktów, kont ani kluczy.
- To NIE jest przełączenie produkcyjnej bazy. Katastrofalne przywrócenie wymaga zatrzymania zapisów, izolowanego odtworzenia, weryfikacji oraz kontrolowanego przełączenia.
- Kolory, nawigacja i ogólny styl WebGUI nie zostały zmienione.

Rzeczywisty test bezpośredniego odtworzenia zaszyfrowanej kopii Magazynu DEV z GlobalNAS do RAM: PASS. Restart tylko WebGUI DEV; Telegram bez restartu. integrity_check i liczby rekordów w tabelach bazy DEV bez zmian; HTTPS /healthz, lista UI i nieautoryzowane API: PASS.

## 4. Niezależny od YubiKeya recovery key — przygotowany, NIE ZAMKNIĘTY

Zaimplementowano offline_escrow.py. Akceptuje wyłącznie publicznego odbiorcę age X25519, wygenerowanego na INNYM urządzeniu. Istniejący 32-bajtowy klucz AES szyfrowany jest przez age przez stdin, a zaszyfrowany wynik trafia do osobnego pliku Magazyn/recovery/magazyn-v1-aes256-key-offline.age po sprawdzeniu NAS. Nie nadpisuje istniejącego pliku YubiKey/age ani lokalnego AES.

Kroki dla właściciela:
1. Na niezależnym komputerze (nie AI Serverze) wygenerować tożsamość age X25519 przez age-keygen. Prywatny plik identity zabezpieczyć na odłączonym nośniku i dodatkowym osobnym miejscu offline. NIE przesyłać prywatnego identity do ChatGPT, GitHub, Telegrama ani AI Servera.
2. Na serwer dostarczyć jedynie publiczny recipient zaczynający się od age1... (np. prywatny plik z publiczną wartością w staging).
3. Jako harrypotter uruchomić: PYTHONPATH=apps/magazyn [PYTHON_VENV] -m magazyn.offline_escrow --key-file [AES_KEY] --public-recipient-file [AGE_PUBLIC_RECIPIENT] --mount /mnt/AI_Platform.
4. Na niezależnym komputerze odszyfrować recovery .age przy użyciu prywatnego identity, zweryfikować AES i archiwum .mgzb oraz wykonać próbny restore do izolowanej bazy.
5. Dopiero po fizycznym teście oznaczyć ten wariant jako PASS. Do tego czasu PENDING.

Wykonano test szyfrowania i odszyfrowania przez age z syntetycznym kluczem i recipientem: 3/3 PASS. Rzeczywisty AES NIE jest jeszcze zaszyfrowany do alternatywnego recipienta, ponieważ nie dostarczono publicznego klucza wygenerowanego poza serwerem.

## 5. Pozostałe bramki produkcyjne

- Kontrola roli administrator/użytkownik, CSRF, kont, sesji, limitów logowania, backend API: testy DEV PASS.
- Dostęp Tailscale i uprawnienia pracowników (tailnet ACL) do potwierdzenia. Brak publicznego wystawienia.
- Nie uruchamiano GPU, ComfyUI, Ollamy ani RM.
- Pozostaje: drugi fizyczny recovery drill, najbliższe automatyczne daily/weekly, odrębny błąd Stage K weekly, akceptacja sposobu dostępu pracowników i końcowy rollout/rollback produkcji.
