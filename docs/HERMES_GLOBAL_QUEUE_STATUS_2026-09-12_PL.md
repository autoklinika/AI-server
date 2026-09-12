# Hermes / AI Gateway: globalna kolejka i status WAIT/START — 12.09.2026

## Status etapu

**Wynik: zakończony i zwalidowany end-to-end na rzeczywistym Serwerze AI.**

Wdrożono wspólną kolejkę zasobów dla Hermesa działającego przez Telegram i Discord oraz komunikaty użytkownika o dwóch przejściach stanu:

- `WAIT` — zapytanie faktycznie czeka na wolny zasób,
- `START` — zasób został przydzielony i rozpoczyna się przetwarzanie.

Dla Discorda komunikaty działają w dwóch kanałach jednocześnie:

- tekstowym,
- głosowym, gdy Hermes jest połączony z Discord Voice.

Końcowy test potwierdził również, że po zwolnieniu zasobu Hermes normalnie odpowiada głosem na pierwotne pytanie, a Resource Manager wraca do stanu zerowego.

Nie wykonano merge do `main`. Wszystkie zmiany tego etapu pozostają na branchu `feat/hermes-discord-queue-status` do czasu osobnej, jednoznacznej decyzji o scaleniu.

## Kontekst i cel

AI Server ma wspólny lokalny backend inferencji wykorzystywany przez różne klasy klientów. Krytyczne zadania infrastrukturalne, przede wszystkim analiza wentylacji, muszą mieć pierwszeństwo przed interaktywnymi zapytaniami użytkownika.

Aktualna polityka priorytetów użyta w tym etapie:

| Klient / klasa | Priorytet | Znaczenie |
|---|---:|---|
| wentylacja / zadanie infrastrukturalne | 10 | wyższy priorytet |
| Hermes Telegram / Discord | 50 | interaktywny użytkownik |

Mniejsza liczba oznacza wyższy priorytet. Scheduler pracuje z `max_concurrency=1`, dlatego aktywne zadanie klasy 10 może spowodować oczekiwanie Hermesa klasy 50.

Cel UX był prosty: użytkownik nie może widzieć tylko bezczynnego Hermesa. Jeżeli zapytanie naprawdę trafiło do kolejki, Hermes ma natychmiast poinformować o oczekiwaniu, a po awansie do stanu aktywnego — o rozpoczęciu pracy.

## Finalna architektura

```text
Discord / Telegram
       |
       v
     Hermes
       |
       | build_api_request()
       | AI_SERVER_GLOBAL_RESOURCE_QUEUE_V4
       v
hermes_resource_queue.py
       |
       | POST /resource/leases
       | heartbeat
       | GET lease state
       | DELETE / release
       v
AI Gateway / Resource Manager
       |
       +---- priority 10: ventilation
       |
       +---- priority 50: Hermes
       |
       v
     Ollama / Qwen
```

### Lease Hermesa

Patch `tools/patch_hermes_global_resource_queue.py` instaluje w Hermesie marker:

`AI_SERVER_GLOBAL_RESOURCE_QUEUE_V4`

Patch działa w `agent/turn_api_request.py` i dla sesji `telegram` lub `discord`:

1. pobiera platformę, chat i thread z Hermes Session ContextVars,
2. buduje target użytkownika,
3. rezerwuje zasób przez `hermes_resource_queue.py`,
4. przekazuje lease do AI Gateway przez nagłówki:
   - `X-AI-Resource-Lease`,
   - `X-AI-Resource-Lease-Release: 1`,
5. utrzymuje heartbeat lease podczas oczekiwania/pracy.

Hermes ma priorytet `50` i źródło odpowiednio `telegram-chat` lub `discord-chat`.

Mechanizm jest fail-open: awaria dodatkowego UX kolejki nie powinna unieruchomić poprawnego zapytania do AI Gateway.

### Ograniczenie komunikatów do pierwszego wywołania turnu

Komunikat WAIT/START jest użytkownikowi pokazywany tylko przy pierwszym API call danego przychodzącego turnu. Kolejne wywołania wynikające z tool-loop nadal korzystają ze wspólnego schedulera, ale nie produkują serii powtarzających się komunikatów kolejki.

## Tekstowe statusy kolejki

Helper `tools/hermes_resource_queue.py` obsługuje platformy:

- `telegram`,
- `discord`.

Status tekstowy jest wysyłany przez lokalne CLI Hermesa `hermes send --to ...`.

Finalne komunikaty:

### WAIT

`⏳ Serwer AI jest teraz zajęty. Twoje zapytanie czeka w kolejce. Powiadomię Cię, gdy rozpocznie się przetwarzanie.`

### START

`▶️ Zwolniły się zasoby. Rozpoczynam Twoje zapytanie.`

WAIT nie jest wysyłany natychmiast przy każdym requestcie. Helper czeka do rzeczywistego przekroczenia progu kolejki (`HERMES_RESOURCE_QUEUE_NOTICE_AFTER`, domyślnie około 0,75 s), żeby nie generować komunikatu dla praktycznie natychmiastowego przydziału zasobu.

Po rzeczywistym WAIT komunikat START jest wysyłany dopiero po zmianie lease na `active`.

## Discord Voice — finalna implementacja V3

Finalny patch:

`tools/patch_hermes_discord_queue_voice.py`

instaluje marker:

`AI_SERVER_DISCORD_QUEUE_VOICE_V3`

w `gateway/run_turn_runner.py`.

### Dlaczego status voice ma osobny callback

Końcowa wersja nie udaje zdarzenia `tool_start_callback` i nie wykorzystuje mechanizmu standardowego voice acknowledgement Hermesa.

Dla każdego turnu Discord patch przypina do agenta osobny callback:

`agent._ai_server_queue_voice_callback`

Globalny patch V4 pobiera ten callback i przekazuje go do `acquire_resource(..., status_callback=...)`.

Callback rozpoznaje dwa eventy:

- `queued`,
- `active`.

Następnie:

1. sprawdza, czy turn nadal jest bieżący i pochodzi z Discorda,
2. znajduje aktywne połączenie Discord Voice powiązane z bieżącym tekstowym `chat_id` przez `_voice_text_channels`,
3. potwierdza połączenie przez `adapter.is_in_voice_channel(guild_id)`,
4. generuje krótkie MP3 przy użyciu istniejącego `tools.tts_tool.text_to_speech_tool`,
5. odtwarza plik przez `adapter.play_in_voice_channel(guild_id, path)`,
6. usuwa tymczasowy plik audio.

Dzięki temu status kolejki korzysta z tej samej rzeczywistej sesji głosowej co normalna odpowiedź Hermesa i nie zależy od dodatkowego VoiceMixer.

Finalne frazy voice:

- WAIT: `Serwer AI jest zajęty. Dodałem pytanie do kolejki.`
- START: `Zwolniły się zasoby. Zaczynam.`

## Dlaczego wcześniejsze warianty nie działały

### Tekst Discord — stary helper runtime

Pierwsza implementacja patcha obsługiwała Discord, ale na serwerze pozostawała starsza kopia runtime helpera `/usr/local/libexec/ai-server/hermes_resource_queue.py`, która akceptowała wyłącznie target `telegram:`.

Objaw: scheduler działał, Discord trafiał do kolejki, ale nie pojawiał się nowy tekst WAIT.

Po instalacji aktualnego helpera z obsługą `telegram` i `discord` tekst WAIT zaczął działać.

### Discord Voice V1 — `play_ack_in_voice()`

V1 próbowało przesyłać status kolejki jako syntetyczne zdarzenie tool-start do `voice_ack_callback()` i wywoływało `play_ack_in_voice()`.

Problem: upstream Hermesa celowo robi no-op dla `play_ack_in_voice()`, gdy `discord.voice_fx.ack_enabled=false`.

Objaw: tekst WAIT działał, ale Hermes nic nie mówił.

### Discord Voice V2 — zależność od `_voice_ack_guild` / VoiceMixer

V2 ominęło `ack_enabled` i generowało TTS samodzielnie, ale nadal wybierało guild przez `_voice_ack_guild` i ścieżkę zależną od aktywnego VoiceMixer.

Na badanej konfiguracji normalny Discord Voice działał bez tego warunku. `_voice_ack_guild` nie było więc wiarygodnym wskaźnikiem rzeczywiście aktywnego połączenia głosowego.

Objaw: zwykła rozmowa voice działała, ale status kolejki nadal milczał.

### Discord Voice V3 — właściwe rozwiązanie

V3 przestało korzystać z voice ack i VoiceMixer jako kryterium routingu. Callback bezpośrednio mapuje tekstowy kanał bieżącego turnu na rzeczywiście połączony Discord Voice i używa normalnego `play_in_voice_channel()`.

To rozwiązanie przeszło rzeczywisty test WAIT -> START -> odpowiedź.

## Bezpieczny installer

Finalny installer:

`tools/install_hermes_discord_queue_voice_status.sh`

ma kilka zabezpieczeń przed uszkodzeniem działającej instalacji:

- wymaga dokładnego wspieranego checkoutu Hermes:
  `79445a496c86a19332ad786494b8384d2167e2d0`,
- sprawdza aktywność `hermes-gateway.service` i `ai-gateway.service`,
- wykonuje statyczny precheck obu patcherów,
- wymaga przed instalacją całkowicie pustego schedulera:
  - `active_count == 0`,
  - `queued_count == 0`,
  - `lease_count == 0`,
- tworzy odwracalny backup w `/srv/ai-data/hermes/discord-queue-voice-backup-v3`,
- instaluje helper i migruje wcześniejsze wersje markerów,
- sprawdza składnię zmienionych plików bez zapisu `__pycache__` w katalogach root-owned,
- weryfikuje obecność markerów V4/V3,
- restartuje tylko `hermes-gateway.service`,
- przy błędzie po mutacji wykonuje automatyczny rollback i restart Hermesa.

Restart Hermesa rozłącza istniejące połączenie Discord Voice. Po instalacji trzeba ponownie wykonać `/voice join` przed testem głosowym.

## Ważna poprawka instalatora: `py_compile` i uprawnienia

W jednej z prób installer po poprawnym patchowaniu zatrzymał się na:

`Permission denied: '/usr/local/libexec/ai-server/__pycache__'`

Przyczyną nie był kod patcha, lecz `python -m py_compile` próbujący zapisać bytecode obok root-owned helpera.

Installer został zmieniony tak, aby finalny syntax-check używał `compile(...)` w pamięci. Dzięki temu waliduje składnię bez tworzenia `__pycache__` w chronionym katalogu.

Automatyczny rollback tej nieudanej próby zadziałał prawidłowo.

## Zjawisko wiszących lease podczas diagnostyki

W trakcie iteracyjnych testów pojawiły się stare zadania Discorda z `in_use: 0`, które pozostały jako aktywne/oczekujące i blokowały kolejne zapytania.

Stan był widoczny w `GET /status` jako niezerowe `active_count`, `queued_count` i `resource_leases.lease_count` mimo braku właściwej pracy.

Do oczyszczenia środowiska testowego użyto restartu:

- `ai-gateway.service`,
- `hermes-gateway.service`.

Po restarcie potwierdzono stan `0 / 0 / 0`, a zwykły Discord Voice ponownie działał po `/voice join`.

Właśnie dlatego finalny installer wymaga pustego schedulera przed wdrożeniem.

## Walidacja końcowa 12.09.2026

Test wykonano z ręcznym lease symulującym wyższy priorytet wentylacji:

- source: `manual-ventilation-test`,
- priority: `10`,
- heartbeat co około 10 s.

Hermes Discord miał priority `50`.

### Test 1 — normalny Voice po instalacji V3

Po restarcie Hermesa ponownie wykonano `/voice join` i zadano zwykłe pytanie bez sztucznej blokady.

**Wynik: PASS.** Normalna odpowiedź głosowa działała.

### Test 2 — WAIT

Przy aktywnym lease priority 10 zadano jedno nowe pytanie głosowo na Discordzie.

Potwierdzono:

- tekstowy WAIT: **PASS**,
- głosowy WAIT: **PASS**.

Hermes wypowiedział:

`Serwer AI jest zajęty. Dodałem pytanie do kolejki.`

### Test 3 — START i właściwa odpowiedź

Ręczny lease priority 10 zwolniono przez `Ctrl+C` i `DELETE /resource/leases/...`.

Potwierdzono:

- głosowy START: **PASS**,
- dalsze przetworzenie pierwotnego pytania: **PASS**,
- normalna odpowiedź głosowa po START: **PASS**.

Hermes wypowiedział komunikat START:

`Zwolniły się zasoby. Zaczynam.`

### Test 4 — stan po zakończeniu

Końcowe `GET http://127.0.0.1:11435/status`:

```json
{
  "max_concurrency": 1,
  "max_queue_size": 128,
  "active_count": 0,
  "queued_count": 0,
  "active": [],
  "queued": [],
  "resource_leases": {
    "lease_count": 0,
    "leases": []
  }
}
```

**Wynik końcowy: PASS — scheduler wrócił do czystego stanu.**

## Pliki tego etapu

Najważniejsze elementy branchu:

- `tools/hermes_resource_queue.py` — klient Resource Managera, heartbeat, WAIT/START i status callback,
- `tools/patch_hermes_global_resource_queue.py` — Hermes global queue V4,
- `tools/patch_hermes_discord_queue_voice.py` — Discord queue voice V3,
- `tools/install_hermes_discord_queue_voice_status.sh` — bezpieczny installer/rollback,
- `tests/test_hermes_resource_queue_voice.py`,
- `tests/test_patch_hermes_global_resource_queue_v3.py` — historyczna nazwa pliku testowego; testy obejmują migrację/current patch,
- `tests/test_patch_hermes_discord_queue_voice.py`.

## Granice potwierdzenia

Potwierdzenie end-to-end obejmuje realny Discord Voice oraz kontrolowaną konkurencję z ręcznym zadaniem priority 10.

Nie należy z tego wnioskować, że wykonano długotrwały soak test przy wielu równoległych użytkownikach i wszystkich klientach AI Servera. Nie wykonano też pełnej nowej walidacji Telegrama po finalnej zmianie V4/V3 w tej samej sesji testowej — mechanizm tekstowy Telegrama był wcześniej działający, ale przed merge warto wykonać krótki test regresyjny Telegram WAIT/START.

Nie ma podstaw, aby nazywać statyczne/lokalne testy GitHub Actions CI. Dla tego branchu nie potwierdzono uruchomienia CI w GitHub Actions.

## Warunki przed merge

Przed scaleniem do `main`:

1. wykonać krótki test regresyjny Telegram WAIT -> START,
2. sprawdzić końcowy `/status` = `0 / 0 / 0`,
3. przejrzeć diff branchu względem `main`,
4. upewnić się, że dokumentacja i testy są na branchu,
5. dopiero po jednoznacznej zgodzie właściciela repo wykonać merge.

Do czasu takiej zgody `main` pozostaje produkcyjnym źródłem prawdy i nie powinien być modyfikowany przez ten etap.
