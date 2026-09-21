# AI Platform — Component Contracts v1

**Status:** TARGET CONTRACTS v1  
**Data:** 2026-09-19  
**Powiązany dokument:** `AI_PLATFORM_TARGET_ARCHITECTURE_V1_PL.md`

## 1. Cel

Ten dokument definiuje stabilne granice pomiędzy klientami, domenami i wymiennymi komponentami AI Platform.

Kontrakty opisują **co komponent robi**, a nie **jakim produktem jest zaimplementowany**.

---

## 2. Zasady kontraktów

1. Kontrakty platformowe są wersjonowane.
2. Produkt/provider nie może przeciekać do API domenowego bez potrzeby.
3. Każdy request posiada correlation/request ID.
4. Każdy request posiada jawny `domain` albo `shared`.
5. Backend może się zmienić bez zmiany klienta.
6. Błędy są normalizowane.
7. Streaming jest właściwością kontraktu, nie konkretnego providera.
8. Kontrakty nie zawierają sekretów.
9. Dane provider-specific mogą występować tylko w kontrolowanym `provider_metadata`.
10. Breaking change wymaga nowej wersji kontraktu.

---

## 3. Context Envelope

Wspólny kontekst przekazywany pomiędzy GUI, domeną, Agent Service i Knowledge Service.

```json
{
  "request_id": "req_...",
  "domain": "ecu-repair",
  "actor_id": "user-or-service-ref",
  "session_id": "optional",
  "case_id": "CASE-000184",
  "current_view": "measurements",
  "time_range": null,
  "metadata": {}
}
```

Pola domenowe są opcjonalne, ale `domain` i `request_id` są obowiązkowe.

Agent nie powinien zgadywać `case_id`, `current_view` ani innego stanu klienta.

---

## 4. Capability Request

Klient prosi o zdolność, nie o nazwę modelu.

```json
{
  "capability": "reasoning",
  "priority_class": "interactive",
  "context": {
    "request_id": "req_...",
    "domain": "ecu-repair"
  },
  "requirements": {
    "tools": true,
    "vision": false,
    "structured_output": true,
    "max_latency_ms": null
  }
}
```

Przykładowe capabilities v1:

- `reasoning`
- `chat`
- `structured-generation`
- `embeddings`
- `rerank`
- `vision`
- `image-generation`
- `image-edit`
- `video-generation`
- `speech-to-text`
- `text-to-speech`

Lista może rosnąć bez zmiany domen.

---

## 5. LLMProvider

Minimalny logiczny interfejs:

```text
generate(request) -> LLMResponse
stream(request)   -> stream<LLMChunk>
health()          -> ProviderHealth
describe()        -> ProviderDescriptor
```

### LLMRequest

```json
{
  "request_id": "req_...",
  "capability": "reasoning",
  "messages": [],
  "tools": [],
  "response_schema": null,
  "temperature": 0,
  "context": {},
  "provider_hint": null,
  "model_hint": null
}
```

`provider_hint` i `model_hint` są przeznaczone dla diagnostyki/administracji. Normalna domena nie powinna ich ustawiać.

### LLMResponse

```json
{
  "request_id": "req_...",
  "content": "...",
  "tool_calls": [],
  "finish_reason": "stop",
  "usage": {
    "input_tokens": null,
    "output_tokens": null
  },
  "execution": {
    "provider": "ollama-local",
    "model": "qwen3.6:35b-hermes64k-gpu",
    "node": "ai-node-01",
    "queue_wait_ms": 0,
    "duration_ms": 0
  },
  "provider_metadata": {}
}
```

---

## 6. AgentProvider

AgentProvider nie jest Platform API. Jest wymiennym wykonawcą logiki agentowej.

Minimalny kontrakt:

```text
run_turn(AgentTurnRequest) -> AgentTurnResult
stream_turn(...)           -> stream<AgentEvent>
health()
describe()
```

### AgentTurnRequest

```json
{
  "request_id": "req_...",
  "session_id": "session_...",
  "message": "...",
  "context": {},
  "allowed_toolsets": ["files", "web", "domain"],
  "capability": "reasoning"
}
```

### Agent events

Standaryzowane zdarzenia:

```text
queued
started
token/chunk
tool_started
tool_finished
artifact_created
completed
failed
cancelled
```

Telegram, Discord i GUI mogą dzięki temu prezentować kolejkę niezależnie od Hermesa.

---

## 7. Resource Manager

### 7.1. Semantic priority contract — Stage D.1

Opcjonalne top-level pole JSON `priority_class` jest obsługiwane przez wszystkie
istniejące scheduled POST endpointy Gateway: `/api/chat`, `/api/generate`,
`/api/embed`, `/api/embeddings`, `/v1/chat/completions`, `/v1/embeddings` oraz ich
istniejące warianty `/clients/ventilation/...` i `/clients/hermes/...`.
Obsługuje je także `POST /resource/leases`. Nie powstaje nowy publiczny nagłówek.

| Klasa kanoniczna | Wewnętrzny priorytet D.1 |
|---|---:|
| `infrastructure` | 10 |
| `interactive-high` | 25 |
| `interactive` | 50 |
| `normal` | 100 |
| `background` | 200 |
| `maintenance` | 300 |

`critical` jest wyłącznie compatibility alias dla `infrastructure`, bez osobnego
poziomu. Nazwy są case-sensitive i bez normalizacji whitespace. Nieznana nazwa,
pusta nazwa, `null` lub typ inny niż string daje HTTP 400
`{"detail":"invalid priority_class"}` przed admission/upstream, także gdy podano
legacy numeric override. Błąd nie powtarza wartości wejściowej.

Precedence po walidacji klasy:

1. Scheduled HTTP: jawny `X-AI-Priority`, następnie klasa, następnie dotychczasowy
   default endpointu z Settings.
2. Tworzenie lease: jawne legacy JSON `priority`, następnie klasa, następnie
   dotychczasowy `gateway_priority_interactive`. Nagłówek `X-AI-Priority` nie
   sterował tworzeniem lease i nadal nim nie steruje.
3. Użycie aktywnego lease: ticket lease zachowuje swój priorytet; priority requestu
   nie zmienia ani nie rezerwuje ponownie slotu. Walidacja requestu nadal obowiązuje.

Legacy liczby zachowują dotychczasowe parsowanie i zakres -1000..1000, bez
zaokrąglania do klasy. `infrastructure` jest najwyższą **klasą**, ale legacy
liczby poniżej 10 nadal mają wyższy efektywny priorytet. Wartości 10/50/100/200
nie zmieniają zachowania. Klasy mapują się na stałe liczby z tabeli; istniejące
Settings/env priority nadal konfigurują legacy defaulty endpointów, nie tabelę
klas. WVC pozostaje na istniejącej trasie z defaultem 10 i zachowuje override'y.

Gateway usuwa `priority_class` przed wysłaniem JSON do providera (również dla
streamingu i użycia lease). Request bez tego pola jest przesyłany byte-for-byte
jak wcześniej; malformed/non-object JSON pozostaje obsługiwany jak dotychczas.
Status i nagłówki diagnostyczne nadal pokazują efektywną liczbę; D.1 nie dodaje
prompt content ani nowego JobState. Niższa liczba wygrywa, FIFO obowiązuje przy
równych liczbach, także pomiędzy klasą i legacy requestem. Brak preemption.

Przykładowe body dla `/api/chat`:

```json
{"model":"qwen3.6:35b","messages":[],"stream":false,"priority_class":"interactive"}
```

JobRequest pozostaje kontraktem docelowego admission API. D.2 implementuje
metadata-only JobState opisany w §7.2, bez nowego Platform API.

### JobRequest

```json
{
  "request_id": "req_...",
  "domain": "ecu-repair",
  "capability": "reasoning",
  "priority_class": "interactive",
  "resource_requirements": {
    "gpu": "preferred",
    "vram_mb": null,
    "ram_mb": null
  },
  "timeout_seconds": 300,
  "preemptible": false
}
```

### JobState

Dozwolone stany:

```text
submitted
queued
admitted
running
completed
failed
cancelled
expired
```

### Job status

```json
{
  "job_id": "job_...",
  "request_id": "req_...",
  "state": "queued",
  "priority_class": "interactive",
  "queue_position": 2,
  "assigned_node": null,
  "assigned_provider": null,
  "created_at": "...",
  "started_at": null,
  "finished_at": null
}
```

Resource Manager nie musi znać treści promptu.

### 7.2. Job model — Stage D.2

Status: **READY FOR SUPERVISOR VALIDATION** — implementacja lokalna, bez walidacji
produkcyjnej. JobState jest niemutowalnym rekordem metadanych. Zawiera wyłącznie:
`job_id`, `request_id`, `domain`, `capability`, `priority_class`, `state`,
`assigned_provider`, `assigned_node`, `created_at`, `queued_at`, `admitted_at`,
`started_at`, `finished_at`. Nie przechowuje source, body, promptów, messages,
modelu, wyników, wyjątków ani dowolnego słownika metadata.

- `job_id=job_<UUID4 hex>` jest unikalny niezależnie od restartu/procesu;
  `request_id=req_<UUID4 hex>` jest generowany na granicy schedulera/adaptera.
  Zaufany wewnętrzny `JobMetadata` pozwala późniejszemu Platform API przekazać
  wspólny request_id do kilku jobów. To korelacja, nie idempotency key.
- D.2 nie interpretuje klientowskich pól `request_id`, `domain`, `capability`
  ani nagłówków korelacyjnych jako nowego envelope. Legacy body pozostaje
  niezmienione poza już konsumowanym D.1 `priority_class`.
- Domain: `wvc` dla compatibility route ventilation, `shared` dla pozostałych.
  Capability pochodzi z trasy: `reasoning` (WVC), `chat`, `text-generation`
  (`/api/generate`), `embeddings` (istniejące trasy embedding).
  Scheduler bez metadanych używa `shared` / `unknown`.
- `priority_class` zachowuje jawną kanoniczną klasę D.1, nawet przy numeric
  override. Gdy jej brak, dokładne dopasowanie liczby do tabeli D.1 daje klasę;
  pozostałe legacy liczby dają `null` (bez zgadywania/zaokrąglania).
  Efektywne `priority` pozostaje w legacy status i steruje ordering/FIFO.
- Assignment jest `null` w kolejce. HTTP po rozpoczęciu wykonania zapisuje
  istniejący stały upstream `ollama-local` i `Settings.node_id`.
  To opis aktualnego proxy, nie registry, discovery ani wybór providera.
  D.3 zachowuje te wartości, pobierając je z walidowanego registry (§8.1).

Jawne przejścia:

| Stan | Dozwolone następne stany |
|---|---|
| submitted | queued, failed, cancelled |
| queued | admitted, cancelled, expired |
| admitted | running, completed, failed, cancelled, expired |
| running | completed, failed, cancelled, expired |
| completed / failed / cancelled / expired | brak |

`submitted` i `queued` mogą być krótkotrwałe przy wolnym slocie. `admitted`
oznacza przydział slotu; `running` rozpoczęcie lokalnego wykonania HTTP.
Sukces HTTP kończy się `completed`, HTTP 4xx/5xx i wyjątki `failed`, przerwanie
requestu `cancelled`. Queue full zapisuje `submitted -> failed`; odrzucone
przed admission niepoprawne requesty nie tworzą joba. Streaming utrzymuje slot
oraz stan running do zakończenia/awarii streamu, również błędu close.

External lease opisuje **rezerwację**, capability `external-reservation`.
Pozostaje `admitted` podczas użycia przez worker, z assignment i started_at
równymi null: Gateway nie zna wykonania zewnętrznego ComfyUI. Zwolnienie aktywnej
rezerwacji oznacza `completed`, zwolnienie queued `cancelled`, idle TTL `expired`.
`completed` nie potwierdza sukcesu pracy zewnętrznego providera. Współdzielone
HTTP pod lease zachowuje ID/klasę rezerwacji, nie tworzy drugiego joba ani nie
zmienia jej stanu na podstawie wyniku Qwen. `in_use`, heartbeat i release-after-use
zachowują semantykę. Unified execution/admission pozostaje D.4.

Czasy to UTC ISO-8601 z offsetem, null przed osiągnięciem etapu. Nie cofają się
przy korekcie zegara; wait_ms/TTL nadal używają monotonic. Każdy terminalny stan
ma finished_at. Timestamps nie służą do priority ordering.

Compatibility:

- legacy numeryczny `job_id`, state `active`/`queued`, source, priority,
  queue_position, wait_ms, liczniki i nagłówki `X-AI-Gateway-*` pozostają;
- `/status` i `/health` scheduler dodają `job` do active/queued oraz
  `recent_jobs` (ostatnie 128 terminalnych rekordów, kolejność zakończenia);
- status/create/heartbeat lease również dodają zagnieżdżony `job`;
- scheduled HTTP z ticketem dodaje `X-AI-Request-Id` i `X-AI-Job-Id`, także
  dla transportowego 502. Legacy upstream `X-Request-Id` pozostaje odrębny;
- historia jest wyłącznie RAM, ograniczona, bez persistence/resume/recovery
  aktywnych zadań po restarcie. Wewnętrzny history_limit może wynosić 0;
- legacy job_status po release nadal zwraca None; D.2 nie dodaje `/api/v1/jobs`.

Raport: [Stage D.2](../reports/AI_PLATFORM_STAGE_D2_JOB_MODEL_2026-09-22_PL.md).

### 7.3. Unified admission — Stage D.4

**READY FOR SUPERVISOR VALIDATION**, bez walidacji produkcji. Ten paragraf
rozszerza historyczne kontrakty D.2/D.3; nie zmienia lifecycle rezerwacji.

`JobMetadata` i `JobState` dodają `workload`: niemutowalną tuple (JSON array)
`{provider, node, capability}`. Każdy binding musi przejść walidację registry
D.3 przed enqueue. To deklaracja dopuszczonej pracy, nie assignment, health ani
potwierdzenie wykonania. Dane pochodzą ze stałych tras/profili, nigdy z promptu,
modelu lub dowolnego source. Terminal history zachowuje workload. Legacy low-level
scheduler bez metadata nadal dopuszcza pustą tuple; publiczne supported ścieżki
Gateway zawsze budują jawny plan. Assignment HTTP musi należeć do planu.

Scheduled HTTP: wszystkie dziewięć istniejących tras nadal używa tego samego
`PriorityScheduler`. Chat/generate/WVC/embedding mają pojedynczy binding
`ollama-local` + lokalny node + dotychczasową capability. Streaming utrzymuje slot
do finalizacji. Direct proxy helper dopuszcza tylko GET `/api/tags` i `/v1/models`;
nieznana expensive trasa nie ma catch-all passthrough ani domyślnego mapowania.

`POST /resource/leases` przyjmuje opcjonalne `workload`:

| Profil | Dopuszczone wykonanie |
|---|---|
| `external` (brak pola) | legacy Qwen + embeddings + image/edit/video |
| `llm` | Qwen chat/reasoning/text-generation/structured-generation |
| `embeddings` | istniejące scheduled Ollama embeddings |
| `media-image` | Qwen jak w llm + ComfyUI image-generation/image-edit |
| `media-video` | Qwen jak w llm + ComfyUI video-generation |

Nieznany profil/null/inny typ daje generyczne 400 `invalid workload` przed
admission, bez echo wartości. Explicit numeric priority, semantic precedence,
WVC=10, FIFO, queue limit i brak preemption pozostają D.1. Legacy request bez
pola zachowuje możliwość współdzielenia lease Qwen/ComfyUI/embedding.

Leased HTTP waliduje binding przed upstream i nie rezerwuje drugiego slotu.
Jeden lease pozwala na jedno wykonanie naraz: drugi równoległy HTTP albo HTTP
podczas external use dostaje 409. Missing lease daje 404, queued/niezgodny plan
409. `begin/end_use`, streaming/error/cancellation i deferred release nadal
chronią slot HTTP; nie zmieniają reservation JobState na running/failed.

Media external use (localhost-only, istniejąca granica zaufania Resource API):

- POST `/resource/leases/{lease_id}/uses`, dokładny JSON
  `{"provider":"comfyui-local","capability":"video-generation"}` (lub image/edit),
  waliduje descriptor i plan aktywnego lease, zwraca 201 `{"use_id":"..."}`;
- invalid body/provider/capability daje 400, missing lease 404, queued/busy lub
  capability poza planem 409; brak backend call przy odmowie;
- DELETE `/resource/leases/{lease_id}/uses/{use_id}` kończy tylko wskazaną fazę,
  zwraca `released`; stary use_id nie kończy nowej fazy. Nie zwalnia całego lease;
- `/status.resource_leases.leases` dodaje ten sam `job`, `external_in_use` i
  `external_workload` (binding aktualnej fazy lub null), bez use_id i payloadów;
- external phase nie jest HTTP `in_use` pin: heartbeat właściciela podtrzymuje
  lease, a utrata heartbeat nadal pozwala TTL/reaper zwolnić slot po crashu.
  To zachowanie cleanup rezerwacji, nie cancel API produktu ComfyUI;
- explicit release i idle TTL zachowują D.2 completed/expired; completed nadal
  nie potwierdza sukcesu renderu. Assignment i started_at rezerwacji pozostają null.

Supported media executors: `ComfyUIAdapter.generate()` wymaga aktywnego lokalnego
lease z `HERMES_RESOURCE_LEASE_ID` i uzyskuje external use przed przygotowaniem
workflow/files/backend call; oddaje fazę w finally. Worker pozostaje właścicielem
heartbeat i całej rezerwacji. Brak lease/unavailable RM/odmowa blokuje wykonanie,
bez fallback do direct ComfyUI. Health/describe/preflight pozostają read-only.
Global `/foto` wrapper deklaruje media-image i obejmuje guardem wyłącznie generator
(po Qwen); `/wideo` deklaruje media-video, a guard znajduje się w adapterze.
Zmiany są w repo helperach/wrapperach, bez nowego patcha produktu Hermes.
Historyczne recovery generatory i jawny direct-Ollama recovery mode pozostają;
nie są nową publiczną ścieżką admission ani gwarancją izolacji od operatora hosta.

Future EmbeddingProvider musi zbudować descriptor-validated binding `embeddings`
i uzyskać ten sam slot przed `embed()` lub użyć istniejących scheduled HTTP tras.
Nie wolno dispatchować nowego adaptera tylko dlatego, że istnieje descriptor.
Konkretny adapter/model, registry provider type migration, Knowledge Service,
indexing i multi-node wymagają późniejszych decyzji. D.4 ich nie implementuje.

Operacyjnie Gateway, packaged adapter i zmienione repo helpery/wrappery wymagają
spójnej wersji przy przyszłym wdrożeniu; nowy guard ze starym Gateway odmawia
wykonania. Deploy/rollback nie został wykonany. Szczegóły i ograniczenia:
[raport D.4](../reports/AI_PLATFORM_STAGE_D4_UNIFIED_ADMISSION_2026-09-22_PL.md).

---

## 8. Model / Worker Registry

### 8.1. Static descriptors — Stage D.3

Status: **READY FOR SUPERVISOR VALIDATION**, bez nowej walidacji produkcji.
`ai_bridge.providers.registry` dodaje kontrakt konfiguracji `schema_version=1`:

- `NodeDescriptor`: `node_id`;
- `CapabilityDescriptor`: `capability_id`, `provider_types`;
- `LogicalProviderDescriptor`: `provider_id`, `provider_type`, `node_id`, `capabilities`;
- `DescriptorRegistry`: `schema_version`, `nodes`, `capabilities`, `providers`.

Wszystkie rekordy są niemutowalne; kolekcje wewnętrzne są tuples, JSON używa arrays.
Identyfikatory są case-sensitive, 1–128 znaków: pierwszy alfanumeryczny ASCII,
pozostałe ASCII alfanumeryczne, `_`, `-`, `.`. Nie normalizujemy whitespace.
Nieznane pola, typy providera, wersje, duplikaty, puste kolekcje registry/provider
capabilities, nieznane node/capability references i niezgodne typy capability
są odrzucane. Lookup nieznanego ID i niezgodny assignment dają `ValueError`
bez powtarzania wartości wejściowej. Błędy konfiguracji to Pydantic
`ValidationError`; nie są wystawiane jako nowe publiczne HTTP API.

Domyślne wpisy (`node_id` pochodzi z istniejącego `Settings.node_id`):

| Provider ID | provider_type | Deklarowane interfejsy |
|---|---|---|
| ollama-local | llm | chat, reasoning, text-generation, structured-generation, embeddings, streaming |
| comfyui-local | media-generation | image-generation, image-edit, video-generation |
| hermes-local | agent | reasoning, tools, streaming |

`unknown` i `external-reservation` są jawnymi D.2 metadata sentinels z pustym
`provider_types`; nie mogą otrzymać assignment. Pozostałe capabilities wymieniają
dozwolone typy providerów. Registry opisuje interfejsy dotychczasowych backendów:
`embeddings` oznacza istniejące proxy routes, nie zainstalowany embedding model,
nowy EmbeddingProvider ani uruchomienie Knowledge Service. Ollama streaming to
możliwość istniejącego Gateway proxy; Stage C `OllamaAdapter.stream()` pozostaje
niezaimplementowany. Hermes/ComfyUI entries nie potwierdzają dostępności API,
skonfigurowanych toolsets, modeli ani workflows.

`LogicalProviderDescriptor` jest statycznym kontraktem inventory, odrębnym od
istniejącego Stage C `ProviderDescriptor` zwracanego przez adapter `describe()`.
Ten drugi zachowuje models/status/metadata i dotychczasową semantykę health.
D.3 nie wywołuje adapterów ani probe na potrzeby registry i nie oznacza wpisów
jako ready. Brak pól URL, credentials, models, dowolnego metadata i prompt content.
Docelowe model descriptors poniżej pozostają przyszłym kontraktem.

Konfiguracja: brak/null `Settings.gateway_registry` wywołuje
`local_descriptor_registry(Settings.node_id)` z kodu pakietu. Opcjonalne
`AI_BRIDGE_GATEWAY_REGISTRY` jest pełnym JSON obiektem, nie ścieżką do pliku.
Przykład: [gateway-registry.example.json](../../deploy/gateway-registry.example.json).
Przy niestandardowym node_id wszystkie provider references muszą wskazywać ten
sam node. Konfiguracja jest walidowana przy tworzeniu Gateway, przed klientem
HTTP: D.3 wymaga jednego lokalnego node i dokładnie obecnych trzech bindings oraz
capabilities (kolejność dowolna). Brak dynamic reload/discovery, wyboru modelu,
fallback, dispatch do Hermesa/ComfyUI lub multi-node execution. Sam schemat
registry potrafi reprezentować kilka node'ów; aktywny Gateway D.3 odrzuca je.

`/status` dodaje `registry` z kopią konfiguracji. Legacy pola i `/health` zachowują
semantykę; registry nie wpływa na health/admission. Wewnętrzny scheduler waliduje
capability metadata przed enqueue, a parę provider/node i obsługę capability
przed zapisaniem running/assignment. Odrzucenie jest atomowe, bez zmiany joba
lub utraty slotu. Zwykłe HTTP przypisuje wpis `ollama-local` dopiero przy wykonaniu,
zachowując assignment także w historii błędów/streamingu. Queued i external lease
(także podczas leased HTTP) nadal mają assignment null. Source/route Hermes/media
nie jest dowodem wykonania przez danego providera. Nie powstaje nowy request
envelope ani D.4 unified admission.

### ProviderDescriptor

```json
{
  "provider_id": "ollama-local",
  "type": "llm",
  "node_id": "ai-node-01",
  "capabilities": ["chat", "reasoning", "structured-generation"],
  "models": ["reasoning-main"],
  "status": "ready",
  "metadata": {}
}
```

### Logical model descriptor

```json
{
  "logical_id": "reasoning-main",
  "capabilities": ["reasoning", "tools"],
  "provider_id": "ollama-local",
  "provider_model_id": "qwen3.6:35b-hermes64k-gpu",
  "context_window": 65536,
  "fallback": null
}
```

Klienci używają `logical_id`/capability. Fizyczna nazwa modelu pozostaje wewnątrz registry.

---

## 9. Knowledge Service

### KnowledgeQuery

```json
{
  "request_id": "req_...",
  "domain": "ecu-repair",
  "query": "MPC564 ...",
  "mode": "hybrid",
  "source_types": ["repair-case", "datasheet", "documentation"],
  "filters": {},
  "limit": 10
}
```

Dozwolone `mode`:

- `exact`
- `keyword`
- `semantic`
- `hybrid`
- `auto`

### KnowledgeResult

```json
{
  "result_id": "kr_...",
  "text": "...",
  "source": {
    "type": "datasheet",
    "uri": "...",
    "title": "..."
  },
  "score": 0.92,
  "metadata": {
    "domain": "ecu-repair"
  }
}
```

Score z różnych backendów nie musi mieć identycznej semantyki. Knowledge Service odpowiada za normalizację/ranking na poziomie API.

---

## 10. TelemetryBackend

Telemetry nie przechodzi przez vector DB jako podstawowy magazyn.

Minimalny kontrakt:

```text
ingest(batch)
query(range, filters)
latest(source)
health()
```

WVC zachowuje własny kontrakt telemetryczny. Platforma nie może wymusić zależności sterowania od dostępności AI.

### Freshness

Każdy system analityczny pracujący na telemetrii musi móc stwierdzić:

```text
fresh
stale
missing
```

Dla `stale/missing` domena może deterministycznie zwrócić `skipped/no_fresh_data`.

---

## 11. StorageBackend / Object Storage

Do dużych artefaktów:

- zdjęcia,
- PDF,
- BIN,
- EEPROM/FLASH dumps,
- logi,
- capture CAN,
- media,
- wygenerowane artefakty.

### ObjectRef

```json
{
  "object_id": "obj_...",
  "domain": "ecu-repair",
  "media_type": "application/octet-stream",
  "size_bytes": 123,
  "sha256": "...",
  "storage_uri": "...",
  "retention_class": "permanent"
}
```

Platformowe API przekazuje `ObjectRef`, a nie lokalną ścieżkę konkretnego hosta.

---

## 12. ToolProvider

Narzędzie posiada descriptor:

```json
{
  "tool_id": "ecu.binary.compare",
  "domain": "ecu-repair",
  "version": "1",
  "risk_class": "read-only",
  "input_schema": {},
  "output_schema": {},
  "required_permissions": []
}
```

Kategorie ryzyka:

- `read-only`
- `write-low-risk`
- `write-sensitive`
- `hardware-action`

Dostęp do toola jest rozstrzygany przez politykę domeny, nie przez sam model.

---

## 13. Domain Adapter

Każda domena rejestruje co najmniej:

```text
domain_id
capabilities
routes
toolsets
knowledge_namespaces
permissions
health
```

Przykład WVC:

```yaml
domain_id: wvc
knowledge_namespaces:
  - wvc
  - shared
capabilities:
  - telemetry-analysis
  - reasoning
control_policy: advisory_only
```

Przykład ECU:

```yaml
domain_id: ecu-repair
knowledge_namespaces:
  - ecu-repair
  - shared
capabilities:
  - reasoning
  - vision
  - binary-analysis
```

---

## 14. Błędy platformowe

Normalizujemy błędy:

```json
{
  "error": {
    "code": "provider_unavailable",
    "message": "Reasoning provider is unavailable",
    "request_id": "req_...",
    "retryable": true,
    "details": {}
  }
}
```

Podstawowe kody:

- `invalid_request`
- `unauthorized`
- `forbidden`
- `not_found`
- `queue_full`
- `deadline_exceeded`
- `provider_unavailable`
- `capability_unavailable`
- `tool_failed`
- `storage_failed`
- `internal_error`

Provider-specific exceptions nie powinny trafiać bezpośrednio do klientów.

---

## 15. Health i readiness

Każdy service/provider udostępnia logicznie:

```text
liveness  -> proces działa
readiness -> może przyjąć pracę
health    -> szczegółowy stan
```

Platform Health agreguje stan bez konieczności odpytania przez klienta Ollamy, Hermesa czy ComfyUI bezpośrednio.

---

## 16. Versioning

### Platform API

`/api/v1/...`

### Contract schemas

Każdy utrwalany payload ma `schema_version`, jeśli będzie odczytywany długoterminowo lub przez wiele komponentów.

### Providers

Provider może mieć własną wersję adaptera niezależną od wersji produktu.

Przykład:

```text
Hermes product: 0.x
HermesAdapter contract: v1
Platform API: v1
```

---

## 17. Compatibility rule

Zmiana backendu jest poprawna bez migracji klientów, jeżeli:

1. obsługuje wymagany contract version,
2. deklaruje wymaganą capability,
3. przechodzi contract tests,
4. zachowuje normalizowany model błędów,
5. spełnia politykę bezpieczeństwa i Resource Managera.

---

## 18. Contract tests

Każdy adapter musi posiadać testy kontraktowe.

Przykłady:

```text
test_llm_provider_contract
test_agent_provider_contract
test_media_provider_contract
test_knowledge_backend_contract
test_storage_backend_contract
```

Dzięki temu np. `OllamaAdapter` i przyszły `vLLMAdapter` przechodzą ten sam zestaw wymagań.

---

## 19. Zasada końcowa

**Domena zależy od kontraktu platformy. Adapter zależy od produktu. Produkt nigdy nie staje się kontraktem domeny.**
