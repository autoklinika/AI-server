# AI Platform Stage I — DEV gate — 2026-09-23

## Status

**DEV GATE PASS / PRODUCTION NOT STARTED.**

Stage I is the P2 observability and operations-hardening step inserted after completed Stage H and before Knowledge Service. The candidate adds a bounded metadata-only Platform observability contract without changing scheduling, providers, WVC control policy, models, GPU policy or public network exposure.

## Implemented contract

- `GET /api/v1/observability` under the existing Platform API auth boundary;
- request totals/in-flight/status/error classes and latency summary;
- Resource Manager admission/queue state and active lease count;
- GPU residency/cleanup summary;
- bounded recent-job aggregation and queue/execution timing;
- logical provider/model/node and process RSS/CPU;
- terminal history retention metadata;
- additive lease/GPU components in `/api/v1/health`;
- structured Platform request completion log with normalized route template.

## Privacy and review findings

The first independent read-only review blocked production for two reasons:

1. default Uvicorn access logging could retain raw dynamic paths/query strings;
2. rollback after a failed build could restart healthy H before durable install evidence existed.

Both were corrected. Gateway Uvicorn access logging is now disabled and the Platform log is the bounded route-template record. A failed pre-install build now uses a no-mutation H health verification/receipt; the verified release switch is used only after `installed.json` exists. Dedicated behavioral tests cover both cases.

The second independent review concluded `AUTOPILOT_REVIEW=PASS` with no production blockers.

## DEV evidence

- `git diff --check`: PASS
- shell syntax for Stage I/autopilot scripts: PASS
- Python compile: PASS
- focused Platform/Stage I/control-plane tests: PASS
- full local test suite on the final tree after merging current `main`: **842 passed**, 2 unrelated deprecation warnings
- local immutable Stage I release build: PASS (`stage-i-c4bb61b52298`), metadata/import/checksum validation PASS
- Stage I CI workflow includes a full `stage-i-*` release build validation
- rollback point pinned to `stage-h-b9362bdae1c3` / `b9362bdae1c30b53606d992fcecb575d7de71f4b`
- candidate smoke requires `/api/v1/observability`; H rollback smoke requires HTTP 404
- heavy media render is intentionally not repeated because Stage I does not alter media execution; media preflight/client integrity remain mandatory and fresh real post-H Telegram/Discord media evidence is retained as historical evidence only.

## Privilege prerequisite

The narrow root helper extension for Stage I is isolated in PR #67. Its branch CI and post-merge main CI passed before any Stage I production mutation. It only extends the existing exact-stage/worktree allowlist; the nine-step/SHA/clean-tree/branch/ancestry/script-hash restrictions remain unchanged and no general root shell is granted.

Production validation remains pending: immutable build/install, H→I candidate smoke, planned rollback to H with functional 404 proof, H smoke, I reactivation/final smoke, finalize, PR/CI/merge and post-merge CI.
