# Magazyn V1 — formalny GO produkcyjny, 29.10.2026

**DECYZJA: GO.** Audyt produkcyjny wyłącznie odczytowy, brak restartów i zmian danych produkcyjnych.

## Potwierdzony stan wdrożenia

- Produkcyjny kod Magazynu uruchomiony od 28.10.2026 pozostaje na niezmienionym, zamrożonym wydaniu Git `529af02029e1` (tag `magazyn-v1-prod-20261028`).
- Działające usługi to `magazyn-webgui.service` i `magazyn-telegram.service`, bez równoległych usług DEV.
- Magazyn jest dostępny tylko w tailnecie pod znanym adresem HTTPS na porcie 8443. Pracownik posiada dostęp wyłącznie do 8443, nie do panelu AI na 443 ani SSH/Cockpit w Tailscale.
- Automatyczne kopie Magazynu do GlobalNAS i integracja z istniejącym Stage K działają bez dodatkowych schedulerów.

## Fizyczny odbiór dwóch YubiKeyów

Pierwszy YubiKey 5C: test fizycznego odszyfrowania rzeczywistej kopii Magazynu, weryfikacji AES i odtworzenia SQLite w RAM odebrano 27.10.2026. Potwierdzenie w MAGAZYN_YUBIKEY_RECOVERY_2026-10-27_PL.md.

Drugi YubiKey 5C: niezależna, nieeksportowalna para PIV ECC P-256 w slocie 0x82, osobny publiczny recipient age i drugi, osobny ciphertext AES na GlobalNAS. **29.10.2026: fizyczne odszyfrowanie AES przez drugi YubiKey, porównanie oryginalnego klucza AES, weryfikacja autentycznego archiwum GlobalNAS, odtworzenie SQLite w RAM i sprzątnięcie tymczasowych danych — PASS.**

Prywatny raport maszynowy, 0600 na serwerze:
`/srv/ai-data/magazyn-v1/reports/yubikey-spare-real-drill-20261029.json`.

Sumy kontrolne w raporcie pasują do obu recipientów, zapasowego ciphertextu age i rzeczywistego backupu; produkcyjna baza nie była modyfikowana. W żadnym repozytorium nie zapisano PIN-ów, PUK-ów, AES ani prywatnych kluczy PIV.

## Nowy formalny release gate

Zastąpiono odrzucony wariant pendrive/age X25519 walidatorem **dwóch niezależnych YubiKeyów**. Nowa kontrola wymaga:
- historycznego, jawnego potwierdzenia prawdziwego testu fizycznego pierwszego YubiKeya;
- rzeczywistego raportu z fizycznego testu drugiego klucza, 0600, właściwego właściciela;
- różnych recipientów i dwóch osobnych escrow na GlobalNAS;
- zbieżnych SHA-256 raportu z recipientami i drugim ciphertextem;
- wszystkich wyników fizycznego decrypt/restore, w tym przywrócenia SQLite w RAM;
- niezmienionego klucza AES i istniejących zaszyfrowanych archiwów w produkcji.

Po zmianie pakiet testów kontroli release gate: **13/13 PASS**, w tym testy negatywne. Pełny zestaw syntetycznych testów Magazynu: **227/227 PASS**; tylko ostrzeżenie deprecacyjne biblioteki Starlette.

## Formalne uruchomienie na rzeczywistej produkcji

Uruchomiono z rzeczywistymi ścieżkami do produkcyjnego SQLite, GlobalNAS, statusów Stage K i fizycznego raportu oraz z poświadczonymi testami pierwszego YubiKeya, automatycznego timera i dostępu pracownika.

**Wynik 29.10.2026: exit 0, decision=GO, 9/9 PASS.**

| Kontrola | Wynik |
|---|---|
| sqlite | PASS |
| magazyn_backup | PASS |
| stage_k_daily | PASS |
| stage_k_weekly | PASS |
| pytest | PASS |
| https_tls | PASS |
| daily_timer | PASS |
| employee_access | PASS |
| offsite_recovery | PASS |

Lokalny raport wynikowy:
`/srv/ai-data/magazyn-v1/reports/formal-go-dual-yubikey-candidate-20261029.json`.

Przetestowana zmiana dotyczy **narzędzia odbiorowego**, a nie samego uruchomionego WebGUI/bota. Wdrożenie wersjonowanej bramki audytu powinno zachować niezależny katalog kodu, bez zmiany aktywnego release usług.

## Utrzymanie bezpieczeństwa

Po testach odłącz drugi YubiKey i przechowuj go fizycznie oddzielnie od pierwszego i serwera. PUK/sekrety odzyskiwania przechowuj bezpiecznie poza repozytorium.

GO dotyczy zatwierdzonych wymagań Magazynu V1. Nie oznacza automatycznie, że przetestowano jednoczesną awarię całego serwera i GlobalNAS albo przeprowadzono test odtworzenia na oddzielnym komputerze. Dodatkowo dla przyszłych użytkowników typu Member, a nie Tailscale Share, należy ponownie przeprowadzić audyt uprawnień, ponieważ autogroup:member ma nadal szerokie uprawnienia. UFW nie było auditowane z sudo, ale izolację pracownika potwierdzono w filtrze Tailscale i jego telefonie.

**Nie scalono niepowiązanych gałęzi do main i nie restartowano produkcji na potrzeby tej zmiany.**
