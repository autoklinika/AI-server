# Magazyn V1 — odbiór Etapów 1–4 i plan produkcyjny

27 października 2026 | Serwer AI / AI Platform | gałąź DEV

**Werdykt:** 198/198 testów PASS, ale **PRODUKCJA: NO-GO** do zamknięcia wymienionych warunków. Brak merge do main, brak wdrożenia produkcyjnej instancji.

## Etap 1 — operacje magazynowe

Zweryfikowano na osobnych syntetycznych bazach SQLite: przyjęcie produktu i kolejnych sztuk; wydanie z obowiązkowym powodem i numerem zlecenia; przesunięcie między lokalizacjami; korektę stanu wyłącznie przez administratora; inwentaryzację ze sprawdzaniem oczekiwanej ilości i pełnym rollbackiem przy konflikcie choćby jednego wiersza; historię operatorów; bezpieczną edycję/usuwanie historii przez administratora bez zmiany ilości; brak nadmiernych wydań i przepełnienia 2 miliardów sztuk w jednej lokalizacji. Dotychczasowe testy CSV/XLSX, dokumentów, sesji i ról nadal przechodzą.

Testy obejmują niedozwolone operacje, CSRF, błędy formularza i uprawnienia pracowników. Nie pisano danych syntetycznych do rzeczywistego magazynu.

## Etap 2 — zamówienia, dostawy i prywatne alerty

Nowa akcja **Przyjmij zamówioną dostawę** w szczegółach produktu dla administratora:

- Przyjmuje tylko potwierdzoną fizycznie liczbę sztuk, nie większą niż pozostałe zamówienie.
- Dostawa częściowa zwiększa stan i zmniejsza liczbę sztuk oczekujących, pozostawiając status Zamówione.
- Dostawa pełna zwiększa stan i zamyka status Zamówione.
- ECU umożliwia wybór Nowy/Używany i sprawności; elektronika nie dziedziczy stanów ECU.
- Zapis stanu, wpisu historii i zmiany statusu zamówienia odbywa się w JEDNEJ transakcji SQLite BEGIN IMMEDIATE. Błędy ilości, lokalizacji, stanu ECU lub konflikt dwóch równoczesnych przyjęć wycofują zapis.
- Zwykły przycisk + Przyjmij nie zmienia automatycznie zamówienia. Do obsługi dostawy służy specjalna akcja.

Testy: uprawnienia, statusy, stany minimalne, brak duplikatów alertów, wznowienie cyklu po uzupełnieniu zapasu — PASS. Prawdziwa przeglądarka Firefox, viewport 390×844 na syntetycznej bazie: dostawa 2 z 5, następnie pozostałe 3, kontrola ilości i historii — PASS. Nie wysyłano testowych Telegramów do rzeczywistych odbiorców.

## Etap 3 — bezpieczeństwo i DR

Na rzeczywistej bazie DEV bez zapisywania do towarów: SQLite schema v3, integrity_check, foreign_key_check i SHA-256 załączników PASS. Wykonano nową spójną kopię SQLite Backup API, zaszyfrowano AES-256-GCM, przesłano na GlobalNAS, ponownie pobrano i zweryfikowano, odtworzono do RAM oraz porównano stany, konta, historię i załączniki ze źródłem: PASS. Tymczasowe jawne dane w RAM usunięte, kolejka oczekujących kopii pusta.

HTTPS Tailscale: certyfikat i healthz PASS, backend nasłuchuje loopback, nieautoryzowane API HTTP 401. Dotychczasowe kontrole ról, CSRF, sesji, hardeningu loginów, uploadów i powiadomień — PASS.

**Otwarte bramki:**

1. **Stage K tygodniowy:** ostatni wynik z 25.10.2026 to FAIL, faza knowledge_backup, rc=1. Historyczna przyczyna nie może być udowodniona: K5 przechwytuje stderr K2, a raportuje tylko rc. Aktualne odczyty Knowledge/ERS/CRT z produkcyjnego PostgreSQL w transakcji READ ONLY: PASS; marker i mały tymczasowy zapis/odczyt na prawdziwym GlobalNAS: PASS; ostatni daily Stage K z 27.10: PASS. To NIE jest dowód naprawy weekly. Nie zmieniano kodu i archiwów produkcyjnych Stage K. Kolejny rzeczywisty weekly: niedziela **01.11.2026 02:30 CET**; trzeba odebrać backup i trzy restore PASS (Knowledge, Domains, Adapters).
2. **Niezależny klucz DR:** fizyczne odzyskiwanie YubiKey 5C/PIN wcześniej PASS. Mechanizm drugiego recipienta age X25519 przygotowany i testowany syntetycznie. Wciąż BRAK prawdziwego recipienta z zewnętrznego komputera i fizycznego testu odzyskania AES oraz odtworzenia kopii poza serwerem. Prywatnego identity nigdy nie przesyłać na AI Platform ani GitHub.
3. **Harmonogram dzienny Magazynu:** godzinny monitor Magazynu uruchomiony przez istniejący Stage K PASS. Pierwszy cykl daily po podłączeniu drop-in wypada **28.10.2026 o 02:30 CET**. Musi zostać niezależnie potwierdzony w dzienniku i archiwach NAS.
4. **Dostęp pracowników:** HTTPS działa dla właściciela, lecz potrzebny jest odbiór indywidualnego pracownika na jego urządzeniu, Tailscale ACL/Grants oraz kontroli uprawnień roli. Bez Funnel i bez publicznego Internetu.

## Etap 4 — kontrola GO/NO-GO i cutover

Dostarczono polecenie audit-only magazyn.release_gate. Odczytuje bazę, relacje, sumy SHA-256 dokumentów, uprawnienia SQLite 0600, najnowszą zaszyfrowaną kopię GlobalNAS, kolejkę, JUnit/pytest, dzienny i tygodniowy Stage K wraz ze wszystkimi walidacjami restore, a także HTTPS. Nie uruchamia GPU/LLM, nowego schedulera, usług ani produkcji. Zwraca JSON i kod 2 przy NO-GO.

Uruchomienie z katalogu głównego worktree:

    PYTHONPATH=apps/magazyn <VENV_PYTHON> -m magazyn.release_gate --bridge-config <PRIVATE_BRIDGE_JSON> --junit-report <JUNIT_XML>

Manualne poświadczenia (TYLKO PO FIZYCZNYM ODBIORZE):
- --offhost-drill-verified
- --daily-timer-verified
- --employee-acl-verified

Nie można ominąć statusu FAIL tygodniowego Stage K tymi trzema przełącznikami. Obecny wynik audytu zapisano poza repo w prywatnym staging: /srv/ai-data/staging/magazyn-release-audit-20261027/release-gate.json, raport testów pytest.xml.

### Minimalny, odwracalny plan promocji DEV do produkcji — tylko po GO

1. Zamrozić przetestowany commit/release candidate; po zgodzie scalić przez PR do main. Wdrożyć z wersjonowanego, niezmiennego katalogu, nigdy bezpośrednio z modyfikowalnego worktree DEV.
2. W oknie serwisowym zatrzymać zapisy WebGUI i Telegram DEV; wykonać ostateczny zaszyfrowany backup, verify i restore w RAM. Skopiować stan do osobnego prywatnego magazynu produkcyjnego 0700/0600 przez SQLite Backup API; nigdy nie kopiować aktywnego pliku WAL.
3. Uruchomić stabilny kod oraz bazę produkcyjną. Usługi produkcyjne powinny ZASTĄPIĆ DEV, nie działać równolegle z tym samym tokenem bota lub tą samą bazą i portem. Zachować istniejący endpoint HTTPS; dla produkcji wymusić MAGAZYN_COOKIE_SECURE=1.
4. Przepiąć wyłącznie trzy własne drop-in Magazynu w istniejących usługach Stage K na bazę, klucz i kod wersjonowanego wydania. Bez nowego harmonogramu i bez zmian pozostałych kopii Stage K.
5. Sprawdzić sesje, role, dokumentację, wydania z obowiązkowym powodem, powiadomienia, pierwszy backup i restore do RAM. Zapisać protokół odbioru.

### Rollback

- Jeśli nie było nowych transakcji: wyłączyć nowe usługi, cofnąć konfigurację tylko Magazynu, przywrócić zweryfikowaną dotychczasową wersję i sprawdzić integralność.
- Jeśli po cutover powstały nowe operacje, NIE przywracać starszej kopii, która utraciłaby historię i stany. Najpierw zatrzymać oba procesy zapisu, wykonać snapshot aktualnej produkcyjnej bazy i rozstrzygnąć naprawę aplikacji lub przeniesienie zachowanych nowych zapisów. Nie usuwać dokumentów ani zamówień.
- Nie uruchamiać dwóch instancji Telegram z tym samym tokenem. Nie wykonywać tailscale serve reset ani nie usuwać oryginalnych timerów Stage K; rollback harmonogramu Magazynu polega na odwróceniu jego własnych trzech drop-in.

**Stan wydania: funkcje i testy DEV gotowe; produkcyjne GO wyłącznie po niezależnych bramkach.**
