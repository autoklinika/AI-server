# Stage J2 — Knowledge retrieval benchmark

## Cel

Benchmark służy do wyboru **wewnętrznej konfiguracji indeksu**, nie publicznego
kontraktu Knowledge Service. Backend, model embeddingowy i chunking mogą zostać
zmienione przez reindex bez zmiany klientów.

## Korpus

Benchmark korzysta z:
- prywatnego `autoklinika/EcuRepairService`, z read-only cache wskazywanego przez
  `ECU_REPAIR_KNOWLEDGE_ROOT` (domyślnie
  `/srv/ai-data/knowledge/source-cache/EcuRepairService`);
- `docs/architecture/WVC_DOMAIN.md` z bieżącego checkoutu AI-server.

Runner odmawia pracy, jeżeli cache ECU ma inny origin albo lokalne modyfikacje.
Wynik zapisuje exact Git commit obu źródeł.

## Metryka jakości

13 pytań obejmuje semantic, mixed, exact i cross-language retrieval.
Gold nie jest nazwą pliku. Trafienie wymaga, aby zwrócony **chunk zawierał
jawny dowód odpowiedzi** (np. K23/K82/K85, numer Bosch, no_fresh_data).

Mierzymy Recall@1 / Recall@3 / Recall@5, MRR, czas embeddingu korpusu i pytań
oraz czas search Qdranta. Exact identifiers sprawdzają odporność dense retrieval,
ale docelowa architektura nadal przewiduje exact/full-text + hybrid retrieval.

## Uruchomienie

```bash
PYTHONPATH=src .venv/bin/python benchmarks/knowledge/run_dense_benchmark.py \
  --models bge-m3 qwen3-embedding:0.6b qwen3-embedding:4b \
  --chunk-chars 2400 \
  --output benchmarks/knowledge/results/my-run.json
```

Embeddingi idą przez `AI_GATEWAY_URL` (domyślnie `:11435`), więc podlegają
Resource Managerowi. Qdrant jest używany przez `QDRANT_URL` (domyślnie `:6333`).
Każdy wariant używa tymczasowej kolekcji usuwanej w `finally`.

## Wynik 2026-09-23

Autorytatywny baseline jakości: `results/dense_solo_final_2026-09-23.json`.

| Model | Chunk | Dim | Recall@1 | Recall@3 | Recall@5 | MRR | Corpus embed | Query embed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BGE-M3 | ~2400 | 1024 | 92.3% | 100% | 100% | 0.962 | 15.8 s | 0.461 s |
| Qwen3-Embedding 0.6B | ~2400 | 1024 | 92.3% | 100% | 100% | 0.962 | 22.9 s | 0.445 s |
| Qwen3-Embedding 4B | ~2400 | 2560 | 92.3% | 100% | 100% | 0.962 | 88.9 s | 1.092 s |

Dodatkowy sweep BGE-M3: `results/bge_chunk_refinement_2026-09-23.json`.

- ~1200: Recall@1 84.6%, MRR 0.910
- ~1600: Recall@1 84.6%, MRR 0.923
- **~2400: Recall@1 92.3%, MRR 0.962**
- ~3200: Recall@1 84.6%, MRR 0.923
- wszystkie warianty BGE osiągnęły Recall@3/5 = 100%.

`dense_source_label_exploratory_2026-09-23.json` jest zachowany tylko jako
pierwszy eksperyment i źródło porównawcze latency. Jego pierwotny gold opierał
się na nazwach źródeł, więc nie wolno używać jego quality metrics do decyzji.

`dense_evidence_2026-09-23.json` potwierdza evidence-based scoring, ale czas
całego przebiegu był zanieczyszczony kolejką Resource Managera; do porównania
latency używamy solo/refinement runs.

## Decyzja baseline

Stage J2 rozpoczyna produkcyjny rozwój z:
- model: `bge-m3`;
- dense dimensions: `1024`;
- distance: cosine;
- heading-aware chunk target: około `2400` znaków;
- model i parametry są częścią konfiguracji indeksu, nie canonical identity.

Zmiana baseline wymaga reindex, ale nie migracji klienta Knowledge Service.
