# AI Platform — Granite jako wymienialny router decyzyjny (DEV, 2026-10-26)

## Decyzja architektoniczna

Granite ma działać **przed wyborem właściwej ścieżki przetwarzania**, a nie zastępować Qwena.
Integrujemy go przez istniejący Gateway i jego **pojedynczy Resource Manager**.
Nie dodajemy usług systemd, drugiej kolejki GPU ani osobnego koordynatora.

Nowy kod jest na gałęzi funkcjonalnej, **nie w wydaniu produkcyjnym**.
Domyślnie `AI_BRIDGE_ROUTER_PREVIEW_ENABLED=false`. Kod nie zmienia /api/chat,
Hermes, WVC, Knowledge Service, ComfyUI, Qwen, istniejących modeli czy klientów.

Proponowany przyszły przepływ:
`klient -> Gateway -> (Granite: decyzja) -> zatwierdzona polityka -> istniejące Knowledge/RAG/telemetry/vision/reasoning/tool`.
**Model klasyfikuje, ale nie autoryzuje i nie wykonuje narzędzi.**

## Kontrakt i API

- Opcjonalne `POST /api/v1/router/preview` z `{"schema_version":1,"text":"..."}`.
- Odpowiedź to `decision` z polami `decision,route,selected_tools,required_capability`.
- `decision=route`: sześć historycznych tras i dokładnie dozwolony zestaw narzędzi.
- `decision=clarify`: brak kluczowego kontekstu; żadnych narzędzi.
- `decision=fallback`: brak wymaganej funkcjonalności w sześciu trasach
  (np. `github.write`, `host.inspect`, `web.search`); żadnych narzędzi.
- `decision=no_action`: zakończenie wątku lub brak zadania; żadnych narzędzi.
- Dozwolone `selected_tools`: jedynie pięć narzędzi istniejących w routerze,
  i tylko mapowanie związane z właściwą trasą. `agent.ers` nie obsługuje
  operacji GitHub lub administracji hostem.
- Niezgodny JSON, próba podstawienia narzędzia lub brak poprawnej trasy:
  **odrzucenie modelowej decyzji**, bez uruchamiania żadnego narzędzia.
- Żadne teksty zapytań nie trafiają do logów nowego backendu.
  Podgląd korzysta z tej samej autoryzacji Platform API.

Przełączenie flagi nie jest wystarczające do użycia GPU: potrzebny jest
dostępny model `granite-router-v3:dev` w istniejącej Ollamie RTX.
Tego tagu **nie utworzono w tej zmianie** — eksport i uruchomienie wyłącznie po odbiorze.
Włączenie podglądu bez tagu zgłasza błąd i nie uruchamia Qwena zastępczo.

## GPU / RM / bezpieczeństwo

Backend pobiera tylko **jeden** background ticket od istniejącego RM, wyłącznie
przy pustej kolejce i `gpu_residency=llm`. RTX Ollama jest tylko na
`127.0.0.1:11436`; nazwa modelu pochodzi z ustawień serwera, nie od klienta.

Każde wywołanie podejmuje próbę wyładowania swojego modelu `keep_alive=0`,
weryfikuje `/api/ps`, dopiero potem zwalnia admission. Brak dowodu cleanup
blokuje RM do rozpoznania przez operatora zamiast uznać GPU za bezpieczne.
Brak samodzielnego modelowego tool-call, rejestratora promptów i szeregowania poza RM.
Utrata połączenia z klientem nie może oznaczać milczącego potwierdzenia cleanup.

## Dane i pomiar (prywatne DEV, nie publikować zbiorów)

Istniejące, nietknięte materiały:
- Silver v2: 65 train / 19 val; adapter v2 jest zachowany.
- Zamrożone 120 AI-referencji: nigdy nie są danymi treningowymi.
- Pochodzące z rozmów 68 cytatów: nie użyte w treningu v3.

Nowy prywatny Silver v3:
- 105 train = 65 dotychczasowych + 40 ręcznie przygotowanych scenariuszy
  `clarify/fallback/no_action`; 35 val = 19 dotychczasowych + 16 nowych.
- 20 odrębnych grup źródeł w łącznym zbiorze, ale wiele grup treningowych
  pochodzi z dokumentów technicznych, a nowe scenariusze są syntetyczne.
- 2 epoki LoRA rank 8, BF16, RTX 5060 Ti, 42,1 s, maksimum 6370 MiB reserved VRAM.
- Adapter: prywatny `/srv/ai-data/staging/granite-lora-dev-20261025/outputs/silver-pilot-v3-r1`.
- 0 niezależnych ludzkich etykiet Gold; nie nazywać poniższych metryk accuracy na żywych klientach.

Wynik diagnostyczny `V3_DIAGNOSTIC_RESULTS_155.jsonl`:
- V3 val: **33/35** zgodności ze słabymi etykietami; 35/35 poprawnych struktur.
- Zamrożony test 120: **110/120** zgodności z referencjami AI; 119/120
  poprawnych struktur. Główne słabości: telemetry 14/20, knowledge 18/20,
  vision 18/20.
- Historyczny v2 na tym samym zestawie: 113/120. **Nie ogłaszać poprawy v3**;
  prompt i schemat różnią się, a test miał już wcześniejsze użycia.
- Po ewaluacji RM IDLE, 0 leases, RTX bez rezydentów.

## Bramka publikacji / następny etap

1. Kontrakt + wyłączony domyślnie endpoint mają mieć testy bezpieczeństwa i
   regresji. Kod wejściowo wyłącznie jako PR — bez restartu Gateway.
2. Poprawić kluczowe regresje (zwłaszcza telemetria) na niezależnie
   uzgodnionych danych, nie dokładając Gold/frozen holdout do treningu.
3. Utrzymywać LoRA jako odrębny adapter. Przygotować *kopię eksportową*
   modelu do osobnego GGUF (Ollama 0.40.7 nie przyjmuje nowego `ADAPTER`
   przez `ollama create`), ale nie nadpisywać oryginalnego modelu.
4. Po pozytywnym teście GGUF/HF, polityk, PL/EN, p95 oraz GPU/RM można
   świadomie włączyć **podgląd** — wciąż bez decydowania o żywej trasie.
5. Dopiero niezależny odbiór Gold i brak krytycznych regresji mogą być
   podstawą do osobnej decyzji o produkcyjnym cutover.

**Werdykt: integracja kodowa DEV / GPU eksperymentalny PASS; v3 NIE zaakceptowany
do routingowego cutover, brak zmian w produkcji.**
