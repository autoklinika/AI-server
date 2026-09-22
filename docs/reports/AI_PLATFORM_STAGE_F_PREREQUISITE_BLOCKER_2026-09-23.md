# Stage F prerequisite gate

Status: **BLOCKED before implementation/deployment**. Stage G/H: **NOT STARTED**.
No Stage F production mutation or cleanup was performed.

## Verified production baseline

Stage E is complete: `stage-e-38fff86f7704`, source
`38fff86f7704fcee92d66a750c033a9ec69ff084`. Its candidate, D.6 rollback and final
reactivation smoke all passed, including admitted real media.
[PR #53](https://github.com/autoklinika/AI-server/pull/53) merged as
`02e85aad5a0aec90ade9985467b07fa43f740730`.
[Final PR CI](https://github.com/autoklinika/AI-server/actions/runs/35789623390)
and [post-merge CI](https://github.com/autoklinika/AI-server/actions/runs/35789787023)
passed. The exact production-source CI passed 764 tests and release builds.

At the F prerequisite audit, Platform readiness was true, Resource Manager counts
were 0 active / 0 queued / 0 leases, and Hermes Telegram, Discord and API-server
connections were healthy. E stays active; D.0/D.6 and failed E attempt evidence
remain preserved.

## External prerequisite

The [Stage F specification](../../deploy/autopilot/prompts/stage_f.md) requires
fresh inbound Telegram multiuser isolation, normal chat, `/foto`, `/wideo`,
WAIT/START targeting and Discord user-path validation. The
[D.6 validation runbook](../../deploy/stage-d/D6_VALIDATION_RUNBOOK.md) requires
two consenting test users and explicitly leaves missing-participant multiuser
validation NOT RUN.

Read-only audit of the known control/private-configuration locations
(`agent-control`, `agent-state`, `.config/ai-platform`, `/srv/ai-data/hermes`)
found no provisioned Telegram user-client harness, MTProto session files or
recognized test-user authentication settings. Conversation stores were excluded;
no conversation content or credentials were copied into this report. The local
sanitized evidence is `manual-eh/stage-F-prerequisite-audit.json`.

Existing Stage C tooling exercises the Hermes API-server boundary. Stage E
exercises one-shot inference, correlated synthetic Gateway requests and actual
outbound delivery. These do not produce independent user-originated Telegram
updates or verify fresh reply/WAIT/START/media isolation for two real users.
Historical D.6 user-path PASS is not fresh Stage F evidence.

The execution agent cannot safely manufacture consenting user identities or
replace the required external paths with synthetic API injection. Stage F cannot
be completed autonomously with the provisioned capabilities. No failing or absent
E2E gate has been relabeled PASS.

## Hermes recovery inventory and resumption

The live Hermes checkout is pinned at
`79445a496c86a19332ad786494b8384d2167e2d0`, with three existing modified files:
`agent/turn_api_request.py`, `gateway/run_inbound.py`, and
`gateway/run_turn_runner.py` (245 added lines total). They remain untouched.
This inventory is **not** a complete restore snapshot.

To resume, provide either a coordinated test window with two consenting Telegram
users plus a Discord participant, or a provisioned and authorized equivalent
external-user E2E harness. Keep authentication material in private storage, never
in Git, reports or chat replies. The scenario must demonstrate cross-user/thread
isolation, WAIT/START order, normal chat, `/foto`, `/wideo`, actual delivered media
and Discord request/reply behavior.

Before any F production mutation, capture and verify the required immutable
Hermes recovery snapshot: exact source identity, dirty patch, configuration/state
and integration artifacts. Then implement the supported adapter/extension
boundary, run independent review/CI, and complete the F candidate/rollback/
reactivation cycle against the verified E baseline. G/H remain sequentially gated
on F completion; no cleanup or quarantine is authorized by this blocker report.
