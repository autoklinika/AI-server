# Router benchmark — Clef System One vs GLiNER2.5-Decide — 2026-10-03

Authoritative frozen comparison after production upgrade to Ollama 0.35.1.

## Inputs

- 51 router cases from `golden.v1.jsonl`
- dataset SHA-256: `1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf`
- benchmark code commit: `22b90980925d237a2944bc17ae1fc726d3e982f0`
- Clef digest: `2bb11a61d1fb5d7a51f136ad9f569f970727377cf7b96037a06285d81fa25b73`
- GLiNER revision: `5a7adf72a23b4d311abae6ce050d7f0012bb3416`

## Overall

| Metric | Clef | GLiNER 340M |
|---|---:|---:|
| Route accuracy | 94.12% | 80.39% |
| Macro-F1 | 0.8770 | 0.7227 |
| Tool exact accuracy | 88.24% | 45.10% |
| Tool recall | 91.18% | 50.00% |
| Tool false positive | 0.00% | 49.02% |
| Mean latency | 5625.8 ms | 564.2 ms |

## Interpretation boundary

Clef is substantially stronger on route and tool policy, but it is not a
lightweight pre-router on the current host: observed residency is ~23 GB GPU,
warm decisions are ~10× slower than GLiNER, and the current production contract
allows one loaded Ollama model. P5.11 cold restore after the benchmark took
12.014 s.

No production routing or resource-policy change is authorized by this result.

Artifacts:
- `clef-all-run.json` / `clef-all-eval.json`
- `gliner340-all-run.json` / `gliner340-all-eval.json`
- `comparison.json`
- `runtime-evidence.json`
- `SHA256SUMS`
