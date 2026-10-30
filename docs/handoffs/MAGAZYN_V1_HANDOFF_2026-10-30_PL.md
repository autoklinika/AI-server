# Prompt startowy — kontynuacja Magazynu V1 (stan 30.10.2026)

Poniższy tekst można wkleić jako pierwszą wiadomość do nowej rozmowy z ChatGPT. Przed wykonywaniem zmian przeczytaj raport projektu:
[Magazyn V1 — raport prac 30.10.2026](../reports/MAGAZYN_V1_STATUS_2026-10-30_PL.md).

---

# Kontynuujemy projekt Serwer AI / Magazyn V1

Działamy na realnym, autoryzowanym serwerze AI Platform. **Nie zaczynaj projektu od zera** i **nie proponuj od nowa już zatwierdzonych rozwiązań**. Ostatnie zadanie dotyczyło dopracowania wyglądu Magazynu, w szczególności okien modalnych. Użytkownik potwierdził: **„teraz jest super”**.

## 1. Cel obecnego etapu

**Kontynuujemy dopracowywanie istniejącego wyglądu Magazynu w izolowanym DEV.** Nie wykonuj redesignu ani produkcyjnego GO. Użytkownik wskaże kolejną zakładkę lub element interfejsu do poprawienia. Jeśli nie wskazał jeszcze elementu, zapytaj krótko, nad którym ekranem przechodzimy do pracy; nie zmieniaj zaakceptowanych okien.

## 2. Produkcja — stan potwierdzony 30.10.2026

- WebGUI Magazyn i bot Telegram działają produkcyjnie.
- Produkcyjny backend nasłuchuje tylko na loopback, dostęp użytkowników przez prywatny HTTPS Tailscale (port 8443).
- Produkcyjne wydanie zawiera **TME API v2 + Mouser Search API**. Tokeny już skonfigurowane; **nie żądaj ich ponownie ani nie wypisuj ich wartości**.
- DigiKey i Farnell nie są wdrożone; użytkownik zdecydował pracować na razie tylko z TME/Mouser. Discord jest odłożony.
- Stage K daily/weekly/monitor jest aktywny; GlobalNAS backup i dwa sprzętowe YubiKey 5C mają wcześniej potwierdzone testy odzyskiwania.
- Migawka produkcyjna: 7 produktów, 7 bilansów, 11 zdarzeń, 2 lokalizacje, 2 konta, 1 dokument; SQLite integrity_check = OK.
- **Zakaz modyfikacji produkcji bez wyraźnego GO właściciela.** Nie restartuj produkcji, Telegrama, RM, Tailscale Serve, nie zmieniaj ACL ani schedulerów podczas prac nad UI. Do kontroli statusu możesz używać read-only.
- Produkcja używa wydania o identyfikatorze suppliers-tme-mouser-20261030.

## 3. DEV — aktualna praca na serwerze

- Izolowany katalog: **/srv/ai-data/staging/magazyn-hurtownie-webgui-dev-20261029/**.
- Kod UI: magazyn/static/; ostatnie arkusze stylów: style.css, polish.css, modals.css.
- Backend DEV na loopback, port 18766; prywatny dostęp HTTPS/Tailscale na porcie 18767.
- Konto DEV i jego sekret pozostają zapisane wyłącznie na autoryzowanym hoście; **nie wklejaj loginów, haseł ani tokenów do raportów i repozytorium**.
- Raporty i testy modułu PDF: **/srv/ai-data/staging/magazyn-pdf-improvements-dev-20261030/**.
- Raporty i testy ujednolicenia modali: **/srv/ai-data/staging/magazyn-modal-unified-dev-20261030/**.
- Przeglądarkowy zestaw testów UI: **/srv/ai-data/staging/magazyn-modal-polish-dev-20261030/**.
- W repo GitHub historyczny kod Magazynu jest przede wszystkim na gałęzi feature/magazyn-v1-dev-20261026 pod apps/magazyn. **Bieżący kod staging DEV jest nowszy od tej gałęzi. Raport w GitHub nie jest commitowaniem całego DEV ani releasem.**
- Najnowsza kopia statusu i zaległości: dokument MAGAZYN_V1_STATUS_2026-10-30_PL.md w docs/reports tego repo.

## 4. Co już zostało zrobione

**Funkcjonalność Magazynu:** logowanie i role, ECU, elektronika, wielolokalizacyjne stany, przyjęcie/wydanie/przesunięcie/korekta, historia, inwentaryzacja, minimum i prywatne alerty per produkt, import/eksport CSV/XLSX, załączniki PDF/PNG/JPG, stan Zamówione, Telegram, backup/DR GlobalNAS.

**Produkcja:** TME i Mouser. TME jest pierwszym źródłem, Mouser służy do porównania lub fallbacku. Brak automatycznego przyjęcia produktu na stan podczas wyszukiwania.

**Nowszy DEV:**
- Wyszukiwanie wariantów MPN na przykładzie TJA1050T; wybór pełnego oznaczenia zamiast zgadywania.
- Bezpieczne wyszukiwanie producenta poza hurtowniami: LM2309Y ma tylko możliwy odnośnik do LM2309 Leiditech, bez potwierdzenia tożsamości obu numerów.
- PDF z bezpośredniego linku producenta lub z dysku/telefonu, do 8 MiB. Tekst do 12 stron, OCR CPU maks. 6 stron, weryfikacja MPN i propozycje z cytatami.
- Parser prostowników zrealizowany i odebrany na MURD620CT: DPAK, 200 V VRRM, 6 A IF(AV) na element / 3 A na diodę, trr 35 ns. Nie mylić limitów z nominalnym napięciem zasilania.
- Skany i niepewne warianty nie wypełniają samowolnie pól; użytkownik zatwierdza propozycje i załącznik.
- Dopracowane Ustawienia, formularze, asystent hurtowni/PDF i mobilna ergonomia.

## 5. OSTATNIA DECYZJA — okna modalne ZATWIERDZONE

Użytkownik chciał, aby modal dodawania elektroniki był znacznie większy, a **wszystkie okna modalne w każdej zakładce miały jednakowy rozmiar**. Zmiany wykonano i użytkownik potwierdził, że wygląd jest właściwy.

- W DEV **wszystkie 7 typów modali mają identyczny rozmiar zewnętrzny** w danym widoku.
- CSS jest w magazyn/static/modals.css, ładowanym po style.css i polish.css.
- Desktop: maksymalna szerokość 1720 px, z marginesem 24 px do viewportu; wysokość maksymalna 1140 px z marginesem 16 px. Przy Firefox viewport 1390×854 każdy modal wynosi 1366×838 px.
- Telefon: pełna szerokość i niemal pełna wysokość dla wszystkich okien; tablet także ma jeden rozmiar.
- Wewnętrzne krótkie formularze haseł pozostają wyśrodkowane. Nagłówki sticky, przyciski Zamknij/Zapisz i przewijanie działają.
- **Nie zmieniaj rozmiarów modali ponownie bez polecenia właściciela.** Kontynuuj pracę nad innymi elementami UI.

## 6. Testy i bezpieczeństwo zmian

- Aktualne DEV verify.sh: **54/54 PASS**. To testy dedykowanego DEV modułu, nie pełny zestaw historyczny.
- Firefox desktop/tablet/mobile/small: jednolite rozmiary 7 modali, przyciski, scroll, PDF, PASS.
- Osobno testowano rzeczywisty viewport 390 i 344 px przez iframe, PASS.
- PDF MURD620CT w desktop/mobile i zachowanie załącznika, PASS.
- Zdarzenia biznesowe podczas testów przeglądarkowych: bez zapisów do produkcji; syntetyczne operacje tylko na oddzielnej bazie.
- Po każdej przyszłej poprawce UI: najpierw zabezpiecz oryginały DEV, wykonaj zrzuty przed/po, testy JS, Firefox desktop/mobile i regresję, potem sprawdź hashe produkcji.
- Nie kopiuj credentials/API keys, SQLite, backupów, kluczy, prywatnych zrzutów z danymi do **publicznego** GitHub.

## 7. Co dalej

Prace nad wyglądem kontynuujemy **tylko w DEV**. Proponowane obszary po wyborze użytkownika: ekran główny i katalog, wyszukiwarka/filtry, karty produktów, formularze operacji, Ustawienia/hurtownie, mobilna nawigacja. Nie rozszerzaj zakresu bez uzgodnienia.

Przed przyszłą synchronizacją kodu do GitHub trzeba oddzielnie przejrzeć diff staging vs repo, przygotować bezpieczny branch/PR, bez sekretów. Dopiero po całym odbiorze i **oddzielnym GO** można rozważyć release produkcyjny wraz ze świeżym szyfrowanym backupem, testem przywrócenia i rollbackiem kodu bez cofania danych produkcyjnych.

**Pierwsza czynność nowej rozmowy:** potwierdź przeczytanie raportu Magazyn V1 z GitHub, sprawdź aktualny DEV, zachowaj zatwierdzone gabaryty modali i poproś o kolejny wskazany element wyglądu. Nie uruchamiaj samodzielnie wdrożenia produkcyjnego.
