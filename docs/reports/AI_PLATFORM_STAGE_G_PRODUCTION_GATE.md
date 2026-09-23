# Stage G production gate — 2026-09-23

Status: **BLOCKED by a new GPU MES failure during final validation. G is not accepted or merged; H has not started.** Candidate `stage-g-7ccc9c14da33`, source
`7ccc9c14da3371751e1e84e38bd33c5be75ec8c8`, [PR #64](https://github.com/autoklinika/AI-server/pull/64).
Rollback target: verified `stage-f-d8f68cadd953`.

WVC policy, sensor/fan interpretation, telemetry and analysis schemas, persistence,
API and CLI implementation now live in `ai_bridge.domains.wvc`. Platform composition
uses a domain adapter; compatibility module imports and endpoint contracts remain.
No database schema migration or history rewrite was performed. The analysis policy
returns a successful `skipped/no_fresh_data` on an empty selected window, without
inference or placeholder history. Fresh data resumes normal advisory processing.
Cross-process locking and existing identities prevent duplicate analysis.

## Evidence boundary and domain observations

The actual production policy returned `skipped/no_fresh_data` for the candidate
window **2026-09-23 08:30–08:45 UTC**. The latest stored sample was
**2026-09-21 18:03:33.042432+02:00**. This is valid no-fresh-data behavior, not a
platform failure. **Physical WVC/CM5 reconnection: NOT TESTED.** Offline tests
separately prove fresh ingest after an empty window, retransmission deduplication,
analysis resumption/reuse, cross-process duplicate prevention and retry after a
provider failure. They are not represented as physical-device evidence.

Captured central history remains identical at its original ID bounds:

| Table | Rows | Captured maximum ID | Historical SHA-256 |
|---|---:|---:|---|
| ventilation_ingest_batches | 40,772 | 40,772 | `a40fce3110336b8e7c7abf8f70bbfa1e30283f53e4ae2c5cacfaad9bc4ae8302` |
| ventilation_telemetry_raw | 94,888 | 94,888 | `6fbb0092d3e44b91201a8f3d4042eac7922002da1d7912b3ca440cb825a7dc7c` |
| ventilation_analysis_runs | 2,713 | 2,745 | `590c28d2f51a77d2a663fe5795966a2dad0420c227988afb1515ffc1ae43f7b1` |

Hashes cover every captured row, including stored payloads, without publishing
those payloads. Append-only growth is allowed; changes/removals fail validation.
The difference between analysis count and maximum ID predates this stage.
The F rollback timer ran at **11:09:15 CEST** and appended one zero-sample
`insufficient_data` result (ID 2746), preserving legacy behavior. It is retained as
history, not deleted to make counts match. Final G policy returned
`skipped/no_fresh_data` for **08:45–09:00 UTC** without adding another row. The actual
G systemd timer also logged a successful skip at **10:45:30 CEST**, proving the
installed CLI path, not just the direct policy probe. Analysis count after rollback:
2,714; all 2,713 captured historical rows remain byte-equivalent under the hash check.

Messaging E2E remains **SYNTHETIC/INTERNAL** using real installed Hermes, Gateway,
RM, Qwen, image/video dispatchers and renderers with internal delivery recording.
Separate outbound compatibility probes do not establish inbound transport.
**External inbound Telegram/Discord remains DEFERRED/NOT TESTED.** No GPU driver
fix is claimed; the F residency protocol remains in force.

## Validation

| Check | Result |
|---|---|
| Candidate full local suite | 807 tests PASS |
| Containment/recovery full local suite | 808 tests PASS |
| Candidate CI | PASS, [35838532756](https://github.com/autoklinika/AI-server/actions/runs/35838532756) |
| Preflight, build/install, cutover | PASS |
| Candidate compatibility/internal E2E | PASS: four media paths and post-media inference |
| Planned F rollback and full smoke | PASS: four media paths and post-media inference |
| G reactivation | PASS |
| Final full smoke | **FAIL/BLOCKED: new MES fault after final video; no acceptance record** |
| Production finalize | NOT RUN: GPU blocker |
| Paused containment rollback to F | Restored verified F; no GPU probes or ingress resume; not an acceptance smoke |
| Final branch CI | Pending; code evidence only |
| Merge/post-merge CI | NOT RUN: PR remains draft |

Each full smoke includes Platform API, WVC inference routing, real Hermes CLI,
configured outbound messaging, four internal media paths (image, video, image edit,
video), cleanup and post-media inference. Kernel cursor guards stop ingress on new
GPU faults. Provider identities are checked before/after every smoke and against
the baseline: Ollama PID 3054, ComfyUI PID 30508. G changes neither provider process.

Private immutable evidence is under
`/var/lib/ai-platform/stage-g/7ccc9c14da3371751e1e84e38bd33c5be75ec8c8/`.
Sanitized local logs/observations are under
`/home/harrypotter/agent-state/manual-eh/g-*7ccc9c1*`.
See [domain architecture](../architecture/WVC_DOMAIN.md),
[gate/runbook](../../deploy/stage-g/README.md) and
[GPU recovery policy](../runbooks/GPU_RESIDENCY_RECOVERY.md).

## New kernel failure and containment

ComfyUI logged `Prompt executed in 213.89 seconds` at **11:21:29 CEST** for the
final video. At **11:21:36 CEST**, the kernel began reporting:

```
MES failed to respond to msg=MISC (WAIT_REG_MEM)
failed to reg_write_reg_wait
```

The cursor guard stopped Gateway and the analysis timer, stopped Hermes and marked
`BLOCKED_GPU`. The harness reaped its workers; none remained on inspection. Final
smoke returned failure and wrote no accepted final-phase record. No subsequent
inference, media, unload/free or provider-restart probe was performed.

The final observer recorded 334 samples, including 259 stable media-ownership
samples with **zero Ollama residents**. Its last successful samples at 11:21:30–32
showed an empty Comfy queue but four Comfy models still resident; cleanup was not
verified. Later samples timed out or could not reach the stopped Gateway. Candidate
and rollback observers respectively recorded 259 and 258 stable media samples,
also with zero Ollama residents. Polling does not prove every instant, but the new
failure occurred despite enforced residency isolation and no observed Ollama
residency overlap. The exact GPU failure mechanism remains unresolved. The F repair
removes a demonstrated architectural hazard; it is **not a GPU driver fix or proof
that heavy media cannot trigger another fault**.

A reviewed controller repair (`4fca99a`) adds a distinct paused rollback path.
After a same-boot kernel fault it validates only verified F, stops all inference
producers, requires no surviving external workers, switches service bytes back to
F and starts only AI Bridge telemetry/history. It calls no Ollama/Comfy API, leaves
both providers untouched, retains both block markers and never runs or labels a
smoke PASS. The full 808-test suite includes this no-probe/no-resume invariant.

Contained runtime:

- `/opt/ai-platform/current` → `stage-f-d8f68cadd953`.
- Gateway stopped; analysis timer/service inactive; Hermes MainPID 0 and no workers.
- AI Bridge telemetry/history healthy; central data retained, including the row
  appended by the F rollback timer.
- Ollama PID 3054 and ComfyUI PID 30508 unchanged; no restart attempted after fault.
- F, E, D.0/D.6 recovery releases/evidence and the failed G candidate are preserved.
- G remains draft; H NOT STARTED. External inbound remains DEFERRED/NOT TESTED.

The fault marker and kernel cursor evidence remain under `/var/lib/ai-platform/stage-g`.
Private provider/kernel journals, observer timelines and the containment log are
under `/home/harrypotter/agent-state/manual-eh/` (`g-final-kernel-fault-20260923.log`,
`g-final-provider-journal-20260923.log`, `g-contained-rollback-4fca99a.log`). Failed
harness evidence remains under `/tmp/stage-f-internal-media-476iayg6` and the private
phase directory; do not quarantine it during cleanup.

Resume requires a controlled host/GPU recovery window and fresh bounded inference,
explicit unload and kernel evidence before any new heavy-media acceptance cycle.
No automatic reboot/reset was attempted. Keep ingress paused until that recovery
is established; do not clear markers or mistake endpoint readiness for GPU health.
