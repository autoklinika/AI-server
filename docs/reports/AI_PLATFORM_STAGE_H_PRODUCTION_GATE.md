# Stage H production gate — 2026-09-23

Status: **production acceptance PASS**, finalized at approximately 14:33 CEST.
Accepted immutable release: `stage-h-b9362bdae1c3`, source
`b9362bdae1c30b53606d992fcecb575d7de71f4b`.
[PR #65](https://github.com/autoklinika/AI-server/pull/65) tracks publication/merge
and its final checks; deployment remains bound to the accepted source, not later
documentation-only commits. The local completion receipt records the eventual
merge SHA and post-merge CI run: `/home/harrypotter/agent-state/manual-eh/stage-H.complete`.

H began only after G passed all production gates, merged in PR #64 as
`7b73598f198444edd414d8fcc816fdf94fcd98f8`, and post-merge CI
[35855156672](https://github.com/autoklinika/AI-server/actions/runs/35855156672) passed.
Verified G `stage-g-fa6b31e5f7dc` and F `stage-f-d8f68cadd953` remain available.

## Quarantine and retained artifacts

Exactly four unused copies moved from `/usr/local/libexec/ai-server/` into
`/usr/local/libexec/ai-server-quarantine/stage-h-b9362bdae1c3/`:

| File | Bytes |
|---|---:|
| generate_ltx23.py | 13,685 |
| generate_ltx23_base.py | 12,717 |
| generate_ltx23_stage29.py | 10,277 |
| hermes_video_dispatch_stage26.py | 8,184 |

Total: 44,863 bytes. This is removal of obsolete installed paths, not a storage
purge. No files were permanently deleted. The active video wrapper imports its
Stage29/base modules from the immutable release; the audit executes an import-only
probe and verifies their real paths. The installed Stage30 dispatcher, its base,
foto base, resource helper, prompt compilers and generic video generator stay.

The final root audit records **14 registered worktrees, 26 retained releases,
zero active-reference blockers**. Coverage includes installed command/import
references, systemd sources and effective environment files, process argv/env/open
files, worktree state/reference files, release symlinks/manifests and recovery
tooling. Configuration contents and credentials are not published in evidence.
All worktrees, `/opt/ai-bridge`, `/opt/ai-gateway`, all models and domain/state data,
D.0/D.6 recovery snapshots, F/G rollback points and failed GPU candidates/evidence
remain KEEP. The first H build `4919eb928f4c` was never activated; it is retained
as build evidence, not an accepted or failed runtime.

Historical installer references are retained and explicitly require restoring
this quarantine before using those older installers/recovery paths. That boundary
avoids treating a historical reference as an active dependency while preserving
its recoverability. Details: [H runbook](../../deploy/stage-h/README.md).

## Validation

| Check | Result |
|---|---|
| Full local suite | 828 PASS |
| Accepted-source CI, including H build | [35857110342](https://github.com/autoklinika/AI-server/actions/runs/35857110342) PASS |
| Root preflight and reference audit | PASS |
| Immutable build and manifest | PASS |
| Quarantine/cutover, before/after audits | PASS |
| Candidate full smoke | PASS: all four media paths, cleanup and post-media inference |
| Exact four-file restoration and G rollback | PASS: bytes, inode, owner/group, mode, atime/mtime and extended attributes |
| G rollback full smoke | PASS: all four media paths, cleanup and post-media inference |
| H reactivation/quarantine and final full smoke | PASS: all four media paths, cleanup and post-media inference |
| Final reference audit, manifest and phase records | PASS |
| Permanent deletion/purge | NOT PERFORMED |
| External inbound Telegram/Discord | DEFERRED/NOT TESTED; remains paused |
| Physical WVC/CM5 reconnection | NOT TESTED |

The manifest is
`/var/lib/ai-platform/stage-h/b9362bdae1c30b53606d992fcecb575d7de71f4b/quarantine.json`.
Linux no-overwrite rename preserves the original objects; ctime necessarily changes
on rename and is not claimed restorable. Focused tests cover content/metadata
and xattr drift, symlinks/hardlinks, conflicting destinations, the destination
creation race, partial-move restoration, kernel-fault rollback without GPU probes,
and rollback after controller HEAD changes. The root-owned `deployment.json`
points recovery to the original manifest independently of later commits.

All three smokes run the real API/WVC/Hermes/compiler/RM/renderers, with four media
paths per phase and internal message delivery. Kernel cursor guards verified no
new production-parser GPU errors. Ollama PID 2975 and ComfyUI PID 2968 remained
unchanged throughout recovery and H validation. Stable sampled media ownership:
candidate 254, rollback 255, final 254; every such sample had zero Ollama residents.
The protocol verifies empty Ollama inventory before admitting each media execution.
Final Gateway has zero active jobs and zero leases. ComfyUI has zero loaded models,
empty queues, no cleanup flags and 65,011,712 reserved bytes under the unchanged
67,108,864-byte ceiling. No cleanup failure was sampled.

History remained unchanged at captured ID bounds: 40,772 ingest batches, 94,888
raw telemetry rows and 2,719 analysis rows through ID 2751. The analysis hash is
`a0dd6d249462a7eb1a3355c64af5dbc91c5f4d29fa14412de7b7f53ffbdc70ff`;
ingest/raw hashes match the [accepted G report](AI_PLATFORM_STAGE_G_PRODUCTION_GATE.md).
Candidate/final WVC policy correctly returned `skipped/no_fresh_data`. No physical
reconnection or new inbound transport evidence is inferred from these results.

Private phase, kernel-cursor, audit and manifest evidence is under
`/var/lib/ai-platform/stage-h/b9362bdae1c30b53606d992fcecb575d7de71f4b/`.
Local logs/observations are under `/home/harrypotter/agent-state/manual-eh/h-*`.

## Retention and operational boundary

The exact restore/re-quarantine cycle is proven. A **separate retention review no
earlier than 2026-10-23** may consider these four files only after another reference
audit and confirmation that older recovery workflows no longer need them. This is
not approval to purge. Keep the manifest and recovery evidence; do not extend the
review to models, domain state, releases, worktrees or GPU incident evidence by
inference. Required compatibility helpers with stage names remain maintained;
they are not abandoned solely because of their names.

Hermes user service remains stopped (MainPID 0; this host reports a failed stop
state after its normal shutdown), and the analysis timer remains paused. Gateway
and Bridge are managed systemd services. The earlier MES fault mechanism remains
unresolved: no driver fix is claimed. Any new MES/ring/reset/timeout must contain
ingress, preserve evidence and the last verified release, and require physical
power-cycle. Never initiate warm reboot; the MT7925 Wi-Fi/SSH/Tailscale warm-reboot
failure is documented in the [GPU runbook](../runbooks/GPU_RESIDENCY_RECOVERY.md).
