# AI Platform — Stage J2: canonical knowledge + embedding baseline

**Data:** 2026-09-23
**Status:** IMPLEMENTATION / BENCHMARK / LIVE E2E PASS
**Branch:** `stage-j2/embedding-benchmark`

## Cel

Wybrać pierwszy profil embedding/chunking na rzeczywistych danych ECU/WVC i
zdefiniować kanoniczną wiedzę poza Qdrantem. Model, wymiar i vector backend
pozostają wymienialną konfiguracją indeksu.

## Źródła i zasada read-only

Benchmark ECU czyta cache repozytorium `autoklinika/EcuRepairService`:
`/srv/ai-data/knowledge/source-cache/EcuRepairService`.

- source commit: `0ee98b94705b691d7347c8a6a5676ac63159e359`;
- cache po testach: `main...origin/main`, working tree clean;
- runner sprawdza origin i clean status przed startem;
- w repo EcuRepairService nie wykonujemy zapisu, commitów, checkoutów ani push;
- do AI-server nie kopiujemy źródłowych materiałów ECU.

Korpus: 19 Markdownów EcuRepairService + `WVC_DOMAIN.md` = 20 dokumentów.
PDF-y pozostają materiałem dla późniejszego parser/ingestion gate.
## Metodologia

13 pytań obejmuje semantic, exact, mixed i cross-language retrieval.
Gold jest evidence-based: trafienie wymaga obecności konkretnych faktów w treści
zwróconego chunka, a nie tylko poprawnej nazwy dokumentu.

Mierzone: Recall@1/3/5, MRR, czas embeddingu korpusu i pytań oraz latency Qdranta.
Każdy wariant korzysta z tymczasowej kolekcji usuwanej w `finally`.

## Final dense solo-run — chunk ~2400

| Model | Dim | R@1 | R@3 | R@5 | MRR | Corpus embed | Query embed / 13 | Search avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **BGE-M3** | 1024 | 92.3% | 100% | 100% | 0.962 | **15.85 s** | 460.5 ms | 2.01 ms |
| Qwen3 Embedding 0.6B | 1024 | 92.3% | 100% | 100% | 0.962 | 22.94 s | 445.2 ms | 2.44 ms |
| Qwen3 Embedding 4B | 2560 | 92.3% | 100% | 100% | 0.962 | 88.95 s | 1092.1 ms | 4.76 ms |

Evidence: `benchmarks/knowledge/results/dense_solo_final_2026-09-23.json`.

Qwen3 Embedding 8B został usunięty z finalnej shortlisty po eksploracyjnym
przebiegu: przy 2400 znaków nie poprawił source-level retrieval względem 4B,
używał 4096D i miał najwyższy koszt. Eksploracyjny wynik nie jest gold J2.
## Runtime footprint

Podczas pojedynczych requestów `ollama ps` raportował około:

- BGE-M3: 655 MB;
- Qwen3 Embedding 0.6B: 5.7 GB;
- Qwen3 Embedding 4B: 9.8 GB;
- Qwen3 Embedding 8B: 11 GB.

To runtime size raportowany przez Ollamę, nie deklaracja fizycznego VRAM.
Na obecnym współdzielonym iGPU/UMA BGE pozostawia największy budżet dla
LLM i ComfyUI.

## BGE-M3 — refinement chunkingu

| Max chars | Chunks | R@1 | R@3 | R@5 | MRR |
|---:|---:|---:|---:|---:|---:|
| 1200 | 142 | 84.6% | 100% | 100% | 0.910 |
| 1600 | 105 | 84.6% | 100% | 100% | 0.923 |
| **2400** | **69** | **92.3%** | **100%** | **100%** | **0.962** |
| 3200 | 53 | 84.6% | 100% | 100% | 0.923 |

Evidence: `benchmarks/knowledge/results/bge_chunk_refinement_2026-09-23.json`.
## Decyzja J2

Pierwszy baseline indeksu dense:

- model: **BGE-M3**;
- dimensions: **1024**;
- distance: cosine;
- chunking: heading/paragraph-aware, max około **2400 znaków**;
- query/document embedding przechodzi przez neutralny `EmbeddingProvider`;
- fizyczna nazwa modelu nie należy do kontraktu klienta;
- profil jest reindeksowalny i może zostać zmieniony po kolejnym benchmarku.

BGE-M3 wygrywa bilansem jakości i kosztu, nie dlatego, że dense search rozwiązuje
wszystkie przypadki.

Jedyny finalny miss BGE Top-1 to WVC `--end-at`/historical replay: właściwy
dokument jest #1, ale chunk zawierający oba literalne dowody jest #2.
To naturalny kandydat dla exact/lexical + dense hybrid.

## Canonical knowledge model

Zaimplementowano:

```text
KnowledgeSourceRecord
 -> KnowledgeDocumentRecord
   -> KnowledgeDocumentVersionRecord
     -> KnowledgeChunkRecord
```

Własności: deterministyczne ID, SHA-256 wersji i chunków, source revision,
storage URI, locator/metadata, ACL policy ID oraz immutable top-level mappings.
`text_sha256` jest walidowany względem treści chunka.
Model embeddingowy, vector dimensions i Qdrant nie uczestniczą w canonical
identity. Indeks jest odbudowywalną projekcją danych kanonicznych.

## Scheduled EmbeddingProvider

Dodano adapter embeddingów do istniejącego Ollama-compatible Gateway.
Logiczny provider to `embedding-local`; fizyczny runtime pozostaje detalem adaptera.

Normalna ścieżka:

```text
text-only KnowledgeQuery
 -> KnowledgeService
 -> EmbeddingProvider
 -> AI Gateway / Resource Manager
 -> BGE-M3
 -> QdrantKnowledgeBackend
 -> attributed KnowledgeResult
```

Knowledge Service oznacza rolę `query`; klient nie przesyła własnego wektora
ani nazwy modelu. Workload embeddingowy nie omija admission control.

Live E2E dla tej ścieżki: PASS.
Po smoke nie pozostały kolekcje testowe Qdranta.
## Walidacja operacyjna

Po benchmarkach i smoke:
- pełny repo test suite: **856 passed**, 1 pre-existing Starlette deprecation warning;
- targeted Knowledge/Embedding/J2/Gateway tests: PASS;
- live BGE-M3 end-to-end Knowledge smoke: PASS;
- Qdrant temporary collections: 0;
- Resource Manager: active=0, queued=0;
- GPU residency: `llm`;
- `recovery_required=false`;
- w historii RM widoczny poprawnie zakończony workload `chat` po embeddingach;
- EcuRepairService source cache pozostaje clean.

## Artefakty benchmarku

Autorytatywne:
- `dense_solo_final_2026-09-23.json`;
- `bge_chunk_refinement_2026-09-23.json`.

Pomocnicze:
- `dense_source_label_exploratory_2026-09-23.json` — wcześniejsza metodologia source-level;
- `dense_evidence_2026-09-23.json` — evidence scoring przy konkurencji w kolejce,
  nie używać jego latency do decyzji.

## Następny gate

Kolejny krok Stage J to trwały, idempotentny ingestion/reindex:
canonical store, wersjonowanie/checksumy, import Markdown/PDF, wersjonowana
produkcyjna kolekcja Qdranta oraz exact/lexical + dense hybrid.

Knowledge graph nadal nie jest wymagany na tym etapie.
