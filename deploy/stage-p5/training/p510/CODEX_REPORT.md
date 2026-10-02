# Prior P5.10 blocked snapshot (2026-10-01)

Status: **BLOCKED_INDEPENDENT_EVIDENCE**. Candidate status: **NOT_RUN** for v3,
v4-r3, P57 step-008, P58 step-008 and P59 step-008. **No parent selected**;
historical scores do not provide a common independent comparison.

The methodology fixes eight capability domains, separate parent-selection/selection-dev/
prefinal/final roles, proposition-based scoring and paired uncertainty reporting with
legacy v1–v4 regression protection. It requires reviewed source-family independence
before evaluation. Software fixtures are not evidence of model capability.

The regenerated existing audit covers 31 public datasets; four protected dataset paths
remain metadata-only. Template concentration remains material: v4.2 train has 192 rows
but 19 normalized templates. Lexical overlap cannot certify causal independence, and
no audited training/replay material receives automatic approval. The inventory binds
all five adapter candidates and identifies P57 step-008 from eligible historical dev
history only. P58's reserved 70-case final is identified by declared metadata, with
independence and coverage uncertified.

Exact blocker: no provenance-backed independent evaluation exists. No frozen source/
exposure ledger and independent causal-scenario review establish an unused case pool
excluded from candidate training and prior evaluation. Independent scorer calibration
and a validated prefinal gate are also missing. Acquiring and reviewing this evidence
requires a new protocol snapshot; changing a status flag cannot authorize a run.

GPU tournament, training, prefinal and final: **NOT_RUN**. No model run was started.
Final/golden/test/sealed dataset content remains **UNOPENED**, including P58/P59 sealed
final. Protected hashes were copied only from existing manifest metadata, never
recomputed from protected content. Historical artifacts were not modified.

Validation: Python compilation passed for all six snapshot Python files; **37 unit
tests passed** (30 existing scorer/comparator/audit tests plus seven preflight tests).
Audit and inventory regeneration completed. `preflight.py` verified all 11 artifact
bindings and returned the expected **exit 2** with `BLOCKED_INDEPENDENT_EVIDENCE`.
`git diff --check` passed. The artifact manifest binds methodology, audit, inventory,
scorer, comparator, tests, preflight, this report and the task; it is an integrity
snapshot, not a signature or execution authorization. Preflight reads only fixed
repository artifacts and never follows dataset paths embedded in their metadata.

Read-only telemetry on the same boot at 2026-10-01 19:07:56 and 19:08:50 UTC showed
GPU busy **0% → 0%**, VRAM **162,508,800 → 162,508,800 bytes**, and kernel
`MES ring buffer is full` count **0 → 0**. Kernel telemetry was readable (4,723 lines
at both checks). GPU utilization came from AMD sysfs; `rocm-smi` was unavailable.
These checks establish unchanged MES count during finalization, not historical
absence of every possible GPU fault.


# Current session report — 2026-10-02

Status: **BLOCKED_INDEPENDENT_EVIDENCE**. Preparatory evidence acquisition and software
validation completed; methodology has **not** been certified or unlocked.

Critically reviewed CODEX_TASK, methodology, report and the complete parsed audit/inventory
structures. Existing audit covers 31 public datasets and 65 overlap pairs; protected paths
remain metadata-only. The inventory contains 108 historical artifact entries and five
adapter bindings. These artifacts are preserved byte-for-byte; no historical score was
used to select a parent. The old finalization-only task scope is superseded by the user's
resumed authorization, without weakening the evidence requirements.

Added `protocol_v2/`: eight primary-source records (TI, Analog Devices, NASA), 16 authored
first-principles causal-family seeds across eight domains, canonical record hashes,
source/exposure ledger, separate role contracts, fixed thresholds and precision diagnostics.
Six source HTTP responses have byte hashes; two ADI raw fetches failed, recorded explicitly.
Web inspection and metadata hashes do not substitute for archived source evidence or review.
Every seed is quarantined with UNKNOWN exposure against all five adapter lineages. There
are **0 certified independent scenarios**, not 16 accepted evaluation cases. No empirical
measurements or simulated traces were invented. No final/prefinal payload was created.

Added a source/causal-family split guard, Polish software scorer fixtures, adversarial tests,
and numerical prefinal diagnostics. The latter retain .90/.98/.95 global floors, perfect
parsing and 50/domain with Wilson lower bound .80. The reproduced v5.1 unlisted-negation false positive is now fail-closed in the
versioned v5.2 scope contract; the v5.1 implementation is retained as a bound snapshot. The numerical
diagnostic never returns a final-access PASS, even on perfect synthetic software scores.
Automated checks are explicitly not human review or independent scorer calibration.

Validation: **50 unit tests passed**, including 13 new protocol tests; syntax compilation
and JSON parsing/integrity checks passed. Root preflight verifies **21 artifact bindings**
and the ledger's historical hashes; both preflights deliberately return **exit 2** with
BLOCKED_INDEPENDENT_EVIDENCE. `git diff --check` passed. `freeze_snapshot.py` regenerates
the fixed manifest only on the authorized P5.10 branch. No GPU was used, so no resource
lease or live model telemetry was needed; no new GPU health claim is made. Any future
launch still requires Ollama/ComfyUI exclusion, lease where required, MES/reset baseline,
live kernel telemetry and abort/cleanup on errors or telemetry loss.

Minimal next external dependency: independent technical reviewer/custodian access to
establish correctness, causal-family equivalence and P5 exposure exclusion, including a
protected-split exclusion attestation without disclosing payloads. This alone is not a
sufficient launch condition: acquisition of the complete disjoint 240/240/400 case pools,
independent Polish scorer calibration/adjudication, immutable source snapshots and frozen
base/tokenizer/generation/checkpoint-selection contracts plus the execution/final gate
remain outstanding. Automatically generating variants or relabelling review would not
resolve these blockers. Calibration-exposed seeds cannot become evaluation families.

Exact execution status: five-candidate parent tournament **NOT_RUN** (v3, v4-r3, P57/P58/P59
step-008); selected parent **NONE**; curriculum/training **NOT_RUN**; prefinal and v1–v4
model regressions **NOT_RUN**; sealed final **UNOPENED**, including all P58/P59 sealed data
and all protected test/golden/final content. No LoRA/base merge, historical artifact deletion,
new corrective stage or merge to main. Changes are confined to this P5.10 worktree/branch.


### 2026-10-02 executable ground-truth PoC

Added `protocol_v2/simulation_evidence.py` and a generated, code-hash-bound snapshot for
eight distinct existing causal families, exactly one per domain. All eight mathematical
oracles and their independent metamorphic checks pass. The status is deliberately
`SIMULATION_VERIFIED_QUARANTINE`: P5 exposure exclusion remains false, real-world
representativeness certification remains false, and eligibility for parent selection is
false. No parameter sweep is counted as additional independent families.

The active scorer is now `case-rubric-v5.2-scope-fail-closed`; the demonstrated v5.1
negation/scope false positive is rejected/escalated to review and the historical v5.1 code
is preserved in `protocol_v2/scorer_v5_1_snapshot.py`. This does not replace independent
Polish scorer calibration.

This PoC removes only the narrow blocker “no executable deterministic ground-truth
mechanism exists”. It does not satisfy causal/exposure independence, real-world
representativeness, complete 240/240/400 disjoint case pools, independent scorer review,
custodian exclusion, frozen execution bindings, or the parent tournament. GPU training
therefore remains NOT_RUN and sealed final remains UNOPENED.

## 2026-10-02 automotive-first acquisition continuation

Prepared the next P5.10 acquisition tranche before any further Qwen3.8 electronics training. It contains 32 new primary technical source families from 13 vendors and 40 authored diagnostic causal-family candidates, balanced at 5 candidates for each of the 8 fixed domains. Retrieval disposition is 17 fetched/hash-bound responses and 15 raw-fetch failures recorded without invented hashes. Twenty candidates carry explicit possible-overlap review holds.

Added fail-closed acquisition provenance validation and adversarial tests covering duplicate source identity, URL aliases, renamed causal families, source rebinding, fabricated hash/review/exposure claims, role promotion, transitive overlap holds and unbound sources.

Validation after reconciliation: 77/77 unit tests PASS. Direct protocol validation remains intentionally BLOCKED_INDEPENDENT_EVIDENCE with 0 certified scenarios, parent NONE and sealed final UNOPENED.

No GPU/model inference/training/tournament ran. This tranche improves breadth—especially automotive power, sensors, drivers, CAN/LIN, PCB/environmental faults and ECU isolation—but does not replace independent technical review, P5 exposure exclusion, the full 240/240/400 disjoint pools, independent Polish scorer calibration or custodian attestation.
