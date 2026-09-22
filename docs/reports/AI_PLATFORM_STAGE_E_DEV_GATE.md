# Stage E — implementation and DEV gate

Status: **READY FOR INDEPENDENT REVIEW**. Production validation: **NOT RUN**.
The implementer did not commit, push, use GitHub CLI, activate releases, alter
production or send test messages to external users/services.

The additive Platform API v1 shares the existing Gateway Resource Manager v2.
It provides capability/logical-model inference, correlation/context envelopes,
normalized errors, metadata-only job views, logical models, systems inventory,
sanitized aggregate health and an explicit auth policy boundary. Legacy Stage D
routes, leases, priorities, streaming, matched clients and recovery artifacts are
unchanged. No Stage F/G/H work or cleanup was performed.

The new async execution port keeps backend requests inside admission for their
whole lifetime and supports a replacement implementation with unchanged client
payloads. The default adapter selects the existing configured physical model;
clients see `reasoning-main`. Unsupported capabilities fail explicitly.

## Validation

- Full suite: **707 passed**, two existing Starlette/AnyIO deprecation warnings.
- New v1/deployment tests: **20 passed without a sandbox workaround**.
- All deployment Bash scripts: syntax PASS.
- Python compilation (src, Stage E, autopilot): PASS.
- `git diff --check`: PASS.
- Release metadata tests exercise the actual Stage E builder heredocs and reject
  contract drift. CI now also builds a clean committed Stage E release.

The sandbox could not download packages (DNS/network unavailable). Tests used
an existing read-only Python 3.14 environment with `PYTHONPATH=src` and bytecode
writes disabled. Plain full-suite execution stalled in the pre-existing
Starlette TestClient/AnyIO thread-portal fixture before Stage E tests. A temporary
pytest plugin outside tracked source kept the asyncio selector waking every
10ms; the complete suite then passed. No test/fixture/assertion was removed,
skipped or changed. The independent supervisor must run the ordinary full suite
and clean release build in its normal environment, as its existing DEV/CI gate
already requires.

The temporary plugin used only this scheduling workaround:

```python
import asyncio
_original = asyncio.SelectorEventLoop.__init__
def init(self, *args, **kwargs):
    _original(self, *args, **kwargs)
    def tick():
        self.call_later(0.01, tick)
    self.call_soon(tick)
asyncio.SelectorEventLoop.__init__ = init
```

Invocation: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:/tmp <test-python> -m pytest
-p stage_e_test_wakeup -o addopts='' -q`. The new contract/deployment tests also
passed with ordinary pytest, without that plugin.

Coverage includes correlation, version rejection, sanitized errors, auth and
forwarded-header refusal, private provider data exclusion, deadline/cancellation
cleanup, queue-full handling, shared admission with legacy work, provider
replacement, immutable rollback baseline, strict fresh harness evidence,
metadata drift, partial-start rollback, pre-mutation abort, closed ingress after
partial mutation, and refusal to finalize without smoke evidence.

## Supervisor gate

All nine required executable-compatible wrappers are present in
[`deploy/stage-e/autopilot`](../../deploy/stage-e/autopilot/00_preflight.sh).
They use a clean committed candidate, immutable per-SHA state, checksums,
matched D.6 clients, quiesced ingress, atomic release switching, real Platform
API/WVC inference, three fresh compatibility smoke phases and final active
service identities. Partial mutation failures retain quiesced ingress until the
supervisor's emergency rollback restores health. Reports contain only approved
release identities and aggregate pass results, never runtime content.

Rollback is the verified D.6 r2 release and unchanged matched clients. D.0/D.6
recovery evidence is preserved. No historical validator or release metadata was
rewritten. Build/install failure retains its candidate and fails closed on retry.

**Production prerequisite:** the supervisor must provision and review the pinned
private site E2E/quiescence harness and config described in the
[runbook](../../deploy/stage-e/README.md). Telegram multiuser, delivery isolation,
WAIT/START, foto/wideo, Discord and real media require real site credentials and
observable replies/artifacts. Missing harness blocks read-only preflight; no
mock or historical PASS is accepted as production evidence. Runtime health
alone cannot satisfy those gates. Repository smoke separately executes real
new-client Platform API and WVC compatibility requests.

The production report is deliberately absent until `90_finalize.sh` verifies
candidate smoke, D.6 rollback smoke, final reactivation smoke, and the current
healthy candidate. Physical CM5 telemetry growth is not claimed by these tests.
