# Stage H production gate — 2026-09-23

Status: implementation/reference audit; production acceptance NOT RUN. Stage G
passed all production gates, merged in PR #64 as `7b73598f198444edd414d8fcc816fdf94fcd98f8`,
and post-merge CI [35855156672](https://github.com/autoklinika/AI-server/actions/runs/35855156672) passed before H started.

Scope is four unused libexec copies, not active media helpers. The maintained video
wrapper loads the immutable release's generator modules; active global dispatchers
and their base/resource/compiler dependencies remain. The exact candidates, audit,
quarantine and restoration protocol are in the [H runbook](../../deploy/stage-h/README.md).

All existing releases and worktrees, `/opt/ai-bridge`, `/opt/ai-gateway`, D.0/D.6
recovery snapshots, verified F/G, failed GPU candidates/evidence, models and domain
state are KEEP. Historical installer references are recorded and require restoring
the H manifest before use. No destructive cleanup or retention purge is authorized
by this report.

Required evidence remains pending: root reference audit; immutable build; candidate
quarantine/full smoke; exact file restoration and G rollback/full smoke;
reactivation/full smoke; final reference audit; CI, merge and post-merge CI.
External inbound Telegram/Discord remains DEFERRED/NOT TESTED; physical WVC
reconnection remains NOT TESTED. Inbound is paused. No GPU driver fix is claimed.
