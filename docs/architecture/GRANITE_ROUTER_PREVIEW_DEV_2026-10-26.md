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
dostępny model `granite-router-v4-fix1:dev` w istniejącej Ollamie RTX.
Tag utworzono lokalnie w istniejącej RTX Ollama DEV. Produkcyjny Gateway nie został zmieniony; tag nie oznacza promocji do produkcji.
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

## Aktualizacja: Silver v4 / BF16 GGUF / rzeczywisty Gateway (26.10.2026)

- Silver v4: 152 przykładów treningowych i 50 walidacyjnych (0 prawdziwych Gold); dwie epoki na RTX 5060 Ti, 60,0 s, peak 6322 MiB.
- Z treningu wykluczono 7 błędnie lub niejednoznacznie oznaczonych przykładów telemetrii hosta/RM oraz 1 z walidacji. Nowe przykłady Silver są syntetycznymi pytaniami redakcyjnymi z konkretnymi lokalizatorami i SHA-256 rzeczywistych kontraktów WVC i Gateway; nie są rozmowami użytkowników.
- Na zamrożonych 120 AI-referencjach HF: v3 110/120, v4 113/120; telemetria v3 14/20, v4 20/20. Jednocześnie istnieją regresje w pozostałych klasach. To diagnostyka, nie niezależny benchmark jakości.
- LoRA v4 scalono z prywatną kopią bazowego checkpointu jako BF16. Pierwszy GGUF odrzucono: przy eksporcie Transformers zmienił nazwy 40 typów warstw z attention na full_attention. Lokalny konwerter nie rozpoznawał tych nazw i błędnie zadeklarował hybrid/SSM. Dla kopii wejściowej do konwersji przywrócono dokładnie nazwy oryginalnego config; binarne wagi pozostały te same.
- Poprawny oddzielny GGUF: SHA256 f46b9a62362538a6619fe5a0be2cbcacbd10b761569a0d7301ae81064fc2c8d1, rozmiar 3267401216 B, architektura granite, precyzja BF16.
- W istniejącej Ollamie RTX wybrano tag `granite-router-v4-tpl1:dev` (BF16 i zgodny z HF format wiadomości); oryginalne modele Granite, BGE-M3 oraz Qwen pozostały bez zmian. Tag DEV nie oznacza akceptacji do routingu produkcyjnego.
- Realny test HTTP uruchomiono na tymczasowym Gateway DEV (wyłącznie localhost), przez istniejący produkcyjny RM: sześć przypadków route/clarify/fallback/no_action, 6/6 oczekiwanych decyzji, brak wykonania narzędzi, poprawne zwalnianie leases i GPU. Gateway produkcyjny nie był restartowany ani przełączony na Granite.
- Własność produkcyjnego routingu nadal nie należy do Granite. PR pozostaje DRAFT i podgląd wyłączony domyślnie.
## Test zgodności GGUF vs HF — wynik i decyzja

Test wykonano na 24 z 120 zamrożonych AI-referencji (po 4 na każdą z 6 tras), nieużytych w treningu v4. Zestaw był już wcześniej wykorzystywany do diagnostyki, a etykiety nie są niezależnym Gold. Każde żądanie przeszło przez rzeczywisty HTTP Gateway DEV oraz rezerwację istniejącego Resource Managera RTX. Model nie wykonywał narzędzi.

| Wariant | Zgodność z HF v4 | Błędy schematu / fail-closed | Mediana opóźnienia | p95 |
|---|---:|---:|---:|---:|
| GGUF BF16, domyślny szablon Ollama | 17/24 | 7/24 | 3974 ms | 5741 ms |
| GGUF BF16, znaczniki ról zgodne z tokenizerem HF | 17/24 | 7/24 | 3209 ms | 3999 ms |
| GGUF FP32, znaczniki ról zgodne z tokenizerem HF | 17/24 | 7/24 | 5077 ms | 5554 ms |

W każdym wariancie ten sam rozkład względem referencji AI: graphify 4/4, knowledge_rag 4/4, reasoning 3/4, telemetry 4/4, tool 0/4, vision 2/4. W przypadku niedozwolonego/niezgodnego wyniku Gateway odmawiał routingu i narzędzi (router_invalid_output), a globalny RM przeprowadził unload i zwolnił lease. Nie stwierdzono, by wyższa precyzja FP32 rozwiązała te regresje.

**Decyzja:** zachować oszczędniejszy i szybszy model `granite-router-v4-tpl1:dev` wyłącznie do DEV; w repo flaga `router_preview_enabled=False`. Brak zgody na produkcyjne wybieranie tras, wywoływanie jakichkolwiek narzędzi i automatyczne wprowadzanie kolejnych poprawek na zamrożonym benchmarku. Dalsza poprawa wymaga niezależnych, nowych przypadków i sprawdzenia wyjść Ollama vs HF.

### Odtwarzalność i bezpieczeństwo

- Prywatne źródła, adapter i dane Silver v4: `/srv/ai-data/staging/granite-lora-dev-20261025` (bez publikacji danych do repo).
- Prywatne pochodne GGUF, logi, sumy SHA i porównania: `/srv/ai-data/staging/granite-router-gguf-dev-20261026`.
- GGUF BF16: 3 267 401 216 B, SHA256 `f46b9a62362538a6619fe5a0be2cbcacbd10b761569a0d7301ae81064fc2c8d1`. FP32: 6 530 569 504 B, SHA256 `4b1f01adf3d1757c382e67aef897f88e9830ccd3691df268fb2816b842894a78`.
- Konwersja Granite 4.0 1B wymaga w *kopii* config przywrócenia 40 nazw `layer_types=attention` (Transformers zapisuje `full_attention`) i zachowania właściwych znaczników ról `start_of_role`, `end_of_role`, `end_of_text`. Wagi oryginalne i LoRA pozostają niezmienione.
- Po serii: tymczasowy serwer HTTP DEV zatrzymany, produkcyjny `ai-gateway` działał bez restartu, globalny RM `IDLE`, 0 leases, 0 active/queued, RTX 0 resident models / 2 MiB raportowane przez NVIDIA.
- Wszystkie wyniki porównania mają status diagnostyczny. Brak formalnych, niezależnych Gold i brak pozytywnej bramki jakości produkcyjnej.
