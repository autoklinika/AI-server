# Magazyn V1 — konfiguracja Telegram DEV

**Status na 27.10.2026:** osobne środowisko i jednostka systemd przygotowane; **usługa wyłączona i nieaktywna**. Brakuje tokenu utworzonego przez użytkownika w BotFather i konta administratora w nowej pustej bazie DEV. Nie przeprowadzono jeszcze realnego testu Telegram.

## Osobny bot dedykowany Magazynowi

W Telegram otwórz [@BotFather](https://t.me/BotFather), wyślij polecenie /newbot i podaj nazwę bota oraz unikalną nazwę użytkownika kończącą się na bot. **Nie używamy tokenu Hermesa.** Nie publikuj tokenu w ChatGPT, GitHub ani dziennikach logów.

W BotFather ustaw /setjoingroups → wybierz nowego bota → **Disable**, aby nie można było zapraszać go do grup. Kod Magazynu dodatkowo ignoruje wszystkie wiadomości inne niż prywatne 1:1.

## Środowisko na harrypotter-AI-Series

- Kod: /srv/ai-data/evaluation/magazyn-v1-dev-20261026/apps/magazyn
- Osobny Python: /srv/ai-data/staging/magazyn-telegram-dev-20261027/venv
- Prywatny katalog DEV: /srv/ai-data/staging/magazyn-telegram-dev-20261027/private (0700)
- Baza: private/magazyn.sqlite3 (0600, początkowo pusta)
- Token: private/telegram.token (0600, obecnie nie istnieje)
- Jednostka użytkownika: magazyn-telegram-dev.service (zainstalowana, disabled/inactive)
- Brak tokenów współdzielonych z Hermes lub istniejącymi botami AI Platform.

## Konfiguracja — jedno polecenie w terminalu serwera

Po utworzeniu nowego bota, jako zwykły użytkownik harrypotter, **bez sudo**, uruchom w terminalu SSH:

    bash /srv/ai-data/staging/magazyn-telegram-dev-20261027/configure-telegram.sh

Skrypt:
1. Pyta o login administratora (domyślnie admin). Przy pierwszym uruchomieniu pyta dwa razy o nowe indywidualne hasło administratora (ukryte). Przy ponownym uruchomieniu prosi o hasło istniejącego administratora.
2. Pyta o token BotFather w niewidocznym polu; weryfikuje go przez Telegram API getMe i getWebhookInfo, nie przejmuje żadnego webhooka.
3. Zapisuje token w prywatnym pliku 0600, bez ujawniania w argumentach procesu, kodzie źródłowym ani logach.
4. Uruchamia tylko usługę DEV magazyn-telegram-dev.service, ale nie włącza autostartu po restarcie.
5. Po ponownym podaniu hasła administratora generuje jednorazowy kod parowania ważny 10 minut.
6. Wyślij w **prywatnej** rozmowie z nowym botem: /polacz KOD, następnie /pomoc i /stan TWOJ_NUMER.

Gdy baza nie zawiera jeszcze prawdziwych wpisów, /stan powinien zwrócić „Nie znaleziono produktu…”. Nie dodajemy danych demonstracyjnych do rzeczywistego magazynu.

### Gdy kod parowania wygaśnie

Wygeneruj nowy kod przez panel administratora albo w lokalnym terminalu:

    cd /srv/ai-data/evaluation/magazyn-v1-dev-20261026/apps/magazyn
    PYTHONPATH="$PWD" /srv/ai-data/staging/magazyn-telegram-dev-20261027/venv/bin/python -m magazyn.telegram_setup pair --db /srv/ai-data/staging/magazyn-telegram-dev-20261027/private/magazyn.sqlite3 --admin-username admin

Terminal poprosi o hasło administratora i pokaże nowy kod. Dla innego pracownika administrator może dodać opcję --user LOGIN_PRACOWNIKA po założeniu mu indywidualnego konta Magazynu.

### Status i zatrzymanie

    XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active magazyn-telegram-dev.service
    XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled magazyn-telegram-dev.service
    XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user stop magazyn-telegram-dev.service

Nie włączamy autostartu przed zaliczeniem testu prywatnych wiadomości, odmowy nieuprawnionym i prawdziwego odbioru Telegram. W razie aktywnego webhooka konfiguracja kończy się błędem bez automatycznego usuwania webhooka.

## Zabezpieczenia

- Telegram jest tylko dodatkowym kanałem **odczytu** i nie zmienia ilości produktów.
- Bez powiązania indywidualnego konta użytkownika z Telegram bot odpowiada jedynie neutralną odmową; stany pozostają ukryte.
- Powiadomienia o minimum trafiają wyłącznie do konkretnego, wskazanego użytkownika dla danego produktu, bez broadcastów i ustawień dla całej kategorii.
- Bot ma tylko połączenia wychodzące HTTPS do api.telegram.org, polling getUpdates i wysyłanie sendMessage. Nie otwieramy portu ani webhooka na serwerze.
- Treści przesyłane przez Telegram przechodzą przez serwery dostawcy i nie zapewniają lokalnej poufności end-to-end.
- Nadal potrzebne: realny test wiadomości, polityka restartów/autostartu, archiwizacja sekretów i danych oraz odbiór backupu GlobalNAS.

**Nie udostępniaj w czacie tokenu ani kodu połączenia.** Do dalszej diagnostyki wystarczą bezpieczne komunikaty TELEGRAM_BOT_VERIFIED=PASS i TELEGRAM_DEV_SERVICE=ACTIVE.
