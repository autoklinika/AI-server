# P5.10 automotive electronics acquisition tranche — 2026-10-02

Status: **QUARANTINE / NOT_CERTIFIED**. This packet is preparatory evidence for the fail-closed P5.10 evaluation gate. It is not training data and does not authorize GPU work or parent selection.

## Result

- 32 new primary technical source families from 13 vendors.
- 17 source responses fetched and SHA-256 bound.
- 15 raw fetches failed and remain explicitly marked with no invented payload hash.
- 40 authored automotive-first diagnostic causal-family candidates.
- Exactly 5 candidates in each of the 8 existing domains.
- 20 candidates carry explicit possible-overlap review holds.
- 0 candidates are certified and 0 are assigned to evaluation roles.
- All five adapter-lineage exposure states remain UNKNOWN.

## Automotive emphasis

The tranche is centered on ECU diagnostics: 12/24 V battery front ends, transient protection, regulators and supervisors; SENT/PSI5/VR/current-sense/ADC chains; smart high-side and H-bridge drivers; watchdog/reset/fail-safe state machines; CAN/LIN wake and physical-layer faults; PCB thermal, contamination, strain and moisture mechanisms; and ECU/harness backfeed and isolation.

Each candidate records a competing mechanism, a discriminating measurement or intervention, a conditional prediction, safety constraints, source provenance, and sufficient/insufficient evidence potential. These are authored diagnostic hypotheses, not copied vendor cases.

## Provenance and review disposition

Fetched source bytes are retained only in the local acquisition cache used for verification and are not vendored into the repository. Public technical documentation does not imply redistribution permission. Failed raw retrievals preserve URL/locator and failure reason without claiming an archive or hash.

Automated Codex/ChatGPT work is explicitly not treated as independent technical review, scorer calibration, or custodian evidence. Possible overlap is handled conservatively rather than counted as independence.

## Remaining gate

Before parent comparison or further Qwen3.8 training can resume, P5.10 still requires independently reviewed and exposure-cleared disjoint pools of 240 parent-selection + 240 selection-dev + 400 prefinal scenarios, independent Polish scorer calibration/adjudication, custodian split-exclusion attestation, and frozen execution/model bindings.

Validation for this tranche: 77/77 unit tests pass. The protocol validator deliberately returns exit 2 with BLOCKED_INDEPENDENT_EVIDENCE, certified_scenarios=0, parent=null, and sealed_final=UNOPENED.
