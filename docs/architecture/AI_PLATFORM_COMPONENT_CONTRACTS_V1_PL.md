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

---

## 8. Model / Worker Registry

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
