# AI Platform — Stage P1 Golden Dataset Expansion

Date: 2026-09-28
Baseline: Stage P0 merged to main at 0c6409905446.

## Objective

Expand the benchmark foundation into a pilot-ready, model-independent golden
dataset without starting model training or expensive benchmark inference.

P1 keeps three independent benchmark classes:
- large-LLM automotive reasoning,
- decision/router policy,
- retrieval/reranking/RAG.

## Dataset result

Golden dataset v1 now contains 72 benchmark-only cases:

- 58 LLM-targeted,
- 51 router-targeted,
- 61 retrieval/RAG-targeted,
- 31 dev,
- 23 holdout,
- 18 challenge,
- 61 Polish,
- 9 English,
- 2 bilingual.

Every case remains training_exclusion=true.


## Domain expansion

P1 adds evidence-backed coverage for:

- Hatz C81 J1939 bitrate/source address, DM1/DM2 and SPN encoding,
- CAN0 customer/J1939 vs CAN1 diagnostic topology,
- X6 diagnostic pinout and AFDPS sensor wiring,
- fail-closed handling of unknown Clear-DTC protocol,
- MPC555 normal Flash, Shadow separation and silicon revision,
- EEPROM 25C256 and CASE-0002 read-back/boot-block evidence,
- MC33816, L9945, TLE8108EM and smart high-side diagnostics,
- current sense, watchdog/fail-safe, input protection and cold crank,
- live telemetry vs reasoning routing,
- Knowledge vs Graphify vs Vision vs agent handoff routing,
- exact part-number/MCU aliases,
- multi-turn context and cross-language queries.

Scania S6 and Hatz remain regression cases, not the benchmark boundary.


## Independent network sources added to ERS

P1 also expands ERS source provenance before adding corresponding eval cases.

Merged ERS source commit:
81909b30ef18ca2053bd7496d6faeb814d4e9866

New official source packages:

1. NXP TJA1021 Rev. 9
   - LIN physical-layer transceiver,
   - 1–20 kBd,
   - recessive/high termination behavior,
   - TXD dominant timeout,
   - transient/thermal/short-circuit protection.
2. Microchip AN930
   - independent J1939 reference,
   - CAN Extended Frame / 29-bit identifier,
   - PDU1/PDU2,
   - BAM transport,
   - NAME/address claiming.

Each package contains original PDF, official URL, SHA-256 and machine-readable
source facts. Golden cases reference accepted ERS main, not a temporary branch.


## Coverage gate

coverage_policy.json converts desired diversity into hard minimums.

Current gate checks include:
- total cases and per-suite target counts,
- PL/EN/bilingual distribution,
- dev/holdout/challenge distribution,
- CAN/J1939/LIN,
- MCU/NVM/driver/power,
- fail-closed and exact identifiers,
- routing confusion for Knowledge, Graphify, Vision and telemetry,
- multi-turn coverage,
- unique evidence-source count,
- OEM corpus source diversity.

Current result:
- coverage status: PASS,
- unique evidence sources: 44,
- ERS network source facts validated: 8,
- coverage failures: 0.

Passing the coverage gate does not erase declared gaps.


## Declared gaps after P1

- LIN physical-layer coverage is still TJA1021-centric.
- J1939 has generic Microchip evidence and Hatz OEM semantics, but a second OEM
  implementation would improve independence.
- Vision currently evaluates routing, not visual diagnostic accuracy.
- Sensor/schematic/PCB reasoning is shallower than driver/power/network coverage.
- Only two real repair cases exist; additional workshop cases remain mandatory
  before accepting training gains.

## Reproducibility

Golden dataset SHA-256:
1d7a567f222be99199744589c94c38bc58b0b70b3c7e5ca38aaaf45970651fd2

P1 adds query_variants and context_turns to the strict GoldenCase schema, while
preserving training exclusion and evidence requirements.

No SFT, LoRA/QLoRA, continued pretraining, preference optimization, model
download or expensive baseline inference was run in P1.


## Validation

P1 development gate:
- strict dataset/schema validation: PASS,
- ERS provenance validation including ERS-NET source facts: PASS,
- coverage policy: PASS with zero threshold failures,
- focused benchmark/API/Control Center tests: PASS,
- benchmark module compileall: PASS,
- git diff --check: PASS,
- full AI-server pytest regression: PASS, exit code 0.

No production runtime, scheduler configuration or accepted Stage O release was
changed by P1.
