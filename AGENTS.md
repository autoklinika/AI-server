# AI Platform / Resource Manager — Codex instructions

These rules apply to GitHub/Codex Cloud development. Work in a dedicated feature branch and open a pull request. Do not merge, deploy, start services, or connect to live hardware as part of code development.

## Ownership and safety invariants
- The existing Resource Manager is the **only** coordinator of managed AI workloads. Never introduce a second scheduler, daemon, or competing GPU controller.
- Keep existing public API contracts and single-GPU behavior backward-compatible unless explicitly scoped otherwise.
- Dedicated VRAM belongs to each individual GPU. AMD UMA and CPU allocations share host RAM; do not double-charge or pool independent RTX memories.
- Bind device selection to stable hardware identity, backend and device generation. CUDA ordinals are not stable identities.
- All reservations must be atomic across their entire bundle and owned by a generation-checked lease. No partial grant, double release or stale-owner release.
- Cancellation, lost heartbeats, request timeout, process termination, or a free-VRAM observation do not prove GPU quiescence. On uncertainty, preserve ownership/quarantine until trusted verification.
- Isolate GPU-specific failures without inventing isolation when a known shared fault domain exists.
- A P1 resource **fit** result is **not execution authorization**; only a future P2 atomic commit from existing RM can grant execution.
- Never weaken authentication, expose secrets in tests or logs, run arbitrary commands from model-supplied input, or access private production hosts in cloud CI.

## Project-specific constraints
- The second RTX's model and memory capacity are **not confirmed**. Treat 48 GiB only as a configurable test fixture.
- Earlier N1–N5 experimental branches are reference material, not production-ready code. Do not wholesale merge them.
- Do not import/copy third-party GPUStack/LocalAI/Lemonade code without verifying exact upstream revision, file license, attribution and test provenance.
- Current stage: P1 pure offline calculator; next stage P2 must begin with observation-only/shadow integration. Do not enable hardware admission, model unloading, deployment, or production flags in that PR.

## Required workflow
1. Write a small scoped change with a clear design and backwards-compatibility statement.
2. Add deterministic CPU-only tests, including failure cases and regressions found by independent review.
3. Run the relevant tests plus Ruff and strict mypy checks. In CI, report actual pass/fail status; no fabricated success.
4. Open a PR. Do not merge before CI and an independent code review. Security-critical changes require explicit approval.
5. Record what is tested and what remains NOT_RUN, particularly GPU eGPU/hotplug, CUDA/ROCm, and actual recovery.
6. Never include tokens, private IP addresses, personal files or production configuration dumps in the public repository.
