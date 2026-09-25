# Stage M development gate — 2026-09-25

Development implementation on `agent/stage-m`, based on accepted Stage L commit
`96f0ec239464f728aca2a7cf374670c9cd9be210`. No production gate, migration against
production, service restart, sudo, root bridge installation, /etc change, push or
merge was performed.

## Delivered

- [ADR 0013](../adr/0013-stage-m-crt-projection.md): ownership, passive policy,
  external captures, revision/hash semantics, ERS/AI/Knowledge boundaries and DR.
- `alembic/versions/0005_crt_projection.py` and Alembic model registration: five
  metadata tables (`crt_projects`, `crt_sessions`, `crt_session_artifacts`,
  `crt_ers_links`, `crt_ai_findings`); downgrade only removes these tables.
- `src/ai_bridge/domains/crt/`: strict schemas, adapter, repository, API, existing
  provider-based Signal Hypothesis service, and explicit release composition.
  Existing untracked CRT scaffold was retained and completed.
- `/api/v1/crt`: manifest import, session list/get, audited ERS link/unlink/list,
  advisory finding persist/list, bounded Signal Hypothesis boundary. Unknown schema
  versions fail closed; concurrent identical imports converge on one revision.
- Stage K `backup.py`, `verify_backup.py`, `restore_validate.py`, `crt_dr.py`: CRT
  counts/hashes in the shared dump contract and isolated restore verification.
  No CRT capture storage or object namespace was added.
- `deploy/stage-m/`: release wrapper/validator, schema helper, nine adapted gate
  scripts, gate implementation and prerequisites README. Rollback remains Stage
  L/schema 0004. CRT checkpoints survive the rollback/reactivation drill.
- Shared release builder/main entrypoint, CI release-build job, and root executor
  **source only**: explicit Stage M marker/contract and dedicated worktree allowlist.
- New CRT/operations tests and updated prior-stage allowlist assertions.

## Validation

All commands used `/home/harrypotter/AI-server/.venv/bin/python` and this worktree's
`src` on `PYTHONPATH`. SQLite migration tests used temporary databases only.

Initial implementation full suite (before reconciliation):

```text
PYTHONPATH="$PWD/src:/tmp" timeout 240 /home/harrypotter/AI-server/.venv/bin/python \
  -m pytest -p stage_m_asyncio_poll --disable-warnings
965 passed, 11 warnings in 14.52s
```

Focused CRT/operations plus ERS API/persistence/DR, Stage L gate contracts and
privilege-bridge contracts: **86 passed, 7 warnings in 4.63s**. Three additional
mocked schema-order/marker tests were added afterward and included in the final
965-test run. Earlier exploratory failures (path-count assertion, SQLite timezone
serialization, legacy backup fixture and extended stage allowlists) were corrected
before that final run.

The ordinary TestClient invocation stalled at `TestClient.__enter__` in AnyIO's
cross-thread asyncio portal and was terminated; a diagnostic run timed out with
exit 124. Tests completed with a temporary `/tmp/stage_m_asyncio_poll.py` plugin
that schedules a 10 ms loop heartbeat. This workaround changes test loop wakeups
only; it is not included in runtime/repository code. Its complete implementation:

```python
import asyncio
_original = asyncio.BaseEventLoop.run_forever

def run_forever(self):
    def tick():
        self.call_later(0.01, tick)
    self.call_soon(tick)
    return _original(self)

asyncio.BaseEventLoop.run_forever = run_forever
```

Additional checks: Python compilation, shell syntax and `git diff --check` passed.
The test suite covers schema/version/hash rejection, idempotency including a
concurrent import, retained revisions, ERS event sequencing, advisory provenance
and status, unconfigured and injected providers, context/source/aggregate bounds,
no active-control route, SQLite migration round-trip, mocked DR tampering,
checkpoint checksum rejection, schema-switch ordering and release marker checks.
No production gate was executed; gate tests only load definitions and mock effects.

## Production prerequisites and limits

The implementation is ready for review, not a production acceptance claim.
Install/update the root privilege bridge deliberately later. Confirm the pinned
Stage L immutable release exists with the accepted source SHA, build/install the
committed candidate, and obtain fresh matched Knowledge/ERS backups using the
extended Stage K tooling before rollback/finalization. Then run the authorized
production gate and a real PostgreSQL isolated restore drill. The development
migration round-trip used SQLite; PostgreSQL DDL, real NAS/object restore, release
package installation and live platform behavior were not exercised here.

Signal Hypothesis release execution uses the existing provider abstraction with
the default Platform API v1 adapter. Successful execution was tested with a
deterministic provider and mocked public HTTP envelopes; no live model was called. Knowledge hooks are provenance references, not an automatic retrieval or
indexing pipeline. CRT exporter compatibility is validated against actual code and static generated
fixtures as recorded below; raw capture integrity/availability remains CRT-owned.

## CRT wire-contract reconciliation

Reconciled against the actual read-only checkout at
`/home/harrypotter/agent-worktrees/stage-m-crt`, after reading its exporter, tests
and ADR first. `crt.platform.session-export` v1 and `crt.platform.ai-context` v1
are now consumed directly. No flat manifest translation, self-referential hash,
or client revision is required. The server hashes complete canonical wire JSON,
retains external IDs and all reference/provenance metadata, and allocates immutable
revisions for changed selections. Migration 0005, Stage K DR and ERS audit/link
semantics are retained. No capture contents are loaded or source URIs fetched.

The context validates file references, artifact selection and full provenance
against the imported revision, with a maximum_bytes cap of 1 MiB and 16 evidence
entries. Parsed selected_payload is untrusted: an original file-byte hash cannot
prove the origin of JSON whose original serialization was not transmitted.
AI-server findings remain its own advisory projection, explicitly **not** the
`crt.platform.ai-finding` v1 wire contract. No compatibility claim is made for
that separate producer helper. The ADR records these boundaries and the optional
actor/context envelope alongside direct CRT context ingestion.

The optional `tools/stage_m_cross_repo_check.py` imports actual CRT public APIs,
creates a temporary project, writes two frames and a selected statistics artifact,
includes an original import reference, and calls PlatformExporter.manifest/context.
It validates and posts those returned dicts unchanged to AI-server, verifies
canonical hash equality and metadata preservation, repeats the import, exports a
different selection as revision 2, and tests both selected and empty evidence
through a deterministic LLMProvider. Temporary CRT files are outside the checkout;
PYTHONDONTWRITEBYTECODE prevents cache writes to CRT. No CI dependency on that
checkout is introduced: normal tests and the smoke use the generated static
`tests/fixtures/crt_platform_v1.json`. Artifact schema 2 is deliberately included
to check independence from the platform envelope's version 1.

Source identity (actual file contents, rather than assuming a clean CRT checkout):

```text
CRT Stage M commit: af8671f3eaafb2e153c1644f18135ed9620a92fa
SHA-256 app/platform_export.py:
c534abdfb5bd72d1cba504f11f4cbf81e7b46b14fd3c6f3b8d239c9f38fe78d4
SHA-256 tests/test_platform_export.py:
24b28d6a9d5880780b99d9616d14fc1cf6c5841902b020c7340686e40d85e2b9
SHA-256 docs/STAGE_M_ADR.md:
2b86dd444993550f2e67dcb1338a37173906391b0c47436c4078c0e115d19958
SHA-256 generated tests/fixtures/crt_platform_v1.json:
0fbf4960feba1691af5605ef7503198819af669bff3019cd1341190518ea9936
```

Final reconciliation checks, from the AI-server worktree:

```text
# Ordinary TestClient still needs the existing environment workaround:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:/tmp timeout 20 \
  /home/harrypotter/AI-server/.venv/bin/python -m pytest tools/stage_m_cross_repo_check.py
Exit 124 (TestClient stall); retried with the existing plugin below.

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:/tmp timeout 240 \
  /home/harrypotter/AI-server/.venv/bin/python -m pytest -p stage_m_asyncio_poll \
  tests/test_stage_m_crt.py tests/test_stage_m_operations.py \
  tools/stage_m_cross_repo_check.py --disable-warnings
54 passed, 5 warnings in 6.16s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:/tmp timeout 240 \
  /home/harrypotter/AI-server/.venv/bin/python -m pytest -p stage_m_asyncio_poll --disable-warnings
983 passed, 11 warnings in 16.82s

/home/harrypotter/AI-server/.venv/bin/python -m compileall -q \
  src tests tools/stage_m_cross_repo_check.py deploy/stage-m deploy/stage-k alembic
PASS

git diff --check
PASS

for script in deploy/stage-m/build_release.sh deploy/stage-m/autopilot/*.sh \
  deploy/runtime/build_release.sh deploy/autopilot/install_privilege_bridge.sh \
  deploy/autopilot/root_executor.sh; do bash -n "$script" || exit; done
PASS
```

Untracked Python/JSON/shell/Markdown sources were also checked for trailing
whitespace: PASS. The smoke-contract test uses only a temporary TestClient database
and mocked fetch/database access; no production gate entrypoint was run. Full-suite
coverage includes prior stages, migration round-trip and Stage K DR checks. No
commit, push, sudo, service restart, production change or external checkout edit
was performed. Remaining operational limits are unexercised live inference and
production/PostgreSQL restore behavior described above; no known
wire-contract reconciliation issue remains.


## Final M4 runtime binding

Stage M release composition now defaults to `PlatformAPIProvider` over Gateway
`POST /api/v1/ai`, using logical model `reasoning-main` and existing scheduler/
resource-manager admission. Explicit provider injection and generic Stage L
composition remain unchanged. Public context contains `domain=ecu-repair`, the
context hash as `context_ref`, and a safe projection session UUID. The adapter
validates public response/request IDs and provenance, rejects tool execution,
uses bounded synchronous httpx calls and sends bearer auth only when configured.

The production gate now requires real Signal Hypothesis success for valid context
and retains schema/oversize rejection. Offline gate smoke injects a deterministic
provider and TestClient; no localhost inference occurs in tests. Real live
inference has not been executed and remains pending the production gate.

Final M4 validation in this AI-server worktree (same interpreter and test-only
`/tmp/stage_m_asyncio_poll.py` workaround as above):

```text
Targeted: test_platform_api_provider.py, test_stage_m_crt.py,
          test_stage_m_operations.py, test_provider_contracts.py
85 passed, 5 warnings in 5.86s

Full AI-server suite:
1010 passed, 11 warnings in 17.00s

compileall (src, tests, deploy/stage-m, cross-repo checker): PASS
bash -n (Stage M and shared release/autopilot shell sources): PASS
git diff --check: PASS
```

No production gate, live inference, sudo, commit/push, production change or CRT
repository modification was performed for this binding.
