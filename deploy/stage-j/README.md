# Stage J — Knowledge Service production release

**Production status: PASS / COMPLETE — 2026-09-24**
Accepted release: `stage-j-3b456a56343a`
Accepted source SHA: `3b456a56343a533d2d920e1e63dfe304530c865b`
Production report: [AI_PLATFORM_STAGE_J_PRODUCTION_GATE_2026-09-24_PL.md](../../docs/reports/AI_PLATFORM_STAGE_J_PRODUCTION_GATE_2026-09-24_PL.md)

Stage J closes the Knowledge Service migration introduced after Stage I.

## Release identity

- stage: `J`
- migration: `knowledge-service-v1`
- Platform API contract: `1` (additive routes)
- observability contract: `1`
- Knowledge Service contract: `1`
- rollback release: `stage-i-30626dcc60f8`

Stage J does not replace the existing Platform API. It adds the Knowledge surface
under `/api/v1/knowledge/*`.

## Production gate

Run in order:

```bash
deploy/stage-j/autopilot/00_preflight.sh
deploy/stage-j/autopilot/10_build_install.sh
deploy/stage-j/autopilot/20_cutover.sh
deploy/stage-j/autopilot/30_smoke.sh
deploy/stage-j/autopilot/40_rollback.sh
deploy/stage-j/autopilot/50_rollback_smoke.sh
deploy/stage-j/autopilot/60_reactivate.sh
deploy/stage-j/autopilot/70_reactivate_smoke.sh
deploy/stage-j/autopilot/90_finalize.sh
```

The supervisor performs a real `J -> I -> J` cycle.

Before building the candidate, `10_build_install` also performs fail-closed production data preparation:
- one immutable PostgreSQL custom-format backup keyed by the source Git SHA;
- two-pass PDF ingestion (the second pass must create zero versions/chunks);
- pending Knowledge index drain through the existing retrieval adapter;
- SHA-256 verification of every content-addressed canonical object.

The backup and integrity evidence live under `/srv/ai-data/backups/stage-j/<sha>/`.
Secrets are read only by the privileged executor and are never emitted.

Candidate/final smoke proves:
- existing Platform API + observability;
- raw Knowledge search;
- RAG answer with citations;
- document metadata and immutable content opening;
- WVC;
- Hermes inference;
- messaging boundary;
- media preflight.

Rollback smoke proves Stage I is healthy and Knowledge routes are absent.

## Gateway canonical DB access

Stage I gateway did not need PostgreSQL. At Stage J cutover the supervisor copies
only the existing `AI_BRIDGE_DATABASE_URL=...` assignment from the protected
AI Bridge env file into the Gateway env file. It never prints the value.
The extra variable is backward-compatible with Stage I and remains harmless during
rollback. The production database is not migrated or recreated by Stage J cutover.

## Data independence

Stage J release activation does not modify canonical knowledge. PostgreSQL and the
object store outlive code rollback. Qdrant remains rebuildable.

PDF ingestion/reindex are separate data operations documented in `deploy/stage-j4`.
