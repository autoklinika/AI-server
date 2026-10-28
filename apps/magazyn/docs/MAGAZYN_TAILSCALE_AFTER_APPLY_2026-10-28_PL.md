# Magazyn V1 / AI Platform — Tailscale po zapisaniu nowych Grants

Data: 28.10.2026, 23:25 CET.
Serwer: produkcyjny ai-server, Tailscale 1.102.4.
Wynik serwerowy: PASS. Test telefonu pracownika po zmianie: PENDING.

## Wykonana kontrola

Użytkownik samodzielnie zapisał nową politykę w centralnej konsoli Tailscale. Asystent nie zmieniał żadnych ustawień sieci ani usług produkcyjnych.

Sprawdzono na żywym serwerze: tailscale debug netmap (Cached=false), tailscale status --json, analizę efektywnych PacketFilter Srcs/Dsts/IPProto i zgodność IP serwera z docelowym 100.112.82.87.

Po zapisaniu polityki serwer otrzymał dokładnie DWA filtry PacketFilter:

- Reguła 1: zakres źródłowy obejmuje 8 własnych peerów (bezpośrednich członków tailnetu); zachowany pełny dostęp do wszystkich portów.
- Reguła 2: zakres źródłowy obejmuje 1 udostępniony peer ShareeNode, online; pozwala wyłącznie na TCP 8443 do 100.112.82.87/32.
- Udostępniony peer NIE pasuje do reguły 1. Nie istnieje trzecia reguła pozwalająca mu obejść ograniczenie.

Macierz dla udostępnionego klienta:

| TCP | Port / usługa | Efektywna decyzja |
|---|---|---|
| 22 | SSH | DENY |
| 80 | HTTP | DENY |
| 443 | AI Platform | DENY |
| 8443 | Magazyn V1 | ALLOW |
| 9090 | Cockpit | DENY |
| 51907 | Inna usługa | DENY |
| 57629 | Inna usługa | DENY |

Powyższe to weryfikacja działającego PacketFilter serwera, NIE aktywne połączenia TCP z telefonu pracownika.

## Ciągłość działania

- HTTPS Magazynu port 8443, certyfikat ważny, HTTP 200.
- HTTPS panelu AI Platform port 443 odpowiada z poziomu administracyjnego urządzenia serwerowego, HTTP 200.
- Jednostki magazyn-webgui.service i magazyn-telegram.service pozostają aktywne z Result=success.
- SQLite Magazynu bez błędów integralności, jedno konto admin i jedno konto pracownika.
- Tailscale Serve nadal tailnet-only; nie uruchamiano Funnel.
- UFW pozostaje aktywne, lecz odczyt reguł UFW i nft wymaga sudo. To oddzielny audyt host-firewalla, nie unieważnia dowodu ograniczenia w efektywnym Tailscale PacketFilter.

Prywatny, zanonimizowany dowód zapisano w /srv/ai-data/magazyn-v1/reports/tailscale-policy-after-apply-20261028.json (0600). Nie zawiera maili, haseł, surowej netmap ani kluczy sieci.

## Pozostały krótki test po stronie użytkownika

1. Na telefonie pracownika, na JEGO koncie Tailscale, otworzyć adres HTTPS Magazynu na porcie 8443 i potwierdzić logowanie.
2. Spróbować otworzyć panel AI Platform na porcie 443, który powinien być niedostępny.
3. Potwierdzić wynik bez przesyłania haseł lub tokenów.

Po tym potwierdzeniu można zaliczyć formalne ograniczenie pracownika do Magazynu. Nie trzeba już zmieniać polityki serwera.

Zastrzeżenie: autogroup:member ma nadal pełny dostęp dla wszystkich bezpośrednich członków tailnetu, w tym przyszłych. Pracownik musi pozostawać odbiorcą udostępnionej maszyny, a nie pełnym Memberem. Obecna konfiguracja pasuje do jednego rzeczywiście udostępnionego peera.

Źródła Tailscale:
https://tailscale.com/docs/features/sharing
https://tailscale.com/docs/reference/syntax/grants
