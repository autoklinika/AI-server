# AI Platform — Router Decision Models / System One benchmark — 2026-10-03

## Cel

Po migracji produkcyjnej Ollama 0.32.14 → 0.35.1 porównano natywny model
decyzyjny Clef przez endpoint System One z dotychczasowym najmocniejszym
lekkim routerem CPU: fastino/GLiNER2.5-Decide 340M.

Benchmark nie zmienia produkcyjnego routingu. Jest warstwą ewaluacyjną i
pozostawia decyzję o architekturze routera poza automatycznym gate.

## Frozen identity

- dataset: `golden.v1.jsonl`, 51 router cases
- dataset SHA-256: `1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf`
- benchmark code: `22b90980925d237a2944bc17ae1fc726d3e982f0`
- Ollama: `0.35.1`
- Clef digest: `2bb11a61d1fb5d7a51f136ad9f569f970727377cf7b96037a06285d81fa25b73`
- Clef installed model size: 17,987,253,552 bytes
- Clef observed resident size: ~23 GB, 100% GPU
- Clef observed runtime context: 16,384
- GLiNER revision: `5a7adf72a23b4d311abae6ce050d7f0012bb3416`
- GLiNER2: 2.0.0; Torch: 2.14.0+cpu
- GLiNER2 implementation SHA-256: `791814c58c3674f0b546c67d90ab5013bf645e5eda29d25e9fd17fa100aaa061`

## Wynik 51-case

| Metryka | Clef / System One | GLiNER2.5-Decide 340M |
|---|---:|---:|
| Route accuracy | 94.12% | 80.39% |
| Macro-F1 | 0.8770 | 0.7227 |
| Tool exact accuracy | 88.24% | 45.10% |
| Tool recall | 91.18% | 50.00% |
| Tool false-positive rate | 0.00% | 49.02% |
| Średnia latency | 5625.8 ms | 564.2 ms |
| Max latency | 5953.9 ms | 687.2 ms |

Różnica Clef względem GLiNER:
- route accuracy: +13.73 pp,
- macro-F1: +0.1543,
- tool exact accuracy: +43.14 pp,
- tool recall: +41.18 pp,
- false-positive rate: -49.02 pp,
- latency: 9.97× wyższa.

Wszystkie 51 przypadków obu modeli zakończyły się mechanicznie poprawnie.
Clef nie wygenerował żadnego błędu kontraktu System One.

## Wynik per split

| Split | Clef route / F1 | GLiNER route / F1 | Clef tool exact | GLiNER tool exact |
|---|---:|---:|---:|---:|
| dev (23) | 91.30% / 0.7222 | 82.61% / 0.6698 | 86.96% | 39.13% |
| holdout (15) | 100.00% / 1.0000 | 80.00% / 0.7048 | 93.33% | 53.33% |
| challenge (13) | 92.31% / 0.7895 | 76.92% / 0.4737 | 84.62% | 46.15% |

Clef ma 100% route recall dla klas: graphify, reasoning, telemetry, tool i vision.
Dla dominującego knowledge_rag recall wynosi 92.68%.

Błędy route Clef:
- ERS-GOLD-0005: knowledge_rag → reasoning,
- ERS-GOLD-0011: knowledge_rag → telemetry,
- ERS-GOLD-0058: knowledge_rag → reasoning.

Kanoniczny scorer porównuje wybrane narzędzia jako zbiór, więc różna kolejność
tych samych narzędzi nie jest liczona jako błąd. Clef ma 6 realnych mismatchów
tool-policy; dominują pominięcia knowledge.search jako narzędzia pomocniczego.

## Stabilność

Przed i po benchmarku liczniki kernela pozostały bez zmian:
- MES failed=14,
- GPU reset=10,
- ring timeout=0,
- GPUVM fault=0,
- device wedged=2.

## Granica operacyjna

Aktualna produkcja ma `OLLAMA_MAX_LOADED_MODELS=1`.
Clef i P5.11 są osobnymi modelami klasy ~27B, więc router Clef per-request
powodowałby przełączanie rezydencji GPU zamiast lekkiego pre-routera.

Zaobserwowane cold-load:
- pierwszy smoke Clef: ~12.06 s,
- przywrócenie P5.11 po benchmarku: 12.014 s.

Z tego powodu wynik jakościowy Clef nie jest równoznaczny z gotowością do
wpięcia go przed każdym żądaniem produkcyjnym. W obecnym resource contract
koszt przełączania modeli jest istotniejszy niż sama warm latency ~5.6 s.

GLiNER pozostaje około 10× szybszy i CPU-only, ale jego jakość tool-policy
jest znacznie słabsza. Clef jest natomiast bardzo dobrym źródłem decyzji
referencyjnych/teacherem do kalibracji lub treningu lekkiego routera.

## Decision boundary

- brak automatycznej zmiany produkcyjnego routera,
- brak zmiany `OLLAMA_MAX_LOADED_MODELS=1`,
- P5.11 pozostaje produkcyjnym LLM i został ponownie załadowany po benchmarku,
- Clef pozostaje zainstalowanym kandydatem benchmarkowym,
- frozen wyniki są podstawą do następnego etapu router architecture/calibration.

Pełne artefakty i SHA-256:
`benchmarks/automotive_v1/results/router/systemone-2026-10-03/`.
