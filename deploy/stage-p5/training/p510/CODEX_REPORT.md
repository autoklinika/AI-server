# P5.10 blocked snapshot

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
