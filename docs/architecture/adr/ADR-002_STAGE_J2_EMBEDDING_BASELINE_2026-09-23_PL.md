# ADR-002 — Stage J2: baseline embedding i chunking

**Status:** ACCEPTED
**Data:** 2026-09-23
**Zakres:** Stage J / Knowledge Service / indeks dense

## Kontekst

Po ADR-001 Qdrant jest wymiennym backendem. Stage J2 wymaga pierwszej konkretnej
konfiguracji embeddingu i chunkingu, aby można było budować ingestion/reindex
na danych ECU/WVC bez przecieku modelu do klientów Knowledge Service.

## Benchmark

Benchmark użył 20 rzeczywistych dokumentów Markdown z EcuRepairService/WVC
oraz 13 pytań semantic, mixed, exact i cross-language. Trafienie jest oceniane
po obecności dowodu odpowiedzi w zwróconym chunku, a nie po samej nazwie pliku.

Autorytatywny przebieg porównawczy `dense_solo_final_2026-09-23.json`:

| Model | Dim | Recall@1 | Recall@3 | Recall@5 | MRR | Corpus embed | Query embed |
|---|---:|---:|---:|---:|---:|---:|---:|
| BGE-M3 | 1024 | 92.3% | 100% | 100% | 0.962 | 15.8 s | 0.461 s |
| Qwen3-Embedding 0.6B | 1024 | 92.3% | 100% | 100% | 0.962 | 22.9 s | 0.445 s |
| Qwen3-Embedding 4B | 2560 | 92.3% | 100% | 100% | 0.962 | 88.9 s | 1.092 s |

Qwen3-Embedding 8B został odrzucony wcześniej: przy ~2400 znaków nie dawał
mierzalnej przewagi jakościowej nad mniejszymi kandydatami, a generował wektor
4096D i najwyższy koszt embeddingu.

Sweep BGE-M3 dla 1200/1600/2400/3200 znaków pokazał najlepszy Recall@1/MRR
dla wariantu około 2400 znaków. Wszystkie warianty osiągnęły Recall@3/5 = 100%.

## Decyzja

Pierwszy baseline indeksu dense Stage J:

- embedding model: `bge-m3`;
- vector dimensions: `1024`;
- distance: cosine;
- heading-aware target chunk size: około `2400` znaków;
- query/document embedding przechodzi przez neutralny `EmbeddingProvider`;
- fizyczna nazwa modelu pozostaje konfiguracją Knowledge Service/ingestion;
- klient Knowledge Service nigdy nie podaje embeddingu ani nazwy modelu w normalnym użyciu.

## Dlaczego BGE-M3

Na korpusie projektu osiągnął tę samą jakość co Qwen 0.6B/4B przy 2400 znakach,
zachowując 1024D. W czystym przebiegu miał najkrótszy czas embeddingu korpusu.
Nie wymaga też query instruction używanej przez Qwen. Wymiar 1024 ogranicza
koszt storage/HNSW w porównaniu z 2560D/4096D.

Dodatkowo `ollama ps` na obecnym AI Serverze raportował około 655 MB runtime dla
BGE-M3 podczas embedding requestu, wobec około 5.7 GB dla Qwen3-Embedding 0.6B
i 9.8 GB dla 4B. Jest to pomiar runtime/context na tym hoście, nie katalogowa
wartość VRAM, ale ma znaczenie dla współdzielenia GPU z głównym LLM/ComfyUI.

## Wymienialność

Ten ADR nie zmienia publicznego kontraktu. Model embeddingowy i parametry chunkingu
są właściwością wersji indeksu. Ich zmiana oznacza kontrolowany reindex z
kanonicznych `Source -> Document -> DocumentVersion -> Chunk`, bez migracji
Hermesa, Telegrama, Discorda, GUI ani agentów.

## Exact/hybrid

Dobry wynik dense dla kodów technicznych nie znosi wymagania ADR-001/architektury.
Numery DTC, part numbery, piny i identyfikatory mają docelowo korzystać również
z exact/full-text/sparse/hybrid retrieval. Stage J2 nie udaje hybrid search.

## Gate zmiany baseline

Zmiana modelu/chunkingu wymaga:
1. tego samego lub rozszerzonego benchmarku z evidence-based gold;
2. porównania Recall@K/MRR i kosztu operacyjnego;
3. reindexu do nowej wersji fizycznego indeksu;
4. smoke source attribution;
5. możliwości rollbacku do poprzedniej konfiguracji indeksu.
