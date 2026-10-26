# Magazyn V1 — Telegram i Discord (DEV)

**Status: warstwa oprogramowania, bez aktywowanych botów.** Mechanizmy zostały zaprojektowane jako osobne, włączane świadomie procesy wyłącznie z połączeniami wychodzącymi. Nie korzystają z konfiguracji Hermesa, nie modyfikują AI Platform i nie wymagają GPU, Ollamy ani modelu AI.

## Funkcje

- Pytania prywatne o stany produktów, np. `/stan 0281016738`, `/szukaj IRF3205`, `ile mam EDC7?`. Nazwa, numer i kilka lokalizacji podawane są w odpowiedzi, maksymalnie 5 pozycji. W przypadku wielu trafień bot prosi o doprecyzowanie.
- Boty obsługują **wyłącznie odczyt**; nie da się przez nie dodawać, wydawać, edytować ani usuwać produktów.
- Zapytania i kody powiązania konta są przyjmowane **wyłącznie w prywatnym czacie jeden do jednego**. Grupy Telegrama, kanały serwerowe Discorda, grupowe DM, boty nadawców oraz inne zdarzenia są ignorowane bez odpowiedzi.
- Konta są przypisywane do konkretnego użytkownika Magazynu, sprawdzane jest także `active=1` w bazie. Inne osoby widzą tylko neutralną odmowę.
- Alert o niskim stanie przypisywany jest **wyłącznie do jednego, wskazanego użytkownika dla jednego produktu** i jednego wybranego komunikatora. Brak dziedziczenia kategorii i żadnego broadcastu.
- Alert po zejściu do minimum trafia do trwałej kolejki SQLite w tej samej transakcji co zmiana stanu; wysyłka jest poza transakcją. Dalsze wydania nie generują kolejnych alertów. Dopiero powrót ponad minimum i kolejny spadek uzbraja następny alert.
- Błąd wysyłki skutkuje ponowieniem z rosnącą przerwą. Anulowanie konfiguracji, odłączenie konta, dezaktywacja pracownika lub uzupełnienie zapasu może anulować oczekujące wysyłki. Mechanizm ma charakter **at-least-once**; wyjątkowo po awarii między wysłaniem a zapisem potwierdzenia dostarczenia może zdarzyć się powtórka.
- Uprawnienia odbiorcy są sprawdzane podczas pobierania alertu oraz ponownie tuż przed wysyłką (dla Discorda również po operacji sieciowej `fetch_user`). **Wiadomości, których wysyłkę do dostawcy już rozpoczęto, nie można wycofać po późniejszej dezaktywacji użytkownika.** Administrator powinien wiedzieć o niewielkim oknie nieodwracalnych operacji „w locie”. Nie blokujemy operacji magazynowych na czas komunikacji z zewnętrznym dostawcą.

## Powiązanie użytkownika przez administratora

1. Administrator loguje się do WebGUI i otwiera **Administracja → Telegram i Discord**.
2. Wybiera istniejącego, aktywnego użytkownika i komunikator. Kliknięcie „Utwórz kod połączenia” generuje jednorazowy losowy kod ważny 10 minut.
3. Kod przekazuje bezpiecznym kanałem właściwemu użytkownikowi (nie publikować go w grupach ani na kanałach).
4. Użytkownik wysyła **prywatną** wiadomość do dedykowanego bota Magazynu: `/polacz KOD`.
5. Po potwierdzeniu konto Telegram/Discord jest powiązane. Administrator może je odłączyć w WebGUI; nowe powiązanie wymaga nowego kodu.
6. Administrator otwiera pozycję magazynową i ustawia minimum, odbiorcę oraz Telegram **albo** Discord. Jeśli użytkownik nie ma zweryfikowanego konta, wpis pozostanie na liście „Do zamówienia”, ale nie będzie wiadomości.

Hasz kodu zapisany jest w bazie; jawny kod zwracamy w panelu administratora tylko podczas generowania. Kod nie uprawnia do innego konta ani innego komunikatora. Zmiana użytkownika w WebGUI nie nadaje dodatkowych praw botowi.

## Uruchomienie tylko po osobnym odbiorze DEV

Boty są domyślnie wyłączone. Zmienne i komendy (przykład koncepcyjny, nie oznacza skonfigurowania prawdziwych tokenów):

    export MAGAZYN_DB_PATH="/PRIVATE/DATA/magazyn.sqlite3"
    export MAGAZYN_BOTS_ENABLED=1
    export MAGAZYN_TELEGRAM_BOT_TOKEN="TOKEN_Z_OSOBNEGO_BOTA"
    python -m magazyn.bots telegram --db "$MAGAZYN_DB_PATH"

Dla Discorda należy zastosować **inny token bota** w `MAGAZYN_DISCORD_BOT_TOKEN` i osobny proces:

    python -m magazyn.bots discord --db "$MAGAZYN_DB_PATH"

Pakiety klienta komunikatora są opcjonalne, wskazane w `requirements-bots.txt`. Tokenów nie umieszcza się w GitHub, logach, argumentach procesów ani wiadomościach. Przed produkcją umieścić je w odpowiednio chronionym środowisku usługi. Nie wykorzystywać tokenów Hermesa.

### Transport

- Telegram: `https://api.telegram.org` i `getUpdates` przez HTTPS/polling, `sendMessage` tylko do identyfikatora prywatnego konta powiązanego w bazie. Polling nie działa równolegle z aktywnym webhookiem **tego samego bota**. Nie usuwamy istniejących webhooków i nie zmieniamy botów Hermesa.
- Discord: biblioteka `discord.py` i połączenie wychodzące Gateway, obsługa wyłącznie `DMChannel` (nie `GroupChannel`, nie serwery). Wysyłka z `allowed_mentions=none` wyklucza pingowanie innych użytkowników.
- Zawartość zapytań i odpowiedzi przechodzi przez serwery Telegrama lub Discorda. Nie stanowi to szyfrowania end-to-end lokalnej bazy; przeznaczenie komunikatorów powinno uwzględniać ten kompromis poufności.

### Braki operacyjne

- Nie ma jeszcze prawdziwych, zatwierdzonych kont botów Magazynu ani ich tokenów.
- Nie utworzono usług systemd, harmonogramów, otwartego portu czy webhooka.
- Nie przeprowadzono testu prawdziwej wysyłki i odbioru przez Telegram/Discord ani odbioru bezpieczeństwa kont.
- Przed uruchomieniem trzeba przetestować zawieszenie/odnowienie sesji, utratę połączenia, uprawnienia konta bota, logi, limit zapytań i instrukcję odwołania dostępu.

## Testy

`tests/test_messaging.py` testuje pełną logikę z syntetycznymi użytkownikami, stany, autoryzację, wymuszenie prywatnych DM, deduplikację, retries, odłączenie konta oraz migrację schematu SQLite v1→v2. Transporty są testowane przez funkcje/adapters i zastępczego nadawcę; bez prawdziwej sieci.

**Nie wdrażać do produkcji i nie udostępniać zdalnie API Magazynu przed zakończeniem odbioru bezpieczeństwa.**
