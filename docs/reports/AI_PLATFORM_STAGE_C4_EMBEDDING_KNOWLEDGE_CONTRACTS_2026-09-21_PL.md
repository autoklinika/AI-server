# AI Platform — Stage C.4 EmbeddingProvider + KnowledgeBackend contracts

**Data:** 2026-09-21  
**Branch:** `stage-c/provider-abstraction`  
**Zakres:** kontrakty platformowe bez rollout Knowledge Service i bez wyboru konkretnego backendu/modelu.

## 1. Cel

Stage C.4 kończy bazowy zakres provider abstraction przez dodanie stabilnych granic dla:

- generowania embeddingów,
- retrieval wiedzy.

Zmiana nie wdraża nowej funkcji użytkowej. Nie uruchamia Knowledge Service, nie tworzy vector DB, nie wybiera modelu embeddingowego i nie zmienia obecnego runtime.

## 2. EmbeddingProvider

Dodany kontrakt:

```text
embed(request) -> EmbeddingResult
health()       -> ProviderHealth
describe()     -> ProviderDescriptor
```

`EmbeddingRequest` przenosi:

- `request_id`,
- batch `inputs`,
- capability `embeddings`,
- opcjonalny `model_hint`,
- opcjonalny `dimensions_hint`,
- jawny `context`,
- opcjonalny `provider_hint`.

`EmbeddingResult` zwraca:

- uporządkowane wektory z indeksem wejścia,
- provider,
- model,
- wymiar wektora,
- opcjonalne usage/latency,
- kontrolowane `provider_metadata`.

Kontrakt nie zawiera nazw Ollama, Qwen ani innego konkretnego runnera/modelu.

## 3. KnowledgeBackend

Dodany kontrakt retrieval:

```text
search(query) -> KnowledgeSearchResult
health()      -> ProviderHealth
describe()    -> ProviderDescriptor
```

`KnowledgeQuery` zachowuje zatwierdzony kontrakt architektury:

- jawny `request_id`,
- jawny `domain`,
- treść `query`,
- tryb:
  - `exact`,
  - `keyword`,
  - `semantic`,
  - `hybrid`,
  - `auto`,
- `namespaces`,
- `source_types`,
- `filters`,
- `limit`,
- opcjonalny `query_embedding`,
- jawny `context`.

Wynik zachowuje attribution:

- `result_id`,
- `text`,
- `source.type`,
- `source.uri`,
- `source.title`,
- backend-specific raw `score`,
- `metadata`.

Score nie jest traktowany jako wspólna znormalizowana miara. Przyszły Knowledge Service odpowiada za normalizację/ranking na poziomie API.

## 4. Granica EmbeddingProvider vs KnowledgeBackend

Embedding nie jest częścią kontraktu konkretnego vector backendu.

Docelowy przepływ może wyglądać:

```text
Knowledge Service
  |
  +-- EmbeddingProvider -> query embedding
  |
  +-- KnowledgeBackend.search(query + optional embedding)
```

Dzięki temu:

- model embeddingowy może być wymieniony niezależnie od vector DB,
- pgvector/Qdrant pozostają wymiennymi implementacjami,
- backend exact/keyword może działać bez embeddingu,
- hybrid retrieval nie wymusza jednego produktu.

## 5. Świadomie odłożone

Stage C.4 nie definiuje jeszcze:

- modelu embeddingowego,
- adaptera embeddingowego,
- pgvector vs Qdrant,
- API Knowledge Service,
- indexing/upsert/delete contract,
- chunkingu dokumentów,
- rerankera,
- graph DB,
- pipeline ingestu plików/PDF/GitHub/object storage.

Write/indexing contract zostanie określony razem z Knowledge Service i pipeline'em źródeł, aby nie zamrozić go przedwcześnie.

## 6. Testy kontraktowe

Dodane testy obejmują:

- runtime `EmbeddingProvider` Protocol,
- zachowanie kolejności batch embeddingów,
- wymiar wektorów,
- wszystkie tryby KnowledgeQuery v1,
- jawny domain + namespaces,
- opcjonalny query embedding,
- source attribution,
- runtime `KnowledgeBackend` Protocol,
- brak vendor/product leakage w polach kontraktu.

## 7. Runtime / rollback

Ta zmiana jest source-only i nie zmienia działającej produkcji.

Do czasu zbudowania kolejnego release:

- aktywny Stage C r1 pozostaje bez zmian,
- WVC pozostaje zsynchronizowany,
- Hermes/Telegram/Discord pozostają bez zmian,
- media wrapper Stage C pozostaje aktywny,
- nie uruchamiamy żadnego Knowledge Service.

Rollback source: poprzedni commit/branch state.  
Rollback runtime: nie jest potrzebny, ponieważ C.4 nie został jeszcze aktywowany w runtime.
