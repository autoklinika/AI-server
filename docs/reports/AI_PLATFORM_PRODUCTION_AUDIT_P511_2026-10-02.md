# AI Platform — production audit: Qwen3.8 + P5.11

Date: 2026-10-02

## Scope

This audit reconciles GitHub history, the live AI Platform runtime, P5 training artifacts,
and the production model contract before the next Stage O production gate.

The target production reasoning model is Qwen3.8 27B with the accepted P5.11
`automotive-specialization-v1` LoRA mounted at inference time. The LoRA remains a
separate adapter; it is not merged into the Qwen3.8 base weights.

## Git / branch decisions

- Current production-line source before this audit: `main` at `ec24144`.
- P5.11 is integrated onto a fresh branch descended from current `main`.
- `stage-p5.10/eval-foundation-v1` is not merged wholesale. It is a large,
  divergent evaluation/acquisition development lineage and is not a runtime
  dependency of P5.11.
- `fix/p5-amdgpu-mes-stability` is not merged wholesale. It contains divergent
  historical training changes; current runtime has no new MES/GPU-reset evidence.
- The useful Stage K RAG restore retry from PR #141 is included in the audited branch.
- The old Stage J3 FK flush fix from PR #74 is already present in current `main`
  through later accepted work and must not be merged again.

## P5.11 training evidence

Training artifact:
`/srv/ai-data/training/p5/adapters/automotive-specialization-v1/current`

Resolved run:
`automotive-v1-20261002T145342Z`

Evidence:

- base: Qwen3.8 27B BF16 buffered checkpoint;
- parent training state: `electronics-foundation-v3/current`;
- LoRA rank: 8; alpha: 16; dropout: 0;
- training: 244 microsteps / 64 optimizer steps;
- source adapter tensor count: 992;
- source adapter SHA-256:
  `46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb`;
- manifest status: `TRAINING_INTEGRITY_PASS_QUALITY_PENDING`.

Acceptance boundary is deliberate: training integrity is PASS, but final independent
automotive quality/regression acceptance remains pending. Productionizing the adapter
does not re-label the training as independently quality-accepted.

## Runtime adapter

Ollama cannot directly import this Qwen3.8 PEFT safetensors adapter with the current
supported safetensors conversion path. The audited runtime therefore converts the
standalone LoRA to GGUF and mounts it with Ollama `ADAPTER`.

Pinned conversion inputs:

- llama.cpp: `34af94cd9ab277632e27caeec2d41de2fd091b31`;
- training image:
  `sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8`;
- source LoRA SHA-256: `46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb`;
- runtime GGUF SHA-256:
  `bb4966fa3d8a5a71a7e21b159235cc5e00f0282ff6c50ce6c1c41eca2dbba8a7`.

The Qwen3.8 linear-attention output projection requires a column permutation.
For LoRA W = B @ A, the audited converter applies this permutation only to A.
A numerical equivalence test produced maximum absolute error 0.0.

## Runtime acceptance

Stable Ollama model contract:
`qwen3.8:27b-p4-64k-gpu-p511`

Runtime smoke proved that Ollama starts `llama-server` with the P5.11 adapter as an
explicit `--lora` layer whose blob digest is the runtime GGUF digest above. The model
generated a coherent Polish ECU diagnostic answer while fully resident on GPU, with
no new MES reset, GPUVM fault, or ring timeout observed during the smoke.

The Stage O production gate is fail-closed: it verifies the stable model name and the
expected adapter blob before cutover and again after preload. Release metadata records
both source-adapter and runtime-adapter digests.

## Release acceptance gates

Before production finalization the candidate must pass:

1. full pytest suite;
2. immutable Stage O release build and metadata validation;
3. GitHub CI for the exact candidate SHA;
4. Stage O preflight, cutover smoke, rollback smoke, reactivation smoke and finalize;
5. post-cutover verification that `reasoning-main` resolves to the adapted Qwen3.8 model.
