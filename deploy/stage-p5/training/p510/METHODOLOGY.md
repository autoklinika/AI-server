# P5.10 methodology and fail-closed disposition

Status: **BLOCKED_INDEPENDENT_EVIDENCE**. No parent is selected. No GPU tournament,
training, prefinal or final evaluation is authorized by these artifacts. This supersedes
the initial document's unsupported v3 parent choice and 64-case selection proposal.

## Evidence and roles

`audit.json` inventories all 31 public JSONL datasets under the P5 training and relevant
benchmark roots. Four protected dataset paths are metadata-only. `evidence_inventory.json`
records manifests, aggregate historical scores, candidate configuration/weight hashes and
P57 dev selection evidence. Final/golden/test/sealed paths, symlink targets and known
former-final output aliases are excluded before opening. Historical files are unchanged.
Path protection is defense in depth: a renamed or embedded protected dataset still requires
provenance review. Absence of a result file does not establish non-exposure.

None of the audited files is certified as a new independent evaluation. Public holdouts/dev
are already exposed; train material cannot evaluate descendants trained on it. No source
ledger establishes an unused, confirmed case pool. Automotive curriculum v2 explicitly
requires confirmed unbenchmarked cases before serious calibration. Synthetic wording changes
cannot repair that absence. The audit measures lexical dependence, not semantic independence;
causal topology, mechanism, intervention and observation must also be reviewed.

P58's 70-case final is the strongest *reserved candidate identified by metadata*, not a
certified best final. P59 reuses its declared hash. No P58/P59 final result file was found at
the expected locations. Its content stays unopened; its independence, coverage and power
remain unknown. P57's former final is revealed according to the P58 manifest and cannot
become new selection evidence. Automotive golden remains protected. Declared final hashes
are copied from manifests, never recomputed by reading protected content.

## Fixed capability taxonomy

Eight non-overlapping primary domains; cross-cutting tags describe evidence sufficiency,
channel comparisons, numeric reasoning, thermal/vibration triggers and measurement safety:

1. `power_integrity`: supply, ground, regulation, resets and transient load response.
2. `analog_sensor_chain`: sensor excitation, signal conditioning, ADC/reference faults.
3. `actuator_power_stage`: low/high-side drivers, gate drive, inductive loads and protection.
4. `digital_timing_reset`: clocks, logic levels, reset sequencing and watchdog evidence.
5. `vehicle_network`: physical-layer CAN/LIN wiring, termination, wake and communication.
6. `pcb_fault_localization`: shorts, leakage, opens, connector/contact and interconnect faults.
7. `intermittent_environmental`: controlled thermal/vibration localization and causal timing.
8. `ecu_system_isolation`: ECU versus harness/load faults, bench/vehicle boundaries and verification.

Abstention is evaluated within every domain, not treated as a replacement for domain coverage.
The duplicated good/bad-channel categories in the original design are removed.

## Acquisition contract (not fabricated datasets)

Freeze source IDs, acquisition dates, consent/license, exposure ledger, causal scenario IDs,
reviewer decisions and record hashes before generating candidate outputs. Use independently
confirmed cases or independently reviewed first-principles/simulation scenarios, with a
source ledger showing exclusion from all candidate training and prior evaluation. Human
review of case correctness and causal independence is still missing. Do not claim unknown
base-model pretraining exposure is excluded; the attainable claim concerns P5 adaptation.

Allocate entire causal scenario/source families to one role. No numeric/ID/temperature
variants across roles. Target 240 parent-selection scenarios (30/domain), a separate 240
checkpoint selection-dev scenarios, and 400 prefinal scenarios (50/domain). Include at
least 60 insufficient-evidence and 60 sufficient-evidence scenarios in each evaluation.
These are acquisition targets, not automatic power certificates. Parent selection has no
binary category floor: report estimates and intervals. Plan a power/precision analysis
before freezing the protocol; inability to distinguish adapters is a valid outcome.

Prefinal uses fixed global diagnostic/measurement/prediction point floors of .90, no-guessing
.98, abstention .95, sufficient-answer rate .95, and raw/final parse 1.0. Category acceptance
requires at least 50 independent scenarios and a Wilson lower bound >= .80 for each of the
three core dimensions. Fifty cases permit 2-point increments but still have substantial
uncertainty; sample count alone is not evidence of precision. Do not reduce these thresholds
after seeing outputs. Prefinal needs a separate implemented, validated gate before any run.
Final is a separately locked source-family split. No protected content is used to tune this
contract. A trusted custodian must establish split exclusion without exposing final content.
If that cannot be done, final readiness remains blocked.

## Scoring, calibration and comparisons

`score_quality_benchmark_v5.py` v5.1 replaces unsafe category-keyword/embedding overrides
with case-specific proposition rubrics: all required groups, alternative equivalent phrases,
explicit contradictory claims, measurement setup, and conditional prediction branches.
It strictly checks output field types, one result per case, and boolean abstention. Five
separate dimensions are reported, including over-abstention on sufficient evidence. Missing
abstention samples produce null, not a perfect rate. Guessing is checked across all fields.

Regex proposition matching is a limited semantic approximation, not a technical truth oracle.
It can miss unlisted equivalents and negation/scope, and can reward an incomplete rubric.
Unmatched answers require blinded adjudication under the frozen rubric. Arbitrary embedding
similarity cannot override causal contradictions. No acceptance is authorized by this scorer.
Thirty self-authored software fixtures test positive/negative/equivalent answers and integrity;
they are not new selection data or sufficient domain calibration. Before use, independently
reviewed calibration cases must cover all eight domains, Polish production responses,
negation, plausible wrong alternatives, numeric units and safety; freeze rubric/scorer hashes.

`compare_quality_v5.py` recomputes aggregates from validated boolean case scores, verifies
identical case/scenario/category/abstention and dataset/scorer hashes, then reports paired
bootstrap intervals for the equal-weight five-dimension composite and each dimension.
Intervals use 20,000 fixed-seed resamples, with Bonferroni alpha=.05/(10 pairs * 6 statistics)
for the five-candidate tournament. Evidence of improvement needs composite lower bound >0,
all dimension lower bounds >=-.02, and absolute safeguards. Approximate bootstrap intervals,
especially all ties or rare events, do not prove equivalence. Category results are descriptive.
The comparison tool deliberately produces no PASS token and exits 2: provenance, calibration,
legacy regressions and a real launch gate are absent. More than five candidates or repeated
checkpoint looks require a separately frozen multiplicity plan before scoring.

## Tournament and consolidated run contract

Inventory all five required candidates. P57 step-008 is justified by eligible dev history,
not former-final results. Pin the resolved v3 directory and every adapter hash; `current`
may move. Use identical base hash, inference contract, tokenizer, generation settings,
context limit, prompts and scorer for all candidates. Capture raw outputs and per-case
metrics plus matched v1–v4 regression evaluations. No final-derived regression is allowed
for this tournament. Historical non-common evaluations cannot establish a winner.

Preserve existing v1–v4 protection: at most 2% relative token-weighted loss increase on
each public legacy holdout against the fixed comparison reference, and retain existing
quality safeguards. Loss complements causal quality; it cannot replace it. Inconclusive
measured results favor the simplest non-regressed eligible lineage; without a valid common
evaluation, select nobody, including v3.

Build one curriculum only after roles and leakage reviews are complete. Reserve 25% replay
from reviewed v1–v4 training rows, balance new material across domains, and include explicit
insufficient-data behavior in each domain. Cap each reviewed causal scenario at one example
per epoch. Template-heavy v4.1/v4.2/P57–P59 packs are not bulk sources. Any exceptional reuse
needs a row-level justification and exclusion from all evaluation families. No current file
has automatic train/replay approval; do not silently promote a lexical audit into certification.

Retain rank-8, all-language-linear BF16 LoRA, frozen Qwen base and no merge. All five adapter
configs support rank 8 with the same target-module set. Before starting one bounded run, lock
parent/base/curriculum hashes, seed, learning rate, context length, optimizer, token budget,
checkpoint interval, maximum checkpoints and multiplicity-aware selection rule in a run
manifest. These numerical training choices remain pending measured parent and curriculum;
copying P59's tiny thermal schedule would recreate the problem. Select checkpoints using
selection-dev only. Run prefinal once for the selected checkpoint plus v1–v4 regressions.
Failure stops for error analysis, never auto-creates another corrective stage. Final access
requires a PASS bound to that checkpoint, data/scorer/protocol hashes and regression outputs.

Before any future GPU launch: verified dataset integrity and calibration, a clean resource
lease, no Ollama resident-model conflict, readable kernel telemetry, MES baseline and live
monitoring, abort/cleanup on new MES errors or missing telemetry. Existing runners are not
invoked or edited; their legacy final-reading paths are unsuitable for this tournament.

## Reproduction of the blocked disposition

From the repository root:

```sh
python3 deploy/stage-p5/training/p510/audit_dataset_quality.py --root . --output deploy/stage-p5/training/p510/audit.json
python3 deploy/stage-p5/training/p510/inventory_evidence.py --repo . --output deploy/stage-p5/training/p510/evidence_inventory.json
python3 -m unittest discover -s deploy/stage-p5/training/p510 -p test_foundation.py -v
python3 deploy/stage-p5/training/p510/preflight.py
```

Preflight verifies locked artifact hashes and always exits 2 for this blocked snapshot.
It cannot launch a GPU job or unlock final content. `artifact_manifest.json` binds the
snapshot, not an executable training authorization. Completing the missing acquisition,
review and calibration requires a new reviewed protocol snapshot, not flipping a status bit.
