# Magazyn V1 — naprawa logowania WebGUI DEV (27.10.2026)

**Wynik:** konfiguracja naprawiona, obie usługi aktywne; bez wdrożenia produkcyjnego.

## Przyczyna

WebGUI nasłuchujące na 127.0.0.1:18765 uruchomiono wcześniej na odrębnej bazie podglądowej:
`/srv/ai-data/evaluation/magazyn-webgui-preview-20261027/webgui_preview.sqlite3`.

Baza podglądowa zawierała dwa konta i sześć produktów demonstracyjnych. Zmieniony wcześniej login administratora i powiązanie Telegram należały natomiast do właściwej bazy Magazynu DEV:
`/srv/ai-data/staging/magazyn-telegram-dev-20261027/private/magazyn.sqlite3`.

W obu bazach użytkownicy nie byli ci sami, zatem poprawne po zmianie loginu dane uwierzytelniające Magazynu nie działały w WebGUI podglądowym. **Nie była to awaria hasła ani Telegrama.**

## Naprawa i izolacja

1. Zachowano odrębną bazę podglądową wraz z przykładami bez kopiowania jej zawartości do właściwego Magazynu.
2. Zatrzymano tylko błędnie skonfigurowany, jednorazowy proces WebGUI na porcie 18765.
3. Utworzono jednostkę systemd użytkownika `magazyn-webgui-dev.service` (nie systemową), która:
   - działa pod użytkownikiem `harrypotter`;
   - wskazuje `MAGAZYN_DB_PATH` na tę samą bazę DEV, z której korzysta dedykowany bot Telegram;
   - nasłuchuje wyłącznie na `127.0.0.1:18765`;
   - ustawia `MAGAZYN_COOKIE_SECURE=0` **wyłącznie dla HTTP na loopback przez tunel SSH DEV**, nie dla publicznego LAN;
   - ma ograniczenia `NoNewPrivileges=yes`, `PrivateTmp=yes`, `UMask=0077`, `MemoryMax=384M`;
   - **nie jest enabled** na restart hosta, pozostaje usługą tymczasową DEV.
4. Uruchomiono tę usługę; nie restartowano ani nie modyfikowano Hermesa, RM czy Telegrama.

## Weryfikacja

- `magazyn-webgui-dev.service`: `active/running`, zero restartów.
- `magazyn-telegram-dev.service`: `active/running`, zero restartów.
- Weryfikacja procesu potwierdziła wskazanie tej samej właściwej bazy przez WebGUI i bota Telegram.
- `GET http://127.0.0.1:18765/`: HTTP 200.
- `GET http://127.0.0.1:18765/healthz`: HTTP 200.
- `GET http://127.0.0.1:18765/api/auth/me` bez sesji: HTTP 401 (prawidłowa odmowa).
- Wspólna baza DEV: **jeden aktywny administrator**, **jedno aktywne, zweryfikowane powiązanie Telegram** i magazyn początkowo **0 produktów / 0 sztuk / 0 lokalizacji**.
- Hasła, tokeny botów, sesje, produkty demonstracyjne nie zostały przeniesione, wyświetlone ani zapisane do GitHub.

Nie wykonywano prób logowania z rzeczywistym hasłem użytkownika; do końcowego potwierdzenia należy zalogować się **nowym loginem administratora i dotychczasowym hasłem**.

## Dostęp do podglądu

Na komputerze Windows tunel SSH (w osobnym terminalu):

    ssh -L 18765:127.0.0.1:18765 harrypotter@192.168.1.55

W przeglądarce: `http://127.0.0.1:18765/`. W razie zachowanego nieaktualnego ciasteczka sesji wykonać twarde odświeżenie lub otworzyć okno prywatne.

## Diagnostyka usługi (na serwerze bez sudo)

    XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user status magazyn-webgui-dev.service

Nie uruchamiać ponownie starego procesu WebGUI z bazą podglądową na tym samym porcie. Nie kopiować przykładów do właściwego Magazynu. Produkcja i gałąź GitHub `main` pozostają niezmienione.
