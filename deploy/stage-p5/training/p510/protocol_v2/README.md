# Provenance protocol v2 — acquisition draft, not independent evidence

Status: **BLOCKED_INDEPENDENT_EVIDENCE**, 2026-10-02. This is a reviewable
acquisition packet, not a runnable evaluation. There are **zero certified cases**.
No GPU job, parent tournament, training or final access is authorized.

## Evidence collected

`sources.json` holds eight primary-source records with URLs, access dates, scope,
license limitations and canonical metadata hashes. Six raw HTTP responses were
hashed; two Analog Devices fetches failed although the pages were inspected with
web browsing. Those raw hashes remain null. HTTP hashes do not establish correctness,
immutable availability or permission to redistribute. Source content is not vendored.
A future freeze requires retained permitted snapshots or reviewer-verifiable versions.

`families.json` contains 16 original first-principles causal specifications, two per
domain. Each records topology, competing mechanism, discriminating intervention,
conditional prediction, safety constraints, and likely historical overlap. Sources
support domain background, not the entire authored inference. NASA's record supports
thermal-fatigue background only, not an observed automotive ECU failure. The ADI ADC
article contains device-name inconsistencies; no device-specific numeric limit was
adopted. No fabricated laboratory measurement or simulated trace is included.

Each family is quarantined. Distinct text or ID is not evidence of independence.
Several hypotheses plausibly overlap P5 training mechanisms (brownout, recirculation,
leakage, intermittent joints). All five candidate exposure cells explicitly remain
UNKNOWN. Expanding these 16 seeds into 880 wording/numeric variants is prohibited.

`exposure_ledger.json` binds the existing audit and inventory, all five adapter
config/weight hashes, 31 public dataset records and four metadata-only protected
paths. It records authorship exposure without asserting family exclusion. It does
not open those paths. Unknown base pretraining exposure is outside any attainable
P5-specific exclusion claim. An independent reviewer needs ancestry-to-family
mapping; a trusted custodian must attest protected split exclusion without revealing
payloads to the training/scorer author. No such identity or attestation is available.

## Split and calibration contract

Assign whole source-document families AND causal clusters to one role; the stricter
union wins. A different URL/revision must retain its source-family ID. Cross-role
causal aliases must retain cluster IDs even if different sources describe them.
`split_guard` rejects declared family/cluster collisions and normalized numeric causal
fingerprints. It is a structural guard, not a semantic-independence classifier.
Calibration, train/replay, parent-selection, selection-dev, prefinal and sealed-final
families must be disjoint. Calibration-exposed seed families in this packet cannot
later be promoted into evaluation under new IDs. Quarantine does not erase exposure.

The eight Polish software fixtures exercise positive responses, formatting equivalents,
explicit contradictions, invalid voltage/safety claims and abstention. Their mutations
are software checks, not independent calibration cases or validated semantic paraphrases.
The former v5.1 counterexample (`Nieprawda, że: <positive proposition>`) is retained in
`scorer_v5_1_snapshot.py`. The active v5.2 scorer is deliberately scope-fail-closed:
unapproved negation/quotation/scope markers fail automatic proposition credit and require
review. This fixes the demonstrated false positive without claiming general semantic parsing. Independent Polish answer labels need
negation/scope, real paraphrases, units, plausible wrong causal branches, safety and
insufficient-data cases in all domains; freeze before any candidate outputs. Blinded
adjudication needs a versioned decision and original/scored answer hashes. It is not
available here. Automated inspection is never called human review.

## Precision and fixed gates

Targets remain 240 parent-selection (30/domain), 240 separate selection-dev (30/domain),
and 400 prefinal (50/domain), with at least 60 sufficient and 60 insufficient scenarios
in each. Final is custodian-held, with no payload created or read here. `precision.json`
shows that 45/50 has a Wilson lower bound below .80; 46/50 meets that numerical bound.
At 30/domain category uncertainty is wide. Simultaneous paired inference with 240
families can remain inconclusive for modest gains. No sample-size guarantee of power
is claimed. Freeze the precision plan before outputs, with no adaptive additions to
force significance. One family contributes one independent observation.

`prefinal_metrics` implements the unchanged numerical floors and eight-domain Wilson
checks, recomputing aggregates from strict per-case scores. Even all checks true gives
only `DIAGNOSTIC_ONLY_NO_FINAL_TOKEN`. It cannot issue PASS or open final. A production
gate still needs verified case provenance, unresolved-review rejection, replay/exposure
exclusion, authenticated checkpoint/protocol/scorer/data/raw-output bindings and matched
v1–v4 regressions. Fixed reference loss degradation remains at most 2% on each public
legacy holdout; historical/final-derived scores cannot select parents or checkpoints.

The common five-candidate tournament, generation/base/tokenizer hashes and maximum
checkpoint looks remain unexecuted/unfrozen. Inconclusive parent evidence means **stop
without training**, per the current session instruction. No fallback parent is chosen.
After decisive selection only: one balanced curriculum with 25% reviewed replay, bounded
rank-8 all-language-linear BF16 LoRA without merge; selection-dev alone selects the
checkpoint. A single prefinal failure stops for error analysis. Sealed-final access
requires a hard PASS bound to the exact checkpoint and all protocol/scorer/data/regression
hashes. Old runners are unsuitable because some consume former-final material.

A new launch implementation must acquire the platform GPU lease when required, exclude
Ollama residency and ComfyUI jobs, record same-boot MES/reset baseline and continuously
monitor readable kernel telemetry. Missing telemetry, reset/MES increment or lease loss
must terminate the worker and clean up resources. No GPU was used for this packet, so
no live-launch or post-BIOS health certification is claimed from these software tests.


## Executable simulation proof-of-concept

`simulation_evidence.py` implements eight deterministic first-principles or state-machine
oracles, exactly one existing quarantined causal family per domain (PI01, AS01, AP01, DT01,
VN01, PF01, IE01, ES01). It covers series supply drop, SAR settling, inductive decay,
window-watchdog timing, transmission-line reflection, surface leakage, thermal expansion
thresholding, and off-state backfeed KCL. Each family has a separate invariant plus a
metamorphic/self-check. `simulation_evidence.json` binds the code hash and regenerated
outputs.

This resolves only the narrow question “can these eight mathematical ground truths be
reproduced?”. Every row remains `SIMULATION_VERIFIED_QUARANTINE` with
`p5_exposure_excluded=false`, `real_world_representativeness_certified=false`, and
`eligible_for_parent_selection=false`. Parameter changes are not new causal families.
The PoC is not part of training and cannot issue acceptance, training, or sealed-final
authorization. The 240/240/400 independent pools, exposure review and real-world/domain
review remain outstanding.

## Reproduce without touching protected content

From repository root:

```sh
python3 -m unittest discover -s deploy/stage-p5/training/p510 -p 'test*.py' -v
python3 deploy/stage-p5/training/p510/protocol_v2/validate_protocol.py
python3 deploy/stage-p5/training/p510/preflight.py
```

Both preflights deliberately exit 2. The top-level manifest binds all six JSON files,
the validator, tests and this note. Canonical record hashes use UTF-8 JSON, sorted keys,
compact separators, `ensure_ascii=False`, excluding only `record_sha256` itself.
After authorized edits, `freeze_snapshot.py` regenerates the fixed allowlist manifest
only on the P5.10 branch. Rebinding hashes is not an independence certificate.

The next external dependency is a named independent domain reviewer/custodian who can
assess causal correctness and exposure. Review alone cannot turn this packet into 880
cases: the full disjoint pools, independent calibration and execution/gate implementation
are also outstanding. No final/test/golden content is needed for that preparatory work.
