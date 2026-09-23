# Stage F: supported Hermes messaging plugin

Draft: post-reboot residency isolation is implemented; production acceptance is still pending. See [GPU ownership architecture](../../docs/architecture/GPU_RESIDENCY.md) and [recovery runbook](../../docs/runbooks/GPU_RESIDENCY_RECOVERY.md). The prior [incident report](../../docs/reports/AI_PLATFORM_STAGE_F_GPU_BLOCKER_2026-09-23.md) records the pre-reboot state.

The operator approved SYNTHETIC/INTERNAL E2E as the acceptance boundary on
2026-09-23. External Telegram/Discord inbound transport remains DEFERRED/NOT
TESTED. D.6 external-user evidence remains historical, not fresh Stage F evidence.

The upstream pin is `79445a496c86a19332ad786494b8384d2167e2d0`. The plugin uses
`pre_gateway_dispatch`, `llm_execution` middleware and `register_command`.
Its observer records context only; Hermes authorization remains in force before
commands run. Config replaces the two exec quick commands with plugin commands.
All three source patches are removed at cutover; rollback restores their exact
bytes, config, mode and ownership. No monkeypatch is installed in Hermes.

Queue admission uses the existing RM lease client, with reservation-owned
request/job correlation and an explicit final release even on provider failure.
Hermes consumes streaming completion inside the middleware callback at this pin.
Routing uses task-local session context; media subprocesses receive an explicit
environment with inherited routing/media/lease values cleared. Prompts are a
single argv item and never shell-interpolated. Discord voice notices bind to the
invoking event's guild/channel and task lifetime; temporary audio is owned and
removed by the adapter.

`internal_e2e.py` exercises installed plugin discovery, real Hermes conversation/streaming execution, hook dispatch/middleware,
four independent synthetic contexts (two per platform), actual localhost
Gateway/RM admission, bounded Qwen inference, WAIT before START, request/job
identity, production foto/video dispatchers, prompt compilers, renderers and
artifact validation. Only outbound delivery and the worker launch redirect are
replaced with an internal recording sink; no update is passed off as external.
The harness never sends to synthetic chat identifiers. Offline failure tests
cover subprocess arguments, attachment isolation, voice routing and cleanup.
The production compatibility gate separately executes real Hermes inference,
Platform API, WVC, actual configured outbound messaging and baseline media.

Supervisor scripts require an exact committed/pushed SHA through the existing
privilege bridge. They capture private recovery evidence before mutation:
upstream source archive, dirty patch and touched file bytes, config/state and
integration archive, SQLite online backups and integrity checks, hashes and
ownership. D.0/D.6 are preserved. Planned rollback restores the E runtime and
source/config snapshot but deliberately preserves newer conversation/domain
state. Recovery databases are available for disaster recovery, not automatically
replayed over live history.

Candidate and final internal evidence are separately generated and immutable.
External transport is explicitly deferred in every acceptance record. A repairable
smoke assertion does not trigger automatic rollback if runtime/admission are
healthy; source/config uncertainty or degraded runtime requires recovery. The
planned E rollback and reactivation remain mandatory. No Stage F PASS is claimed
until all gate evidence and CI/review complete.
