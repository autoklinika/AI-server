# AI Platform — Stage P5.1 Automotive Curriculum Seed

Date: 2026-09-29  
Base: P5.0 commit ce8f240  
Branch: stage-p5.1/automotive-curriculum-v1

## Objective

Start the real automotive-training data path for the selected Qwen3.8-27B base without contaminating the existing benchmark and without treating downloaded OEM documentation as automatically trainable material.

P5.1 in this revision is a data-foundation and training-path smoke gate, not a deployable automotive adapter.

## Contamination and licensing boundary

The existing automotive golden dataset contains 72 benchmark-only records and every record has training_exclusion=true.

Direct case-family reuse was checked before creating the training seed:
- CASE-0001 is referenced by 5 golden records.
- CASE-0002 is referenced by 11 golden records.

Therefore CASE-0001 and CASE-0002 are reserved as evaluation/regression material and are not copied into the P5.1 training seed.

The Automotive Semiconductor Corpus v0 and the added LIN/J1939 OEM sources are marked retrieval_reference_only_pending_license_review. They remain available to Knowledge/RAG and evaluation, but are explicitly prohibited from this training export.

## Curriculum seed v1

Generated artifact:
- deploy/stage-p5/training/fixtures/automotive_curriculum_seed_v1.jsonl
- records: 20
- language: Polish
- source kind: project_owned_synthetic
- direct benchmark case reuse: 0
- direct golden-record reuse: 0
- OEM retrieval-only training records: 0
- dataset SHA-256: 367920c9e9e4a2318aac8a722c48b708de193cd62a5718a993ac8252e9d52659
- golden SHA-256 checked by gate: 1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf

The seed teaches diagnostic process rather than exact OEM facts. Every answer follows the reasoning contract:
FACTS -> excluded evidence -> hypotheses -> discriminating test -> expected results -> interpretation -> next action -> confidence.

Covered seed categories include:
- insufficient evidence / no parts-cannon behavior,
- high-side and low-side fault isolation,
- shared sensor-reference rails,
- CAN and LIN physical-layer isolation,
- thermal/intermittent ECU faults,
- current-sense validation,
- open-load vs short separation,
- watchdog/reset diagnosis,
- safe bench wake-up uncertainty,
- clone compatibility reasoning,
- read-back before special-memory speculation,
- EEPROM-wide-difference handling,
- bench-pass vs vehicle verification,
- crank/power integrity,
- schematic net tracing,
- PWM measurement,
- resisting unsupported ECU replacement.

## Dataset gate

deploy/stage-p5/training/prepare_curriculum_seed_v1.py is deterministic and fail-closed.

It rejects:
- golden data without training_exclusion=true,
- missing CASE-0001/CASE-0002 benchmark reservations,
- exact normalized user/answer reuse from golden,
- excessive 8-token shingle similarity,
- non-approved source classes in the generated seed.

Focused tests:
- curriculum reproducibility: PASS
- no benchmark/OEM training-source leakage: PASS
- py_compile: PASS
- git diff --check: PASS

## Training runner

deploy/stage-p5/training/run_curriculum_calibration_v1.sh reuses the P5.0 bounded BF16 streaming loader and UMA-aware safety policy.

Default calibration configuration:
- Qwen3.8-27B BF16
- LoRA r=8
- learning rate 1e-4
- max sequence length 512
- 100 steps only when a sufficiently sized curriculum is approved
- Docker accounting ceiling 48 GiB
- host MemAvailable watchdog 8 GiB
- no resident Ollama model allowed
- no direct provider/runtime bypass

The shared trainer now accepts an explicit purpose string so P5.0 feasibility artifacts and P5.1 training artifacts remain semantically distinct.

## P5.1 seed smoke — PASS

Run ID:
p51-seed-smoke-20260929T2125Z

This was intentionally limited to 8 steps. It validates the new dataset/training plumbing; it is not the mandatory 100–300 step serious calibration and the resulting adapter is non-deployable.

Results:
- manifest status: PASS
- purpose: P5.1 contamination-safe automotive curriculum calibration seed; non-deployable
- model load: PASS
- model load time: 15.509 s
- LoRA target modules: 496
- trainable parameters: 58,363,904
- steps: 8/8
- training time: 168.515 s
- mean step time: 21.063 s
- throughput: 21.446 tokens/s
- peak VRAM allocated: 57,481,204,736 bytes
- peak VRAM reserved: 58,057,555,968 bytes
- adapter tensor count: 992
- adapter SHA-256: 8a5d387510027e1f7f93a2733951428aa426cae6b46611496364c82fdadfdcd1

Step losses:
1. 1.208576
2. 1.224962
3. 1.355535
4. 1.153054
5. 1.221677
6. 1.361191
7. 1.387174
8. 1.219733

No trend conclusion is drawn from eight heterogeneous seed examples; this run is an execution smoke only.

Post-run:
- GPU busy: 0%
- VRAM used: ~163 MiB
- host MemAvailable: ~27 GiB
- MES ring-full recurrence: 0
- adapter SHA verified against manifest: PASS

## Gate decision

P5.1 DATA FOUNDATION / SEED SMOKE = PASS.

The 20-record seed is too small for a meaningful 100–300 step calibration without excessive repetition. The next P5.1 gate is corpus expansion with the same contamination/licensing rules. Serious calibration starts only after the curriculum is large/diverse enough to make the measured 100–300 steps informative.

The benchmark remains untouched and CASE-0001/CASE-0002 remain reserved.
