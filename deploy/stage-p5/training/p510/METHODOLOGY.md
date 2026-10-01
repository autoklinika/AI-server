# P5.10 — Electronics tuning methodology reset

## Why this stage exists

P5.6–P5.9 exposed useful failure modes, but later datasets became too template-heavy and the
quality gates became too sensitive to tiny category slices. P5.10 resets the methodology before
any further expensive Qwen3.8 27B training.

The model parent for the consolidated run is:
`/srv/ai-data/training/p5/adapters/electronics-foundation-v3/current`

P5.6–P5.9 artifacts remain evidence/regression material; they are not the model lineage for P5.10.

## External guidance used

- Keep train, validation and final test roles separate.
- Use representative task-specific evals and an untouched holdout.
- Measure retention after PEFT updates.
- Prefer diverse examples over repeated paraphrases.
- Treat point estimates on small samples as uncertain; report confidence intervals.

References are recorded in the P5.10 commit/PR notes.

## Dataset contract

Four roles are fixed before training:

1. **train** — one consolidated, semantically diverse curriculum.
2. **selection-dev** — 64 cases (8 capability families x 8), used for checkpoint selection only.
   It has no per-category binary PASS/FAIL because one case is 12.5 percentage points.
3. **prefinal-dev** — 160 cases (8 x 20), run only for the selected checkpoint.
   Per-category gates are allowed here because one case is at most 5 percentage points.
4. **sealed-final** — untouched after its hash is locked; opened only after prefinal PASS.

No record or normalized/near-duplicate prompt may cross train/dev/final boundaries.

## Capability families

- schematic_symptom_measurements
- good_bad_channels
- numeric_waveform
- thermal_intermittent
- pcb_short
- good_bad_channel_comparison
- insufficient_data
- borderline_sufficient

Each family must contain multiple circuit topologies, failure mechanisms and evidence patterns.
Changing IDs, temperatures, voltages or component names does not count as a new scenario.

## Evaluation contract

The scorer and the gate are separate.

The scorer produces per-case dimensions, category metrics, and 95% confidence intervals. It does
not decide whether the model is accepted.

Checkpoint selection uses the same cases for parent and candidate and compares them pairwise.
A checkpoint must improve the targeted composite score without a material regression in protected
capabilities. Selection is not based on a single category miss.

The prefinal gate checks:
- JSON/contract parse integrity,
- no-guessing and abstention behavior,
- targeted diagnostic/measurement/prediction quality,
- category floors only where sample size is sufficient,
- regression versus the fixed parent on legacy holdouts.

Only a prefinal PASS is allowed to open the sealed final set.

## Training contract

- one consolidated run from electronics-foundation-v3/current;
- LoRA remains PEFT, base Qwen weights remain frozen;
- replay comes from high-diversity v1–v4 material, not template-heavy v4.1/v4.2/P58/P59 packs;
- checkpointing is bounded and selection-driven;
- no new corrective stage is created from a failed tiny slice;
- a failed run returns to data/error analysis, not another prompt-template patch.
