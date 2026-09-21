# AI Platform — Stage C Provider Abstraction Final Report

**Data:** 2026-09-21  
**Branch:** `stage-c/provider-abstraction`  
**Final validated runtime release:** `stage-c-provider-abstraction-20260921-r3`  
**Runtime source SHA:** `cfe1b12ba5a35e2975ff942a2509ab2eaa3e21c5`

## 1. Cel Stage C

Stage C oddziela AI Platform od konkretnych produktów/backendów przez stabilne kontrakty i adaptery, bez wymiany działających providerów.

Wdrożone granice:

- `LLMProvider`
- `AgentProvider`
- `MediaGenerationProvider`
- `EmbeddingProvider`
- `KnowledgeBackend` (retrieval contract only)

Pierwsze adaptery:

- `OllamaAdapter`
- `HermesAdapter`
- `ComfyUIAdapter`

## 2. C.1 — LLMProvider

- WVC analysis zależy od `LLMProvider`, nie od `OllamaClient`.
- `OllamaAdapter` mapuje logiczny request na istniejący Ollama/AI Gateway runtime.
- model Qwen i scheduler semantics nie zostały zmienione.
- contract tests: PASS.

## 3. C.2 — AgentProvider

- dodano `AgentProvider` i `HermesAdapter`,
- integracja używa udokumentowanej granicy HTTP Hermesa,
- produkcyjny Hermes nie został przebudowany ani zrestartowany,
- izolowany no-tools E2E przez Hermes -> AI Gateway -> Qwen: PASS,
- `allowed_toolsets` pozostaje fail-closed dla nieobsługiwanej per-request narrowing.

## 4. C.3 — MediaGenerationProvider

- dodano `MediaGenerationProvider` i `ComfyUIAdapter`,
- Stage30 nie używa już bezpośrednio transportu ComfyUI,
- input staging/cleanup należy do adaptera,
- produkcyjny `/wideo` wrapper przełączony na Stage C provider wrapper,
- realny render smoke 640x384 / 24 fps / 25 frames: PASS,
- globalny Resource Manager lease obejmuje render,
- Telegram `/wideo` zwalidowany na dwóch kontach bez cross-chat routing.

## 5. WVC compatibility incident podczas Stage C

Regresja ujawniła istniejący wcześniej schema drift:

- CM5 wysyłał `metrics.calendar`,
- AI Bridge odrzucał pole przez strict schema jako `extra_forbidden`,
- backlog CM5 był blokowany od 2026-08-27.

Naprawa:

- jawne opcjonalne passthrough fields:
  - `calendar`,
  - `power_scheduler`,
- strict rejection pozostał dla innych nieznanych pól.

Po wdrożeniu:

- wszystkie requesty WVC: HTTP 200,
- lokalny backlog CM5: `pending=0`,
- żadnych danych nie kasowano ręcznie.

## 6. C.4 — EmbeddingProvider + KnowledgeBackend

Dodano neutralne kontrakty:

- batch embeddings,
- jawny model/provider result metadata,
- KnowledgeQuery z:
  - domain,
  - namespaces,
  - source_types,
  - filters,
  - modes exact/keyword/semantic/hybrid/auto,
  - opcjonalnym query_embedding,
- KnowledgeResult z source attribution.

Świadomie nie wybrano jeszcze:

- modelu embeddingowego,
- pgvector vs Qdrant,
- Knowledge Service/API,
- indexing/upsert/delete pipeline,
- rerankera,
- graph DB.

## 7. Final hardening

### Hermes streaming errors

Błąd HTTP w `httpx.stream()` jest teraz konsumowany w otwartym stream context, aby wtórny `ResponseNotRead` nie maskował pierwotnego błędu providera.

### node_id

Deployment identity nie jest już zaszyty w adapterach.

- adaptery: `node_id: str | None`,
- deployment: `Settings.node_id`,
- default obecnego hosta: `ai-node-01`,
- composition roots przekazują node do providerów.

### Media artifact boundary

`output_dir` pozostaje przejściowym wewnętrznym parametrem provider execution.

Docelowy Platform API ma używać `ObjectRef` po wprowadzeniu StorageBackend; lokalne ścieżki hosta nie mogą stać się trwałym API domen.

## 8. Final release validation — r3

Potwierdzone:

- targeted hardening tests: PASS,
- deploy safety tests: PASS,
- full test suite: PASS,
- final-path venv/shebang validation: PASS,
- provider imports: PASS,
- Stage30 standard preflight: PASS,
- Stage30 HQ + I2V preflight: PASS,
- AI Bridge health: PASS,
- AI Gateway/Ollama health: PASS,
- effective node_id: `ai-node-01`,
- real media smoke: PASS,
- output: H.264, 640x384, 24 fps, 25 frames, ~1.04 s,
- Resource Manager after smoke: 0 active / 0 queued / 0 leases,
- ComfyUI queue after smoke: empty,
- WVC ingest after cutover: repeated HTTP 200,
- Hermes PID unchanged,
- ComfyUI PID unchanged,
- media wrapper unchanged during r3 activation.

## 9. Rollback

Release rollback:

```text
deploy/stage-c/rollback_release.sh
```

Media wrapper rollback:

```text
deploy/stage-c/rollback_media_wrapper.sh
```

Previous runtime release before r3:

```text
/opt/ai-platform/releases/stage-c-provider-abstraction-20260921-r2
```

Pre-Stage-C media wrapper backup remains preserved under recovery storage.

## 10. Remaining gate before merge

One final Telegram `/wideo` user-path regression on r3, then:

- final issue checkpoint,
- branch review,
- merge decision to `main`.

No merge is performed by this report.
