# Stage M: passive CRT projection boundary

Status: development implementation; production gate not executed.
Baseline: accepted Stage L commit `96f0ec239464f728aca2a7cf374670c9cd9be210`,
Alembic `0004_ers_core_persistence`. Stage M adds `0005_crt_projection`.

## Ownership and authority

can-research-tool (CRT) owns CAN/UDS/J1939 algorithms, projects, deterministic
facts, decoders and raw captures. AI-server owns a stable domain API, imported
projection metadata, ERS associations, advisory findings, provider integration,
Knowledge reference hooks and projection backup/DR. This repository does not
read hardware, transmit CAN, implement protocol logic, apply filters/decoders,
or change CRT's source facts. AI output is untrusted advisory material.

ERS remains the repair-case authority. Links reference an existing ERS case UUID
and an immutable imported session revision. They do not copy case state or session
payloads into ERS. Roles and actors are explicit. Linking, unlinking and relinking
append minimal ERS events atomically, increment the existing case row version,
and retain inactive links. Repeating an unchanged link state is a no-op. ERS
status/work state is never changed. Actors follow the existing ERS caller-supplied
identity contract; this is not a new authentication boundary.

## Manifest contract 1

`POST /api/v1/crt/manifests` accepts the dict produced by CRT's
`app.platform_export.PlatformExporter.manifest()` directly: schema_id
`crt.platform.session-export`, integer schema_version `1`. CRT's exporter code,
tests and Stage M ADR are the authoritative wire source. AI-server rejects unknown
schema IDs/versions and extra envelope/reference fields. Provider-owned artifact
metadata and source_reference objects retain their arbitrary bounded JSON fields;
artifact schema_version is independent of the platform envelope version.

The server hashes the complete received wire JSON using SHA-256, UTF-8, sorted
keys, compact separators, ensure_ascii=False, no NaN, no trailing newline. There
are no injected defaults or timestamp conversions in the wire model. There is no
self-referential manifest_hash and no client manifest_version. Identical hashes
for one external project/session return the same immutable projection UUID. A
changed selection/hash allocates another server revision. Migration 0005's existing
manifest_version column stores that internal revision; API responses also expose
it as projection_revision. Unique constraints and transactional retries arbitrate
concurrent imports. No migration change is needed.

The entire wire manifest is deterministic metadata: external project/session IDs,
source kind/header/time/adapter/bitrate/channel, capture mode, time bounds with their
clock description, observed/catalog counts, provenance, omitted_data, limitations,
files and selected artifacts. No raw frame rows or file contents are imported.
Both raw/original file references and selected artifact file references are indexed
in the existing artifact table with hashes, byte sizes, media types and roles.
Selected artifact IDs remain external IDs; top-level files receive local index
keys. Project-relative paths and complete artifact provider/run/source metadata
remain in the immutable manifest. Internal crt:// URIs are derived with escaped
IDs/paths, never fetched. GET/list expose schema_id/version, manifest_hash,
external_project_id, external_session_id, projection_revision and the complete
manifest. The existing project_id field remains the internal database UUID.

Manifests are limited to 1 MiB canonical JSON and 128 files/selected artifacts.
Unsafe absolute/traversal paths, duplicate files/artifacts and cross-session
artifact sources fail closed. Capture integrity and availability remain CRT-owned;
hashes are integrity identifiers, not signatures or proof of having read files.

## Advisory analysis and Knowledge

An AI Finding contains provider/model identity, actor, context hash, source
references, statement, optional confidence, and `suggested` (default) or
`to_review` status. It cannot update a manifest or become a confirmed deterministic
fact. Optional bounded `knowledge_refs` carry document/version/chunk IDs and
content hashes for future Knowledge integration; they are references supplied
by callers, not automatically verified citations or Knowledge writes.

Signal Hypothesis accepts the exact `PlatformExporter.context()` dict with
schema_id `crt.platform.ai-context`, integer schema_version `1`, directly as the
request body. The existing {context, actor_id} envelope is also supported. Direct
imports use the explicit audit actor `crt-context-import`; this is a label, not an
authenticated identity. The package limit is its positive maximum_bytes, capped
at 1 MiB, with at most 16 distinct evidence entries and a 2048-character question.
Empty evidence is valid for a manifest with no selected artifacts.

Validation binds project/session IDs and manifest_sha256 to the immutable revision,
compares all source_files and selected artifact IDs/hashes/file references and
provenance to the imported manifest, and requires the same selected artifact set.
Selected_payload is untrusted bounded JSON. CRT hashes original artifact file bytes
but transmits parsed JSON, losing whitespace/encoding information, so AI-server
cannot recompute that file hash from selected_payload or prove its origin. It
preserves the supplied hashes and records a context hash over the complete package;
it does not claim cryptographic payload-to-file verification. No URI or file is
fetched. Selected summaries may be retained in advisory finding context; this does
not introduce capture/file ingestion.

AI-server's stored FindingRequest projection is its own advisory schema, not the
CRT `crt.platform.ai-finding` v1 wire payload. That CRT helper's suggested-status
provider/model/context_sha256/sources/artifacts/title/description contract is not
ingested or claimed compatible by this endpoint. Existing AI-server advisory
statuses, Knowledge references and ERS audit behavior are retained.

Execution is injected through the existing `LLMProvider.generate` contract with
`structured-generation`, an explicit output JSON schema and no tools. A validated
response becomes a finding with returned provider/model provenance. Tool calls,
extra output fields and oversized output fail closed. Stage M's release factory
defaults to the reusable synchronous `PlatformAPIProvider`, calling Gateway
`POST /api/v1/ai` with logical model `reasoning-main`. Explicit provider injection
still overrides this default. The adapter preserves request IDs, sends only public
context fields, supports optional bearer authentication, bounds HTTP timeouts and
validates public response provenance. The service supplies domain `ecu-repair`,
`context_ref` equal to the context hash, and the projection session UUID.
Gateway retains scheduler/resource-manager admission; this synchronous boundary
introduces neither a direct backend call nor a separate job queue. Generic
`create_app()` behavior remains unchanged. Deterministic injected-provider tests
cover execution offline; live inference remains pending the production gate.

## Composition, rollback and DR

Generic `create_app()` retains WVC/ERS defaults. CRT requires `CRTAdapter` or
`create_stage_m_app()`. The Stage M release builder stamps CRT contract 1 and a
release-local marker selecting that composition; other release stages have no
marker and retain their prior entrypoint. Nothing modifies root configuration.

Stage K's shared PostgreSQL dump includes all five CRT tables. Schema 0005 backup
metadata includes deterministic per-table row counts and SHA-256 digests (UTC,
UUID order, canonical row JSON). Offline verification requires that contract;
isolated restore validates table contents before Knowledge relocation/reindex.
Knowledge canonical objects and ERS object backup behavior are retained. CRT raw
captures are excluded and must be backed up/recovered independently by CRT.
The paired ERS backup remains mandatory for complete shared-database recovery.

The adapted nine-step gate targets Stage M/0005 and rolls back to Stage L/0004.
It preserves ERS tables and events, checks existing Knowledge/WVC/Hermes/messaging
health, and exercises passive imports, links and real Signal Hypothesis inference.
Valid context must produce a suggested finding with non-unknown provider/model;
invalid schema and oversized context must still fail closed.
Before dropping CRT tables it requires a fresh verified Stage M backup and saves
an immutable, hashed, quiesced CRT data checkpoint under root gate state. After
upgrading again it restores that checkpoint transactionally. Link events survive
rollback in ERS as provenance references, even while CRT routes are absent.
Checkpoints are root-readable metadata; retain them with gate evidence and use
Stage K backups for disaster recovery, not the checkpoint as the sole backup.

A failed or partial schema transition must remain quiesced. Retry the explicit
rollback step after resolving the failure; never downgrade below 0004. Standalone
Alembic downgrade removes CRT projections and must only be used with verified
backup/checkpoint protection. Disaster restoration uses a matched shared dump
and ERS object set with the corresponding immutable runtime; restoring only raw
CRT captures does not recover advisory findings or audit linkage.

## Cross-repository evidence

`tools/stage_m_cross_repo_check.py` is an optional local check outside CI collection.
It imports actual CRT code from the read-only sibling checkout, creates a temporary
project/session and analysis artifact using CRT public APIs, calls manifest/context,
and posts the unchanged dicts through AI-server's models and API. It covers raw and
original file references, artifact schema version 2 inside platform version 1,
selected/empty evidence, identical import reuse and changed-selection revisions.
`tests/fixtures/crt_platform_v1.json` was generated by that check and is used by
normal CI tests and the smoke gate without requiring the external checkout.
See the Stage M development report for commands and results.
