# Magazyn V1 — końcowy odbiór dostępu pracownika przez Tailscale

**Data:** 28.10.2026, po zapisaniu nowych Grants.
**Środowisko:** produkcyjny AI Platform / Magazyn V1.
**Status testu pracownika:** PASS.
**Status całej formalnej bramki Magazynu:** nadal NO_GO — tylko brak dodatkowej, niezależnej metody sprzętowego odzyskania AES.

## Dowód odbioru z rzeczywistego urządzenia

Po zapisaniu nowej polityki Tailscale właściciel potwierdził dwa testy na telefonie pracownika, zalogowanym na WŁASNE konto Tailscale, a nie na konto administratora AI Platform:

1. HTTPS Magazyn V1 na 8443 — PASS, działa na telefonie pracownika.
2. HTTPS AI Platform /control na 443 — PASS, panel niedostępny na telefonie pracownika.

Nie pozyskiwano loginów, haseł, tokenów, danych sesji ani zrzutów wrażliwego ekranu.

## Niezależna weryfikacja na serwerze

Wczytano aktualną, niebuforowaną netmap Tailscale przez lokalne narzędzie diagnostyczne:
- Dwie efektywne reguły PacketFilter, zamiast poprzedniego globalnego allow-all.
- 8 peerów wewnętrznych dopuszczonych nadal do pełnego zestawu usług.
- 1 udostępniony peer typu ShareeNode przypisany wyłącznie do docelowego adresu Tailscale serwera 100.112.82.87/32, TCP 8443.
- Dla udostępnionego peera TCP 22, 80, 443, 9090, 51907, 57629 — DENY.
- Utrzymane działanie produkcyjnego Magazynu (HTTPS 200, certyfikat poprawny), Telegrama oraz administracyjnego panelu AI.
- Brak modyfikacji Tailscale Serve, Funnel, systemowych firewalli oraz innych usług.

Potwierdzona jest skuteczność polityki dostępów na tym serwerze i praktyczne zachowanie telefonu, lecz UFW nadal nie był czytany przez sudo. Nie stanowi to blokady tego konkretnego testu segmentacji Tailscale. Zastrzeżenie: przyszłe dodanie pracownika jako bezpośredniego członka tailnetu zamiast użytkownika udostępnionego wymaga ponownego audytu, ponieważ autogroup:member zachowuje szeroki dostęp.

## Formalna kontrola produkcyjna — wynik po odbiorze

Po otrzymaniu potwierdzenia użytkownika ponownie uruchomiono wyłącznie odczytową kontrolę magazyn.release_gate na zamrożonym wydaniu produkcyjnym 529af02029e1. Parametry potwierdzone dowodowo: rzeczywisty timer daily, employee ACL/Grants i dwa testy na telefonie.

Wynik:
- sqlite: PASS
- magazyn_backup: PASS
- stage_k_daily: PASS
- stage_k_weekly: PASS
- pytest: PASS (220/220)
- https_tls: PASS
- daily_timer: PASS
- employee_access: **PASS**
- offsite_recovery: **BLOCKED**

**DECISION = NO_GO**, ponieważ wymagane drugie niezależne odzyskiwanie jeszcze nie zostało odebrane. Nie oznaczać formalnego całego wydania jako GO. Produkcja już działa z tym jawnym wyjątkiem na polecenie właściciela.

Raport formalny z bieżącej kontroli pozostaje w prywatnym katalogu:
 /srv/ai-data/magazyn-v1/reports/production-formal-go-no-go-after-tailscale-20261028.json
(mode 0600). Dowód zanonimizowanej polityki Tailscale:
 /srv/ai-data/magazyn-v1/reports/tailscale-policy-after-apply-20261028.json
(mode 0600).

## Dalszy krok

Drugi YubiKey 5C nadal czeka na konfigurację i fizyczny test odtworzenia. Użytkownik odrzucił alternatywną ścieżkę pendrive/age X25519. Przed GO trzeba dopasować formalny release gate do dwóch YubiKeyów i udokumentować próbę odtworzenia z drugiego urządzenia. Nie resetować istniejącego YubiKeya ani klucza AES.

**Nie zmieniano bazy, kont, kluczy, usług, ACL, backupu czy działającej produkcji podczas końcowego audytu.**
