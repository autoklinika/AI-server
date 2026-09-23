# Stage G production gate — 2026-09-23

Status: **Production acceptance PASS after operator cold-boot recovery.** Accepted
release `stage-g-fa6b31e5f7dc`, source `fa6b31e5f7dcc7a67fe1928e7bf099f2256225c2`,
[PR #64](https://github.com/autoklinika/AI-server/pull/64). Finalized at approximately
13:27 CEST on 2026-09-23. Merge and post-merge CI are tracked below. H has not started.
Verified rollback target remains `stage-f-d8f68cadd953`. The earlier candidate
`stage-g-7ccc9c14da33` remains rejected; its incident/evidence is retained below.

## Accepted cold-boot recovery validation

| Check | Result |
|---|---|
| Full local suite | 815 PASS, including delayed cleanup, final settling window, stale external-use failure, zero-ceiling mismatch and kernel containment |
| Source CI | PASS, [35850680868](https://github.com/autoklinika/AI-server/actions/runs/35850680868) |
| Managed Gateway handoff | PASS: archived blocked diagnostic lease/marker, stopped PID 10872, verified provider cleanup, restored F systemd Gateway |
| Bounded isolated RM video | PASS: 1s 640x384 MP4, Ollama empty, authoritative cleanup, zero leases, kernel cursor clear |
| Preflight/build/cutover | PASS |
| Candidate full smoke | PASS: four media paths, cleanup and post-media inference |
| Planned F rollback and full smoke | PASS: four media paths, cleanup and post-media inference |
| G reactivation and final full smoke | PASS: four media paths, cleanup and post-media inference |
| Finalize | PASS: all three accepted phase records and history hashes verified |
| External inbound Telegram/Discord | DEFERRED/NOT TESTED; Hermes user service remains stopped |
| Physical WVC/CM5 reconnection | NOT TESTED |
| Merge/post-merge CI | Pending documentation CI and merge |

All three fresh smoke phases verify unchanged provider identities (Ollama PID
2975, ComfyUI PID 2968) and no new production-parser kernel matches through their
final journal cursors. Sampled stable media ownership: candidate 243, rollback
252, final 254; every such sample has zero Ollama residents. These are sampled
observations plus the enforced admission protocol, not proof of a driver fix.
Final managed Gateway has zero active jobs and zero leases; ComfyUI has zero
loaded models, empty queues, no pending cleanup and 65,011,712 reserved bytes,
within the unchanged 67,108,864-byte production ceiling.

Fresh WVC candidate/final policy probes returned `skipped/no_fresh_data`; physical
reconnection was not exercised. The resumed baseline captured 2,719 analysis rows
through ID 2751 with hash
`a0dd6d249462a7eb1a3355c64af5dbc91c5f4d29fa14412de7b7f53ffbdc70ff`.
Ingest/telemetry counts and hashes below are unchanged. All resumed baseline rows
were verified through finalization. Background rows accumulated before producers
were paused are retained; no history was rewritten to match older counts.

The cold boot had also restarted the Hermes **user** unit. Recovery's stopped-unit
check refused to proceed until it was stopped and MainPID was zero. It remained
stopped throughout all fresh acceptance gates. The analysis timer is also paused.
Real one-shot inference, configured outbound probes and synthetic/internal E2E
ran without reopening external inbound.

Fresh immutable evidence:
`/var/lib/ai-platform/stage-g/fa6b31e5f7dcc7a67fe1928e7bf099f2256225c2/`.
Isolated evidence:
`/var/lib/ai-platform/stage-g/isolated-video-evidence-342ddcbb63524fa7bbc7b0beeab60678/`.
Isolated MP4: `/tmp/stage-g-isolated-video-6r735lfl/ltx23-20260923-125021-92a14215.mp4`.
Local logs/observations: `/home/harrypotter/agent-state/manual-eh/g-*fa6b31e*`;
managed diagnostic evidence is also in `gpu-isolation-video/managed-isolated-pass.json`.
The historical GPU fault is unresolved; a new MES/ring/reset/timeout must still
latch immediately, stop ingress, preserve the last verified release and require
physical power-cycle. Never issue a warm reboot.

## Earlier attempt and retained incident evidence

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

## Earlier rejected candidate validation

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
| Recovery source CI | PASS, [35842782783](https://github.com/autoklinika/AI-server/actions/runs/35842782783), source `4fca99a`; code evidence only |
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
both providers untouched, retains both block markers (the persistent residency latch was confirmed present) and never runs or labels a
smoke PASS. The full 808-test suite includes this no-probe/no-resume invariant.

Contained runtime after the earlier fault (superseded by the accepted recovery above):

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

## Resumed cold-boot cleanup investigation

The operator performed a physical power-cycle; no automated reboot is authorized.
The resumed boot `5d7c0564-8190-4194-9b09-4877d8943184` has zero matches from the
production `gpu_watch.py` parser as of investigation. The isolated 1s 640x384
video produced a valid MP4, but cleanup did **not** pass: manual Gateway PID
10872 used default configuration (no GPU-related environment and no `.env`),
including a zero-byte allocator ceiling. ComfyUI eventually reported zero loaded
models, empty queues, no pending flags, and 65,011,712 reserved bytes. The
production unit's unchanged 67,108,864-byte ceiling was absent from this process.
The lease correctly remained pinned after the 90-second cleanup timeout.

The provider journal also records repeated cache resets from 12:09:19 through
12:10:48 CEST. The old loop posts `/free` after every failed poll; this re-arms
flags and can obscure clean-state observation while the worker resets/collects.
The exact historical per-poll allocator/flag values were not captured, so the
journal alone cannot attribute each failed poll to flags. The configuration
mismatch is independently sufficient to reject the observed 62 MiB clean state.
The repair preserves all evidence predicates and memory thresholds, spaces
wakeups with bounded read-only settling, keeps the original deadline, and exposes
last cleanup evidence. Focused tests reproduce both delay and permanent failure.

Warm reboot has failed to restore SSH/Tailscale access on the host's MediaTek
MT7925 Wi-Fi (`wlp194s0`); physical power-cycle restores access. Root cause is
unproven (firmware/AGESA/PCIe/device-reset possibilities). See the updated GPU
runbook. This is not evidence of a driver fix. At investigation, G remained
unaccepted pending the fresh isolated/candidate/rollback/reactivation gates that
subsequently passed above; H had not started.
Local investigation evidence: `/home/harrypotter/agent-state/manual-eh/gpu-isolation-video/`.
