# Magazyn V1 — raport dotychczasowych prac (30.10.2026)

**Projekt:** Serwer AI / AI Platform — Magazyn V1  
**Kontrola hosta:** 30.10.2026, około 16:13 CET  
**Zakres:** ewidencja ECU i elektroniki, WebGUI, Telegram, backup/DR, hurtownie, dokumentacja PDF/OCR, interfejs.

**Bezpieczeństwo:** repozytorium GitHub jest publiczne. Ten raport nie zawiera haseł, loginów, tokenów TME/Mouser, prywatnego adresu tailnet, PIN/PUK, kluczy AES/PIV, baz danych ani szyfrowanych materiałów odzyskiwania. Dokument **nie** jest nowym releasem ani przeniesieniem źródeł DEV do GitHub.

## 1. Założenia i przyjęte decyzje

- Magazyn V1 to ilościowa ewidencja sterowników ECU i elementów elektronicznych. Backend: FastAPI, SQLite; WebGUI domyślnie PL.
- ECU: marka, typ i nazwa, wiele numerów Bosch/OEM/zamienników, HW/SW, lokalizacje. **Nowy/Używany** osobno od **Sprawny/Uszkodzony/Nieznany**.
- Elektronika: oznaczenie, producent, kategoria, obudowa, parametry, dodatkowe numery, dokumentacja PDF/PNG/JPG oraz status Zamówione niezwiększający stanu magazynowego.
- Operacje: przyjęcie, wydanie z powodem, przesunięcie, korekty, inwentaryzacja z historią i autorem, nr zlecenia, uwagi. Wyszukiwanie globalne, filtry oraz CSV/XLSX.
- Administrator zarządza historią, kontami, ustawieniami i backupem; pracownicy wykonują podstawowe operacje.
- Minimalne stany i prywatne alerty: wskazany odbiorca **dla konkretnej pozycji**, bez broadcastu i bez ustawień dziedziczonych z kategorii.
- Wygląd: zatwierdzony pomarańcz/grafit/szary; **dopracowywać obecny projekt**, a nie rozpoczynać redesign.
- Resource Manager (RM) kontroluje GPU; Magazyn nie omija RM ani nie tworzy własnych schedulerów.
- Hurtownie: **tylko TME i Mouser**. DigiKey i Farnell nie mają tokenów i nie są objęte wydaniem; Discord odłożony.
- Aplikacja Android oraz skanowanie fabrycznych etykiet ECU aparatem to odrębny projekt, **niepotwierdzony jako część bieżącego wydania produkcyjnego**.

## 2. Chronologia

| Okres | Zakres | Stan |
|---|---|---|
| 25–27.10 | Wymagania V1, konta, role, katalog ECU/elektroniki, lokalizacje, operacje, historia, minimum, import/eksport, dokumenty | Funkcje odebrane w DEV |
| 27–29.10 | Telegram, mobile WebGUI, Tailscale, Stage K, backup GlobalNAS i odzyskiwanie przez 2 YubiKey 5C PIV | Formalny GO 29.10 |
| 28.10 | Uruchomienie podstawowego Magazynu produkcyjnego przez HTTPS w prywatnym tailnecie | LIVE |
| 29–30.10 | Integracja TME v2 + Mouser, odczyt produktów/parametrów/PDF i podpowiedzi w formularzu | Produkcyjny GO 30.10 |
| 30.10 | Warianty MPN, fallback producenta, PDF z linku i dysku, OCR CPU, parser prostowników, poprawki UI | Wyłącznie DEV |
| 30.10 | Ujednolicone i znacznie powiększone wszystkie okna modalne | **Wygląd zaakceptowany przez użytkownika** |

Historyczny [formalny GO](https://github.com/autoklinika/AI-server/blob/feature/magazyn-v1-dev-20261026/apps/magazyn/docs/MAGAZYN_V1_FORMAL_GO_2026-10-29_PL.md) dokumentuje także odbiór 2 YubiKey, GlobalNAS i izolacji Tailscale.

## 3. Aktualny stan produkcji

- WebGUI produkcyjne zwraca service=magazyn, environment=production; backend tylko na loopback, dostęp użytkownika przez prywatne HTTPS/Tailscale na porcie 8443.
- Usługi **magazyn-webgui.service** i **magazyn-telegram.service** działają.
- Stage K: **daily, weekly i monitor — active**, bez nowych timerów/crona.
- Aktywny release: **suppliers-tme-mouser-20261030**, wyłącznie TME/Mouser; dane API zaszyfrowane i odseparowane od kodu.
- Podczas produkcyjnego GO TME/Mouser wykonano świeży zaszyfrowany backup, weryfikację GlobalNAS, testy realnego API i przygotowano rollback kodu. Odbiór dwóch sprzętowych kluczy odzyskiwania: PASS 29.10.
- Ostatnia migawka SQLite (30.10 około 16:13 CET): **7 produktów, 7 bilansów lokalizacyjnych, 11 zdarzeń historii, 2 lokalizacje, 2 konta, 1 dokument**. PRAGMA integrity_check: **OK**.
- Produkcyjnego kodu i bazy **nie zmieniano** podczas późniejszych prac PDF/OCR/GUI. Weryfikowano endpoint zdrowia produkcji i hash jej statycznych plików.

**Uwaga o wynikach:** formalne testy z 29.10 obejmowały 227/227 przypadków ówczesnej wersji. Aktualne 54/54 to **oddzielny** pakiet regresyjny obecnego izolowanego DEV. To nie ten sam zbiór i nie należy sumować wyników.

## 4. TME i Mouser — zakres produkcyjny

- **TME API v2:** OAuth2, katalog produktów, parametry, dokumenty (products, products/parameters, products/files). Rzeczywiste wyszukiwanie BTS134D: PASS.
- **Mouser Search API:** klucz API, rozpoznawanie dokładnego MPN, producenta, danych katalogowych, dostępności i datasheetów. Rzeczywiste BTS134D: PASS.
- Formularz elektroniki: najpierw TME; przy dokładnym dopasowaniu przycisk **Porównaj z Mouser**; Mouser jest też fallbackiem przy braku dokładnego MPN w TME.
- Propozycje wymagają świadomej akceptacji; samo wyszukiwanie nie dopisuje produktu ani dokumentów.
- Nie zakładać, że nowe funkcje DEV (TJA1050T, LM2309Y, OCR, MURD620CT, ujednolicone modale) są w obecnej produkcji.

## 5. Zmiany rozwijane i odebrane w DEV (nie wdrożone do produkcji)

Izolowany WebGUI DEV: osobny loopback na porcie 18766 i prywatne HTTPS na porcie 18767, odrębna SQLite, konto testowe, zaszyfrowane dane dostawców. TME/Mouser w DEV mają aktywne i sprawdzone konfiguracje; DigiKey/Farnell wyłączone.

### 5.1 Identyfikacja części, katalogi i źródła

- **TJA1050T:** wyszukiwarka prezentuje pełne numery różnych wersji, np. TJA1050T/CM,118 i TJA1050T/N1,112. Użytkownik wybiera wariant; nie ma automatycznego utożsamiania różnych MPN.
- **LM2309Y:** TME/Mouser nie mają dokładnego numeru; strona producenta Leiditech potwierdza LM2309 w SOT-23, ale **nie** potwierdza LM2309Y. Kandydat z ostrzeżeniem, propozycje odznaczone, żadnych domyślnych parametrów elektrycznych.
- Można analizować **PDF z linku HTTPS producenta** (zatwierdzone domeny, limit pliku, bezpieczne przekierowania, sprawdzenie formatu/MPN), a potem świadomie dołączyć dokument.
- Można analizować **PDF z dysku/telefonu** bez wcześniejszego wyszukiwania w hurtowniach. Plik pozostaje załącznikiem do zapisania przy finalnym dodaniu elementu.
- PDF: limit **8 MiB**, tekst pierwszych **12 stron**, lokalny **Tesseract CPU OCR** maks. **6 stron** bez użytecznej warstwy tekstowej. Bez nowych usług GPU/RM. Czytelny PDF z niepasującym MPN daje status needs_identification; nie kopiuje danych innego elementu.
- **MURD620CT:** dedykowany odczyt danych prostownika ultraszybkiego: producent onsemi/ON Semiconductor, kategoria diody, obudowa DPAK, 200 V VRRM **maks. napięcie wsteczne**, 6 A IF(AV) **na element** i 3 A na diodę, temperatura katalogowa oraz 35 ns trr. G/T4/T4G klasyfikowane jako opakowaniowe tylko na podstawie tabeli zamówieniowej.
- Dla MURD620CT wykonano test na późniejszym oficjalnym PDF producenta na serwerze i testy przeglądarkowe desktop/mobile; oryginalny czterostronicowy PDF zgłoszony przez użytkownika przeanalizowano w rozmowie. Użytkownik potwierdził, że poprawka na jego pliku działa.
- OCR daje wartości do sprawdzenia, z niższą pewnością; nie wolno tworzyć niepotwierdzonych danych ani zastępować MPN domysłami.

### 5.2 Wygląd — ostatni zaakceptowany stan

- Zachowano pomarańczowo-szary motyw. W DEV poprawiono Ustawienia, skróty, karty hurtowni, asystenta PDF, formularze i mobilny layout.
- **Wszystkie 7 modali ma identyczny rozmiar zewnętrzny w danym widoku:** Dodaj ECU, Dodaj elektronikę, Szczegóły/operacje, Historia, Zmień hasło, Reset hasła pracownika, Podgląd dokumentów.
- Maksymalny desktop: szerokość min(1720px, szerokość viewportu minus 24px), wysokość min(1140px, wysokość viewportu minus 16px).
- Firefox viewport 1390×854 CSS px: **wszystkie 7 modali = 1366×838 px**. Przed ostateczną zmianą modal elektroniki miał szerokość 1120px.
- Tablet: wspólne wymiary dopasowane do ekranu; telefon: pełna szerokość i niemal pełna wysokość dla wszystkich modali. Wewnętrzna zawartość krótkich okien hasła jest wyśrodkowana.
- Zachowano przewijanie, sticky nagłówki, dostępne przyciski Zamknij/Zapisz, dokumentację i operacje.
- **Użytkownik potwierdził: „teraz jest super”.** Nie zmieniać znów rozmiarów okien bez jego polecenia.

### 5.3 Testy

- Aktualne verify.sh w DEV: **54/54 PASS**.
- Firefox desktop/tablet/mobile/small: 7 okien o jednakowych wymiarach, przewijanie, formularze, przyciski, Escape, PASS.
- Dodatkowe wąskie widoki CSS 390px i 344px: PASS.
- Prawdziwy PDF MURD620CT (oficjalna późniejsza wersja), przygotowanie dziewięciu pól i załącznika, desktop/mobile: PASS.
- Inne scenariusze DEV: TME/Mouser BTS134D, wariant TJA1050T, kandydat LM2309Y, OCR skanu, niepoprawny PDF, uprawnienia: PASS.
- Nie dodawano syntetycznych produktów do działającej produkcji; mocki i źródła live rozróżnione.

## 6. Gdzie jest najnowszy kod

| Rola | Identyfikator katalogu lub gałęzi |
|---|---|
| Produkcja | magazyn-v1 / release suppliers-tme-mouser-20261030 |
| Aktualny izolowany DEV | staging/magazyn-hurtownie-webgui-dev-20261029 |
| Testy i raport PDF | staging/magazyn-pdf-improvements-dev-20261030 |
| Testy i raport modali | staging/magazyn-modal-unified-dev-20261030 |
| Historyczna baza kodu w GitHub | feature/magazyn-v1-dev-20261026, apps/magazyn |

**Istotne:** najnowszy DEV staging na uprawnionym hoście jest obecnie bardziej aktualny niż wersjonowany kod Magazynu w GitHub. Publikacja **tego raportu i handoffu nie synchronizuje źródeł** CSS/PDF/OCR ani nie wdraża niczego do produkcji. Sync kodu wymaga odrębnej gałęzi, przeglądu różnic, testów i sprawdzenia sekretów.

## 7. Kolejne kroki i granice

1. Kontynuować dopracowywanie **obecnego UI DEV** według wskazanego przez użytkownika następnego obszaru. **Zachować zatwierdzone rozmiary modali.**
2. Po zakończeniu etapu UX osobno uzgodnić synchronizację kodu DEV z repozytorium (bez SQLite, tokenów, PIN, kluczy, haseł, danych pracowników i testowych plików użytkownika).
3. Przed ewentualnym nowym produkcyjnym GO: pełne testy Magazynu, dostawców, PDF/OCR, ról, Telegrama, Tailscale, Stage K, backupu i odzyskiwania, UI desktop/mobile, manifest i rollback.
4. Produkcję zmieniać **wyłącznie po wyraźnej zgodzie użytkownika**. Przed cutover wykonać nowy zaszyfrowany backup; rollback kodu nie może cofać bieżących stanów SQLite.
5. Nie ingerować w inne usługi AI Platform, RM, Stage K, Tailscale Serve/ACL i Telegram podczas poprawiania CSS.
6. DigiKey, Farnell, Discord i Android pozostają osobnymi, odłożonymi zakresami.

## 8. Powiązane dokumenty

- [Magazyn V1 — formalne GO 29.10](https://github.com/autoklinika/AI-server/blob/feature/magazyn-v1-dev-20261026/apps/magazyn/docs/MAGAZYN_V1_FORMAL_GO_2026-10-29_PL.md).
- [Historyczne README źródeł Magazynu](https://github.com/autoklinika/AI-server/blob/feature/magazyn-v1-dev-20261026/apps/magazyn/README.md).
- [Handoff do kolejnej rozmowy](../handoffs/MAGAZYN_V1_HANDOFF_2026-10-30_PL.md).

**Aktualna decyzja właściciela:** jednakowe, bardzo duże okna modalne zostały zaakceptowane; **następny etap to dalsze poprawki wyglądu DEV**, nie automatyczny deploy.
