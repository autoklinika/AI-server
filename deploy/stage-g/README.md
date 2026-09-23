# Stage G — WVC domain and freshness

**Production acceptance PASS:** `stage-g-fa6b31e5f7dc` passed the isolated
cold-boot probe and fresh candidate/F-rollback/reactivation full gates on 2026-09-23.
The rejected `7ccc9c14da33` incident remains preserved; no driver fix is claimed.
Hermes/external inbound remains paused and DEFERRED/NOT TESTED. See the
[production/incident report](../../docs/reports/AI_PLATFORM_STAGE_G_PRODUCTION_GATE.md).

The [domain architecture](../../docs/architecture/WVC_DOMAIN.md) defines ownership,
compatibility and freshness. The verified rollback point is
`/opt/ai-platform/releases/stage-f-d8f68cadd953` (PR #63, post-merge CI PASS).
No provider, Hermes plugin, client binary, systemd configuration or database schema
changes in this stage. Cleanup diagnostics and bounded polling are repaired in G. G switches both platform services to one immutable source
release. GPU ownership retains the verified F predicates with bounded cleanup settling; neither Ollama nor ComfyUI
is restarted by G deployment or normal handoffs.

Use the exact clean/pushed `agent/stage-g` SHA through the supervisor privilege
bridge, in order: `00_preflight`, `10_build_install`, `20_cutover`, `30_smoke`,
`40_rollback`, `50_rollback_smoke`, `60_reactivate`, `70_reactivate_smoke`,
`90_finalize` (all `.sh` under `autopilot/`). Failure retains phase evidence.
Rollback verifies the target release, quiesces workers, explicitly recovers GPU
residency with known-good E Python and the reviewed controller, and restores F
without depending on a healthy G candidate. It never replaces central history.

Each smoke checks Platform API, WVC admission/inference, Hermes, configured
outbound messaging, four real media paths through the installed plugin, cleanup,
post-media inference and unchanged provider identities. Kernel cursor guards stop
ingress on a new GPU fault. Historical rows are verified by bounded hashes. G
candidate/final smoke also invokes the actual domain freshness policy against the
configured production database; it reports the observed skip or analysis result.
No fresh telemetry is acceptable; no physical CM5 reconnection is invented.

Messaging E2E remains SYNTHETIC/INTERNAL. Real external inbound Telegram/Discord
is DEFERRED/NOT TESTED. Recovery follows the
[GPU runbook](../../docs/runbooks/GPU_RESIDENCY_RECOVERY.md). D.0/D.6/E/F recovery
artifacts and current conversation/domain data remain preserved.

On a same-boot kernel blocker, `40_rollback.sh` uses the explicit paused containment
path: verify F, stop producers, require workers gone, switch to F and start only
telemetry/history. It does not invoke GPU providers, clear markers, resume ingress
or claim an acceptance smoke. A new controller SHA may run this path without
requiring an installed/healthy failed candidate.

Cold-boot recovery preflight performs the recorded diagnostic-to-systemd handoff
and a bounded admitted 1s 640x384 video with Ollama explicitly empty and kernel
cursor evidence. Hermes/external inbound and analysis ingress remain paused
through acceptance; the real one-shot and synthetic/internal tests run locally.
Candidate, planned F rollback and final G reactivation smokes remain mandatory.
