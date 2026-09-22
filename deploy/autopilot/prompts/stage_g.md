# Stage G — WVC as a real domain

Implement the migration-plan Stage G only.

Separate WVC/ventilation details from Platform Core through a WVC domain package/adapter.
Preserve the existing telemetry API during migration and central history.

Required domain behavior:
- WVC analysis policy belongs to the domain adapter,
- freshness gate is explicit,
- absence of new telemetry is a valid `skipped/no_fresh_data` result, not a platform error,
- if fresh telemetry exists, ingest/analysis resumes without duplicate processing,
- AI remains advisory-only,
- Platform Core must not contain SEN55/fan-specific policy.

Production gate must work safely whether the physical WVC/CM5 is currently connected or
temporarily unavailable. When unavailable, validate the no-fresh-data path and existing
stored history without inventing live evidence.

Rollback target is the verified Stage F runtime; preserve the existing telemetry API.
