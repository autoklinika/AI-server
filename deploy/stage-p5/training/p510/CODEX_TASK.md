# Codex task: finish P5 training methodology correctly

You are working in /home/harrypotter/agent-worktrees/stage-p59 on branch
stage-p5.10/eval-foundation-v1.

Goal: stop the P5.6–P5.9 corrective-stage loop and build one defensible methodology that can
select the best existing adapter parent and perform one consolidated electronics/automotive
diagnostic LoRA improvement run for Qwen3.8 27B.

Do not assume electronics-foundation-v3/current is the parent. Compare candidates first.

Important context already established:
- P5.8/P5.9 were technically stable; GPU/MES is not the current blocker.
- P59 best checkpoint was step-008.
- Later datasets became template-heavy.
- Examples:
  v4_2 train: 192 rows but ~19 normalized templates;
  p58 train: 80 rows / ~35 normalized templates;
  p59 dev: 28 rows / ~7 normalized templates.
- score_quality_benchmark_v4 used global 0.90 gates and category floor 0.80 from only 5 cases.
  A 6-case category changes 16.7 percentage points per example.
- P59 thermal dev was 89.3/92.9/89.3 diagnostic/measurement/prediction with 100% no-guessing
  and abstention; broad dev was 100/97.6/95.2 with 100% no-guessing/abstention.
- Some v4 failures are plausible technical answers that differ from a single reference, so raw
  semantic similarity must not be the sole acceptance criterion.
- P58/P59 sealed finals were not opened by the failed runs.

Existing P5.10 foundation:
- METHODOLOGY.md
- audit_dataset_quality.py
- score_quality_benchmark_v5.py (scorer only; reports confidence intervals)
- compare_quality_v5.py (paired comparison gate)
Review these critically; change them if needed. Do not preserve a flawed design just because it exists.

Candidate adapters to benchmark at minimum:
1. /srv/ai-data/training/p5/adapters/electronics-foundation-v3/current
2. /srv/ai-data/training/p5/checkpoints/electronics-v4-measurement-r3-20261001
3. best valid P57 checkpoint from existing state/results
4. /srv/ai-data/training/p5/checkpoints/p58-p58-seed1-20261001/step-008
5. /srv/ai-data/training/p5/checkpoints/p59-p59-seed1-20261001/step-008

Hard rules:
- Do not merge LoRA into the Qwen base.
- Do not modify or delete historical artifacts.
- Do not open any sealed-final dataset before its prefinal gate passes.
- Do not weaken thresholds simply to obtain PASS.
- Do not use final/test data for training, checkpoint selection, scorer calibration, threshold tuning,
  or parent selection.
- Do not call numerically varied copies of one template independent evidence.
- Do not create another tiny corrective P5.x stage from a handful of failed examples.
- Preserve legacy v1–v4 regression protection.
- Keep MES monitoring/fail-closed behavior.
- Commit coherent changes on the current branch only. Do not merge to main.

Required work:

A. AUDIT
1. Inspect all P5 datasets, manifests, gates and existing benchmark outputs from electronics v1
   through P59.
2. Produce a machine-readable audit report covering:
   exact duplicates, normalized-template duplicates, cross-split leakage, category sizes,
   semantic/template concentration, and which datasets are safe for train/replay/dev/final roles.
3. Identify actual best sealed/unused material and do not accidentally contaminate it.

B. EVALUATION DESIGN
4. Define a fixed capability taxonomy appropriate to practical electronics/ECU diagnosis.
5. Build a new diverse parent-selection eval that is not a set of ID/temperature/value paraphrases.
   It must have enough independent scenarios that one example cannot swing a category gate wildly.
6. Keep selection-dev separate from prefinal and sealed final.
7. Scoring must separate:
   diagnostic model, discriminating measurement, predicted observation/result, no-guessing,
   and abstention.
8. Improve scoring so technically equivalent answers are not rejected solely for wording.
   Use deterministic structural checks plus semantic/concept checks; document limitations.
9. Report uncertainty. Use paired candidate-vs-parent comparison on the same cases and confidence
   intervals. Binary per-category gates are allowed only when sample size is defensible.
10. Add calibration/unit tests with positive, negative and technically-equivalent paraphrases.

C. PARENT TOURNAMENT
11. Run the same parent-selection eval against all candidate adapters above.
12. Produce a comparison artifact with raw metrics, paired comparisons and regression metrics.
13. Select a parent only from measured evidence. If evidence is inconclusive, state so and prefer
    the simplest/non-regressed candidate rather than inventing a winner.

D. CONSOLIDATED TRAINING PLAN / RUN
14. Build one consolidated high-diversity training curriculum from safe material. Do not use the
    template-heavy corrective packs as bulk data. Reuse individual examples only if independently
    justified and non-leaking.
15. Include replay protection for retained capabilities and explicit insufficient-data behavior.
16. Use bounded checkpointed LoRA from the measured parent. Do not change LoRA architecture without
    evidence; current rank-8/all-language-linear BF16 setup is acceptable if audit supports it.
17. Selection checkpoints must use selection-dev only.
18. Run a large prefinal on the selected checkpoint plus v1–v4 regressions.
19. Open sealed final only after prefinal PASS.
20. If prefinal fails, stop and produce an error analysis; do not auto-create a new corrective stage.

E. QUALITY / REPO
21. Add reproducible manifests/hashes and fail-closed validation.
22. Run syntax/unit/data-integrity tests and git diff --check.
23. Commit and push coherent changes to stage-p5.10/eval-foundation-v1.
24. Leave a concise final report in deploy/stage-p5/training/p510/CODEX_REPORT.md stating:
    - methodology,
    - audit findings,
    - candidate comparison,
    - selected parent and why,
    - run status/results if executed,
    - exact blockers if any,
    - whether sealed final remains unopened.

You may use the server/GPU and existing containers, but keep Ollama resident-model conflicts and
MES monitoring in mind. Prefer correctness over speed. Do not fabricate PASS.

## Finalization scope (2026-10-01)

The user's latest instruction supersedes execution of the original tournament/training
work: finalize only the blocked snapshot, run software/integrity checks, verify GPU idle
and unchanged MES count, then commit and push this branch. No new audit from scratch,
protected-content access, tournament or training is authorized. Regeneration of the
existing public audit and metadata inventory is requested for reproducibility.
