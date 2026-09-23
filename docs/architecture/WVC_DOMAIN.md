# WVC domain boundary

`ai_bridge.domains.wvc` owns telemetry schemas, SQL mappings/repositories, analysis
profiles, deterministic sensor/fan interpretation, advisory rendering, analysis
policy and the existing telemetry/delivery router. Platform composition installs a
`DomainAdapter`; it can run without WVC. Core, Gateway and generic storage contain
no SEN55 or fan policy. Legacy Python module paths are exact compatibility aliases,
and the CLI name `ai-bridge-analyze-ventilation` remains unchanged.

The database schema and all existing table names/constraints remain unchanged.
No migration rewrites or deletes history. Telemetry batch/sample identities retain
their existing deduplication rules. `/api/v1/ventilation/telemetry/batches` and
`/api/v1/ventilation/analysis/latest` preserve their wire contracts. Health remains
generic. WVC delivery is advisory-only and exposes no actuator/control endpoint.

The scheduled CLI delegates to `WVCAnalysisPolicy`. Freshness is explicit: the
selected completed, timezone-aware window must contain telemetry from that source.
An empty window returns `status=skipped`, `reason=no_fresh_data`, exit 0, without
calling a model or storing an empty analysis row. Historical telemetry outside the
window cannot make it fresh. Explicit `--end-at` selects a historical window for
operator replay; it does not claim current device connectivity.

Once new telemetry arrives, normal ingest resumes; retransmitted batches/samples
remain duplicates. A populated window follows the existing minimum-sample and
v12.2 advisory policy. Existing results retain their window/model/profile identity
and are reused. Completed windows remain immutable, including insufficient-data
results; late additions do not silently rewrite an already published advisory.
No separate watermark can advance on an empty window or permanently suppress a
later populated window.

The read/reuse/generate/save boundary is serialized across scheduled processes:
PostgreSQL uses a session advisory lock; SQLite uses a process lock and file flock
(in-memory databases use the process lock). Crashes release the locks. Ingest is
not locked by this analysis policy. The existing unique analysis constraint remains
a second guard. A model failure writes no completed result and does not consume
freshness. Direct legacy service APIs remain for explicit historical compatibility;
scheduled execution always uses the domain policy.

Production checks hash existing rows at captured maximum IDs, so appended telemetry
or analysis is allowed while mutation/removal of captured history fails the gate.
Physical WVC/CM5 availability is not a prerequisite: an observed empty current
window is a valid skip, not an inference or platform-health failure. Synthetic
reconnection tests are reported separately from physical-device evidence.
