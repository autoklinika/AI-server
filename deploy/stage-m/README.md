# Stage M development release and gate

This directory is prepared for a later deliberate installation. No gate step has
been run as part of development. Ownership and exchange contracts are in
[ADR 0013](../../docs/adr/0013-stage-m-crt-projection.md).

The release builder extends the shared Stage L build: migration tooling,
Knowledge/ERS/observability contracts remain version 1; CRT adds domain contract 1
and migration contract `crt-projection-v1`. Schema head is `0005_crt_projection`.
A release-local empty `src/ai_bridge/stage_m_enabled` marker selects
`ai_bridge.domains.crt.release:app` for the AI Bridge entrypoint. Metadata validation
requires the marker and the release checksums cover it. Generic `create_app()`
and builds for prior stages retain their previous composition.

The nine gate steps are copied/adapted from Stage L. The rollback identity is
pinned to `stage-l-96f0ec239464` and source SHA
`96f0ec239464f728aca2a7cf374670c9cd9be210`; preflight must confirm that immutable
release actually exists and matches the accepted runtime. Do not substitute a
newly built Stage L runtime as an unreviewed rollback baseline.

Before later production use:

1. Review/commit the development changes and build the immutable candidate through
   the existing release workflow. The root executor requires a clean tracked
   `agent/stage-m` worktree and matching remote SHA.
2. Deliberately install the updated root privilege bridge using the existing
   administrative process. This change only extends its repository source with
   stage M and the dedicated worktree path; the installed bridge is untouched.
3. Verify the accepted Stage L release path, checksum/source identity, schema 0004,
   and fresh paired Stage K Knowledge/ERS backups. Use this version of Stage K
   backup tooling for schema 0005 so CRT metadata digests are included.
4. Keep writers quiescent for schema changes. After candidate smoke, obtain a fresh
   Stage M backup before `40_rollback`; the gate refuses destructive downgrade
   without it. It also records its own quiesced CRT SQL checkpoint. Reactivation
   requires that checkpoint and verifies restored counts. Obtain another fresh
   Stage M backup before final acceptance.
5. Execute the nine steps only through the deliberately authorized production
   process. Smoke checks use a clearly named synthetic CRT project and link/unlink
   an existing ERS case; the audit events remain visible after rollback. No repair
   case is created. Existing platform, Knowledge, WVC, Hermes and messaging checks
   remain in the gate.

Stage M M4 binds Signal Hypothesis to the synchronous `PlatformAPIProvider` by
default through Gateway `POST /api/v1/ai` (logical model `reasoning-main`).
Gateway scheduler/resource-manager admission remains authoritative; no direct
backend call is introduced. The adapter uses the configured bearer token when
present, otherwise the Gateway loopback policy applies. Context contains only
public fields: `ecu-repair`, the context hash as `context_ref`, and the projection
session UUID. Explicit `create_stage_m_app(provider=...)` injection remains
available; generic/prior-stage composition is unchanged.

The production gate requires real inference for valid bounded context, a
`suggested` finding and non-unknown provider/model provenance. Schema and oversized
package checks still fail closed. Offline tests inject a deterministic provider
and TestClient. Real live inference has not been executed and remains pending the
separately authorized production gate.

Stage K restores CRT metadata from the shared dump and verifies row hashes;
CRT itself must restore external captures. No CRT object namespace exists here.
The gate checkpoint preserves CRT projections across its rollback drill, but is
not a replacement for the paired backup/isolated restore procedure. Do not run a
bare downgrade against unbacked-up findings. Stage M never downgrades below 0004.
