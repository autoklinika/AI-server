# Stage I — Observability & operations hardening

Stage I is the P2 observability step after the completed E–H core migration. It is intentionally operational, not a new AI feature. Knowledge Service remains the next functional stage after I.

## Scope

The Platform API gains `GET /api/v1/observability`. The response is bounded metadata only and aggregates existing runtime truth instead of creating a second scheduler/job database. It includes:

- Platform API request totals, in-flight count, status classes, bounded error classes and average/max latency;
- Resource Manager admission/active/queued/max limits;
- active Resource Manager lease count;
- GPU residency state and authoritative cleanup summary;
- recent job state/capability/provider/node counts plus queue-wait and execution timing summaries;
- logical provider/model/node identity;
- process RSS and user/system CPU seconds;
- terminal job retention policy and count.

`GET /api/v1/health` remains API v1 and adds lease/GPU components. Existing clients are not required to consume the new fields.

## Privacy and logging

Platform request completion is logged as one structured JSON payload containing only correlation ID, HTTP method, normalized route template, status, duration and bounded error class. The code does not store prompt/response content, auth values, chat IDs, actor/session fields, raw exception text or raw dynamic URLs. Uvicorn access logging is disabled on the Gateway because its default formatter includes the concrete request target and query string. Observability is in-memory and resets with the Gateway process.

No Prometheus, Grafana, OpenTelemetry collector or persistent metrics database is added in Stage I. Those can consume this stable contract later without becoming the source of runtime semantics.

## Production and rollback

Candidate release metadata is `stage=I`, `migration_version=observability-v1`, `observability_contract_version=1`. The immutable rollback point is `stage-h-b9362bdae1c3` (`b9362bdae1c30b53606d992fcecb575d7de71f4b`).

The nine production steps preserve the established contract: preflight, build/install, cutover, candidate smoke, rollback, rollback smoke, reactivation, final smoke and finalize. Hermes ingress and the WVC analysis timer must be active before Stage I and are restored to the same active state after every healthy switch.

Candidate/final smoke requires the new endpoint and validates real Platform API, WVC and Hermes inference plus the messaging boundary, matched client bytes, health and media preflight. Rollback smoke requires `/api/v1/observability` to return 404 on H, proving functional rollback rather than only symlink movement.

Stage I deliberately does not trigger another heavy LTX render. No media execution code is changed here, and fresh post-H real Telegram/Discord voice/foto/wideo tests already passed. Stage I keeps media preflight and installed-client byte integrity as regressions; the earlier user-path evidence remains historical and is not renamed as a fresh Stage I media PASS.

## Privilege boundary

Stage I extends the existing root helper allowlist only after a separate prerequisite change is merged to `main` and installed from a clean current main checkout. The helper still accepts only the existing nine tracked step names, exact committed SHA, clean `agent/stage-i`, ancestry from `origin/main`, and matching committed script bytes. It grants no general root shell.
