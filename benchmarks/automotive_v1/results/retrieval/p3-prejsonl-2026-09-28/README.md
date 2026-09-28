# P3 retrieval baseline — pre JSONL sync

This directory captures the production Knowledge retrieval baseline before the
new record-level JSONL synchronization is applied.

Runtime identity:

- Platform release: stage-o-491e982e627e
- Platform source SHA: 491e982e627e8b550dcea0742693bb903009622f
- benchmark runner commit: c520cbd1426319616442dedb5af2d7ce8d58ef40
- ERS source commit: 81909b30ef18ca2053bd7496d6faeb814d4e9866
- golden dataset SHA-256:
  1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf
- retrieval mode: hybrid
- top-k: 10

Raw retrieval uses rerank=false. Reranked retrieval uses the production
TechnicalEvidenceReranker through the stable Knowledge API.


## Aggregate metrics

Raw:
- dev Recall@1/3/5 = 59.6% / 76.9% / 92.3%, MRR 0.739,
- holdout = 70.0% / 95.0% / 100%, MRR 0.829,
- challenge = 73.3% / 93.3% / 100%, MRR 0.847.

Reranked:
- dev = 59.6% / 96.2% / 100%, MRR 0.777,
- holdout = 75.0% / 95.0% / 100%, MRR 0.843,
- challenge = 80.0% / 93.3% / 100%, MRR 0.880.

Mean search latency is approximately 254–260 ms/query for both tracks.

## Network subgroup

Before the new JSONL sync:

- J1939 raw Recall@1/3/5 = 55.6% / 77.8% / 88.9%.
- J1939 reranked = 66.7% / 88.9% / 100%.
- LIN raw = 66.7% / 100% / 100%.
- LIN reranked = 66.7% / 83.3% / 100%.

This is the fixed A-side for the later post-ingestion comparison.
