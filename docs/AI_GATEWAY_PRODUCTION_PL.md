# AI Gateway — stan produkcyjny

Data zamknięcia etapu: 2026-09-03

## Cel

AI Gateway jest lokalną warstwą admission/scheduling pomiędzy klientami AI a Ollamą. Nie wykonuje inferencji samodzielnie. Jego zadaniem jest kolejkowanie żądań i nadawanie priorytetów tak, aby analiza wentylacji miała pierwszeństwo przed interaktywnymi i tłem.

## Produkcyjna architektura

- Ollama: `127.0.0.1:11434`
- AI Gateway: `127.0.0.1:11435`
- Gateway max concurrency: `1`
- Gateway queue size: `128`
- Ventilation namespace: `http://127.0.0.1:11435/clients/ventilation`
- Hermes namespace: `http://127.0.0.1:11435/clients/hermes/v1`

Priorytety:

- ventilation: `10`
- interactive / Hermes: `50`
- normal: `100`
- background: `200`

Niższa wartość oznacza wyższy priorytet. Scheduler jest niepreempcjny: aktywnej inferencji nie przerywa, ale wybiera następne oczekujące zadanie według priorytetu, a przy tym samym priorytecie FIFO.

## Produkcyjny Hermes

Instalacja Hermesa pozostaje poza tym repozytorium pod:

`/srv/ai-data/hermes/hermes-agent`

Zweryfikowana wersja podczas wdrożenia:

- Hermes `0.21.0`
- commit Hermesa `254158f4530cada634c4ef8f4cff93257c5b4f77`
- model `qwen3.6:35b-hermes64k`

Produkcja używa:

- provider: `custom`
- base URL: `http://127.0.0.1:11435/clients/hermes/v1`
- `agent.reasoning_effort: 'none'` jako literalny string YAML
- Telegram toolsets: `[terminal, file, web]`

Model-facing Telegram tools po runtime gating:

- `terminal`
- `process_manage`
- `read_file`
- `write_file`
- `patch`
- `search_files`
- `web_search`
- `web_extract`

Hermes może wewnętrznie rozwiązać niekonfigurowalny toolset `kanban`; jego narzędzia są blokowane przez runtime `check_fn` i nie są wystawiane zwykłej sesji Telegram.

## Zweryfikowane wyniki na realnym serwerze

- Gateway health: PASS
- real Qwen inference przez Gateway: PASS
- ventilation przez namespace z priorytetem 10: PASS
- Hermes przez namespace z priorytetem 50: PASS
- kolejność przy kontencji: aktywne Hermes -> oczekująca ventilation 10 -> oczekujące Hermes 50: PASS
- Telegram po optymalizacji bez narzędzia: około 2 s do odpowiedzi
- Telegram z prawdziwym odczytowym użyciem terminala (`hostname`): około 4 s
- wynik `hostname`: `harrypotter-AI-Series`

## Dlaczego Telegram ma statyczny profil narzędzi

Pełny domyślny zestaw Hermesa powodował bardzo duży stały narzut promptu i tool schemas. Benchmark realnego serwera pokazał około 43 s dla banalnej odpowiedzi przy pełnym zestawie. Progressive disclosure zostało zbadane, ale pełne E2E nie było wystarczająco niezawodne do produkcji. Produkcyjna decyzja to prosty statyczny profil `terminal + file + web`.

Eksperymentalne benchmarki i diagnostyka progressive disclosure nie są częścią wydania produkcyjnego.

## Kolejność wdrożenia od zera

1. Zainstaluj Gateway:

```bash
tools/install_ai_gateway_stage1.sh
```

2. Przełącz tylko analizę wentylacji na namespace Gatewaya:

```bash
tools/cutover_ventilation_to_ai_gateway_stage2.sh
```

3. Audytuj Hermes przed zmianą routingu:

```bash
tools/audit_hermes_runtime_stage3.sh
```

4. Przełącz Hermes na namespace Gatewaya:

```bash
tools/cutover_hermes_to_ai_gateway_stage3.sh
```

5. Ustaw Hermes reasoning off poprawnym literalnym stringiem `none`:

```bash
tools/configure_hermes_reasoning_none.sh
```

6. Ustaw produkcyjny profil Telegram:

```bash
tools/cutover_hermes_telegram_static_profile_stage22.sh
```

7. Wykonaj smoke test Gatewaya i opcjonalny test priorytetu:

```bash
tools/validate_ai_gateway_real_server.sh
tools/validate_ai_gateway_priority_stage4.sh
```

## Rollback

Rollback wentylacji:

```bash
tools/rollback_ventilation_ai_gateway_stage2.sh
```

Rollback routingu Hermesa:

```bash
tools/rollback_hermes_ai_gateway_stage3.sh
```

Rollback reasoning:

```bash
tools/rollback_hermes_reasoning_none_stage9.sh
```

Rollback profilu Telegram:

```bash
tools/rollback_hermes_telegram_static_profile_stage22.sh
```

Backupi utworzone i zachowane na realnym serwerze podczas wdrożenia obejmują m.in.:

- `/srv/ai-data/hermes/config.yaml.pre-ai-gateway-stage3`
- `/srv/ai-data/hermes/config.yaml.pre-reasoning-none-stage9`
- `/srv/ai-data/hermes/config.yaml.pre-telegram-static-stage22`

## Ważne ograniczenia

- Gateway v1 nie przerywa już aktywnej inferencji.
- Jedna aktywna inferencja zajmuje slot aż do końca streamu.
- `qwen35moe` w używanej wersji Ollamy pracuje jako pojedynczy runner z `-np 1`; nie wymuszamy `-np 2`.
- Dwa pełne runnery Qwen 35B nie są wdrażane; realny benchmark dał zbyt mały zysk względem kosztu zasobów.
- Gateway zarządza wyłącznie ruchem do Ollamy. Przyszły niezależny generator obrazów/GPU wymaga osobnej warstwy Resource Managera.
- AI nie steruje wentylacją. Serwer AI analizuje i rekomenduje; sterowanie oraz logika bezpieczeństwa pozostają po stronie CM5.

## Źródło prawdy

Po zamknięciu PR wdrożenie produkcyjne jest reprezentowane przez `main` repozytorium `autoklinika/AI-server`. Rozwój kolejnych funkcji ponownie odbywa się na osobnych gałęziach zgodnie z zasadą, że `main` pozostaje działającym źródłem produkcyjnym.
