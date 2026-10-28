# Magazyn V1 — proponowana polityka Tailscale Grants

Data: 28.10.2026. Status: PRZYGOTOWANO, NIE ZAPISANO do centralnego Tailscale.

## Powód

Właściciel dostarczył rzeczywisty domyślny plik HuJSON: grants src=* dst=* ip=*. Efektywny PacketFilter serwera również nie ogranicza portów. Na serwerze zidentyfikowano 8 peerów przypisanych do konta właściciela i 1 peer udostępniony. Tailscale IPv4 serwera to 100.112.82.87.

## Kandydat

Pełny plik gotowy do wklejenia: TAILSCALE_MAGAZYN_GRANTS_PROPOSAL_2026-10-28.hujson.

Zasady:
- autogroup:member → dst=* / ip=* : zachowuje pełen dostęp obecnych bezpośrednich członków tailnetu (w tej chwili urządzenia na jednym koncie).
- autogroup:shared → dst=100.112.82.87 / ip=tcp:8443 : każdy użytkownik korzystający z udostępnienia maszyny może połączyć się tylko do tego hosta i portu Magazynu. Zewnętrzne osoby nadal mogą zobaczyć tylko urządzenia, do których dostały zaproszenie w sharing.
- Zachowano niezmienione reguły SSH-check i nodeAttrs Funnel z polityki użytkownika. Funnel nie został uruchomiony.

Uwaga: to rozwiązanie dotyczy użytkownika korzystającego z UDOSTĘPNIENIA maszyny, nie pełnego, bezpośredniego Membera tailnetu. Gdyby pracownika dodano jako Membera, pierwszy grant dawałby mu zbyt szerokie uprawnienia. Sprawdź w Tailscale Admin Console, że pracownik korzysta z Sharing.

## Zmiana z zachowaniem możliwości powrotu

1. Otwórz https://login.tailscale.com/admin/acls i zachowaj kopię CAŁEGO istniejącego pliku polityki na swoim komputerze.
2. Zastąp dotychczasowy plik pełną propozycją HuJSON.
3. Użyj Preview rules. Sprawdź, czy Twoje konto wciąż ma dostęp do portu 443 i SSH 22 na serwerze, a pracownik tylko TCP 8443.
4. Save wykonaj sam na koncie administratora Tailscale. Nie zamykaj panelu podczas testów.
5. Zweryfikuj na telefonie pracownika: Magazyn 8443 działa, panel 443 i systemowe porty 22, 9090 są niedostępne. Przetestuj połączenia na poziomie TCP, nie tylko komunikat logowania aplikacji.
6. Gdyby zniknął dostęp administratora, przywróć natychmiast zapisaną oryginalną politykę z drugiej karty w konsoli; można także użyć Configuration logs. Przywrócenie starej polityki oznacza tymczasowy powrót szerokiego allow-all.
7. Po potwierdzeniu zapisania zweryfikujemy ponownie efektywny PacketFilter serwera i formalnie zamkniemy employee_access.

## Odbiór

Lokalna weryfikacja statyczna proponowanego pliku oraz zgodności z żywym Tailscale IPv4 serwera: PASS.
Kontrola zachowania SSH/nodeAttrs: PASS.
Zapis polityki centralnej: NIE WYKONANY.
Testy uprawnień rzeczywistych po zapisie: PENDING.

Nie zmieniono konfiguracji działającej produkcji Magazynu ani usług AI Platform.

Dokumentacja Tailscale: https://tailscale.com/docs/features/sharing ; https://tailscale.com/docs/reference/syntax/grants ; https://tailscale.com/docs/reference/targets-and-selectors ; https://tailscale.com/docs/features/tailnet-policy-file/manage-tailnet-policies .
