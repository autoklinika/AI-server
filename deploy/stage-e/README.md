# Stage E supervisor handoff

Implementation/DEV review only until the supervisor records the complete live
cycle. Do not infer production PASS from unit tests or the readiness marker.
Stage E adds the API to the release-managed Gateway on localhost port 11435;
there is no new public listener, firewall rule, Hermes patch, client rewrite,
storage migration or deletion. Stage F/G/H are out of scope.

## API v1

- `POST /api/v1/ai`: synchronous, non-streaming chat/reasoning/structured generation.
  The client supplies `messages`, a capability, optional logical model
  `reasoning-main`, `context`, semantic `priority_class`, `timeout_seconds`
  (queue + execution, default 300, max 600), temperature and response schema.
  Unsupported capabilities return `capability_unavailable`; we do not dispatch
  new media/agent/tool/embedding workloads based on inventory descriptors alone.
- `GET /api/v1/jobs` and `GET /api/v1/jobs/{job_id}`: RM v2 lifecycle, including
  compatibility jobs. In-memory terminal retention is 128 jobs, lost at restart;
  missing/evicted jobs return 404. External lease completion remains reservation
  completion, not evidence of render success. No cancel/resume API is promised.
- `GET /api/v1/models`: logical model/capability inventory, no backend model names.
- `GET /api/v1/systems`: declared compatibility integrations, not live device status.
- `GET /api/v1/health`: process + RM queue counts + actual inference model availability.
  `readiness=false/status=degraded` if the model probe fails; HTTP remains 200.
  Messaging/media/domain health is explicitly `not_probed`, not an invented PASS.

All v1 successes carry `schema_version=1` and `request_id`. Errors use
`error.{code,message,request_id,retryable,details}` with empty sanitized details.
`X-Request-Id` is validated or generated. `context.request_id` is accepted; a
conflict with the header fails. Context supports domain (default shared), actor,
session, case, view and opaque context_ref. It is not retrieved automatically or
persisted in scheduler history. Unknown body fields are rejected. Job IDs are
server generated. Validation errors never echo input. Header/body correlation
IDs must be opaque non-sensitive identifiers, not content or credentials.

Auth policy runs before every v1 route, including health, schema and errors.
`AI_BRIDGE_PLATFORM_API_TOKEN` (minimum 16 chars) requires Bearer authentication;
otherwise only direct loopback peers pass. Actor context is not identity. This
first policy grants a trusted service access to all jobs; it is not multi-tenant
user authorization. Keep the Gateway private. Policy injection and the async
provider port allow replacement without touching v1 clients. Existing D.6
registry IDs remain internal bindings; no dynamic provider registration is added.
All legacy paths, numerical priorities, leases and recovery modes remain intact.

Example new client (only Platform API URL):

```json
{"capability":"reasoning","context":{"domain":"shared"},"messages":[{"role":"user","content":"Return OK."}]}
```

## Production scripts

The nine `autopilot/*.sh` wrappers run the versioned Python executor with
`sudo -n`; only the supervisor invokes them. `00_preflight` is read-only. Build
reruns preflight, captures an immutable baseline, and builds both virtualenvs
at their final release paths from a clean committed SHA. It never activates.
Build failure preserves the partial candidate and fails closed on retry.
The release declares Stage E, config schema 4, Platform API 1, RM 2 and all D.6
subcontracts unchanged. Stage D builders/validators and recovery files remain.

Rollback is pinned to verified `stage-d-resource-manager-v2-20260922-r2`, source
`82d55f629f763c9352ad7c9e678e22eadb623639`, and its byte-identical five matched
clients. Checksums, clients, current symlink, running service cwd, health and
idle are verified. Candidate builds must contain the same clients. Stage E
never changes them. D.0 and the D.6 recovery snapshot are never removed.

State is root-only under `/var/lib/ai-platform/stage-e/<full-source-sha>` with an
exclusive executor lock. Baseline/evidence use exclusive creation and fsync.
Switches atomically replace `current` while ingress is quiesced and services are
stopped. The harness must preserve and restore ingress/analysis activation state.
No ComfyUI restart is allowed. The supervisor's existing automatic rollback
handles failed cutover/smoke; rollback also handles a stopped/failed candidate
Gateway. Do not delete state to bypass failed gates; investigate first. Smoke
retry fails closed rather than overwriting evidence. No GitHub command is used.

### Autonomous production quiesce and smoke

Stage E does not require a new private site harness or any new Telegram/Discord
credentials. Before each release switch the privileged executor closes the real
ingress it controls: it stops the existing Hermes gateway and pauses the
`ai-bridge-analysis.timer`, waits for Resource Manager and ComfyUI idle, then
switches the release atomically. On a healthy candidate/rollback it restores the
previous activation state and waits for Hermes to reconnect. The existing Hermes
service owner is discovered from `/srv/ai-data/hermes`; user-systemd is invoked
with `runuser` and the owner's `XDG_RUNTIME_DIR`, matching the D.6 production
finding.

Fresh Stage E smoke is intentionally limited to evidence that can be generated
autonomously without impersonating real Telegram/Discord users:

- new-client Platform API inference plus jobs/models/systems/health,
- real compatibility WVC -> Gateway -> Qwen inference,
- Hermes gateway state with Telegram/API and configured Discord connected,
- byte-identical D.6 matched clients,
- release-managed media preflight,
- service identity stability, health and idle recovery.

The fresh D.6 production evidence for Telegram multiuser isolation, `/foto`,
`/wideo`, Discord and real media remains the compatibility baseline because
Stage E does not modify Hermes source, those five matched clients, models, GPU
configuration or media workflows. Stage E does **not** relabel historical D.6
evidence as a fresh user-path PASS. A later stage that changes Hermes or messaging
must execute its own fresh user-path validation.

The production smoke independently executes new-client Platform API inference,
correlated job lookup, models/systems/health, and real compatibility WVC inference.
It validates Hermes connectivity, matched-client integrity, media preflight,
service identity stability and post-smoke idle on candidate, D.6 rollback and
final Stage E reactivation. Physical WVC telemetry growth is not claimed when
CM5 is offline. `90_finalize` requires all three immutable smoke records and the
active healthy candidate, then writes `docs/reports/AI_PLATFORM_STAGE_E_PRODUCTION_GATE.md`.
No production report is fabricated during implementation.
