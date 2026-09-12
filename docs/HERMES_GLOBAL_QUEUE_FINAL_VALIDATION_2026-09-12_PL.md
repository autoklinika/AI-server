# Hermes / AI Gateway — końcowa walidacja kolejki WAIT/START, 12.09.2026

## Status

**PASS — etap gotowy technicznie do merge po osobnej, jednoznacznej decyzji operatora.**

Branch: `feat/hermes-discord-queue-status`

Finalna architektura:

- global queue patch: `AI_SERVER_GLOBAL_RESOURCE_QUEUE_V4`,
- Discord Voice queue patch: `AI_SERVER_DISCORD_QUEUE_VOICE_V3`,
- Hermes interactive priority: `50`,
- wentylacja / zadania infrastrukturalne priority: `10`,
- `max_concurrency=1`.

`main` nie został zmodyfikowany ani scalony w ramach tej walidacji.

## Walidacja runtime — Discord

Potwierdzono na rzeczywistym Serwerze AI:

1. zwykła rozmowa Discord Voice bez kolejki — **PASS**,
2. tekstowy WAIT przy aktywnym lease priority 10 — **PASS**,
3. głosowy WAIT — **PASS**,
4. głosowy START po zwolnieniu lease — **PASS**,
5. właściwa odpowiedź głosowa Hermesa po START — **PASS**.

Frazy voice:

- WAIT: `Serwer AI jest zajęty. Dodałem pytanie do kolejki.`
- START: `Zwolniły się zasoby. Zaczynam.`

## Walidacja runtime — Telegram

Po finalnych zmianach V4/V3 wykonano pełny test regresyjny Telegrama:

1. zwykłe pytanie bez kolejki — **PASS**,
2. WAIT przy aktywnym lease priority 10 — **PASS**,
3. brak przedwczesnej właściwej odpowiedzi podczas WAIT — **PASS**,
4. START po zwolnieniu lease — **PASS**,
5. właściwa odpowiedź Hermesa po START — **PASS**.

Tym samym finalna wersja nie powoduje regresji Telegrama.

## Testy automatyczne

Testy wykonano w osobnym worktree:

`~/AI-server-queue-final-test`

z izolowanym venv `.venv-test` utworzonym tylko dla walidacji. Produkcyjne środowisko Python nie było modyfikowane.

Uruchomiony zestaw:

- `tests/test_gateway_scheduler.py`
- `tests/test_gateway_resource_api.py`
- `tests/test_gateway_resource_leases.py`
- `tests/test_hermes_global_resource_patch.py`
- `tests/test_hermes_resource_queue.py`
- `tests/test_hermes_resource_queue_voice.py`
- `tests/test_patch_hermes_discord_queue_voice.py`
- `tests/test_patch_hermes_global_resource_queue_v4.py`

Wynik końcowy:

```text
34 passed, 2 warnings in 0.10s
```

Dwa warningi są ostrzeżeniami deprecacyjnymi zależności testowych (`Starlette/httpx`, `anyio`) i nie dotyczą logiki kolejki ani patchy Hermesa.

### Korekta testu przed końcowym PASS

Pierwsze uruchomienie dało `33 passed, 1 failed`, ale fail nie wskazywał błędu runtime. Test `test_patcher_inserts_queue_voice_v3_path_once` wyszukiwał literal `voice_mixer_active` również w komentarzu opisującym, że V3 właśnie od niego nie zależy.

Test poprawiono tak, aby weryfikował realny kod metody, a nie tekst komentarza. Po tej korekcie cały wymagany zestaw przeszedł: `34/34 PASS`.

## GitHub Actions

Dla branchu `feat/hermes-discord-queue-status` GitHub Actions nie uruchomił workflow (`total_count=0`). Nie traktujemy więc tego jako CI PASS ani CI FAIL.

Walidacja tego etapu opiera się na:

- testach automatycznych uruchomionych lokalnie w izolowanym worktree,
- rzeczywistych testach runtime Discord i Telegram,
- końcowym stanie Resource Managera.

## Końcowy stan Resource Managera

Po testach automatycznych i runtime:

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

**PASS — brak aktywnych zadań, brak kolejki, brak wiszących lease.**

## Checklista przed merge

- [x] Discord normal Voice działa.
- [x] Discord WAIT text działa.
- [x] Discord WAIT voice działa.
- [x] Discord START voice działa.
- [x] Discord odpowiada poprawnie po START.
- [x] Telegram bez kolejki działa.
- [x] Telegram WAIT działa.
- [x] Telegram START działa.
- [x] Telegram odpowiada poprawnie po START.
- [x] Scheduler / Resource Manager / leases przeszły testy automatyczne.
- [x] Helper i patchery V4/V3 przeszły testy automatyczne.
- [x] `34/34` wymaganych testów automatycznych PASS.
- [x] Końcowy Resource Manager `0/0/0`.
- [x] Dokumentacja etapu istnieje.
- [ ] Merge do `main` — wymaga osobnej, jednoznacznej zgody operatora.
