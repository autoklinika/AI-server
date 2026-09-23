# Stage H — reversible legacy quarantine

Status: production acceptance PASS for `stage-h-b9362bdae1c3`: candidate, exact
restore/G rollback, reactivation and final audits passed. See the
[production report](../../docs/reports/AI_PLATFORM_STAGE_H_PRODUCTION_GATE.md). G is accepted
and merged (PR #64, post-merge CI 35855156672 PASS). Verified baseline:
`/opt/ai-platform/releases/stage-g-fa6b31e5f7dc`; F `stage-f-d8f68cadd953` is retained.

Only these unused copies are candidates under `/usr/local/libexec/ai-server/`:

- `generate_ltx23.py`
- `generate_ltx23_base.py`
- `generate_ltx23_stage29.py`
- `hermes_video_dispatch_stage26.py`

The current video wrapper uses the immutable release's Stage30/Stage29/base
modules. The installed Stage30 dispatcher and its base, foto base, resource helper,
prompt compilers and generic `generate_video.py` are active dependencies and stay.
All releases, registered worktrees, models, domain/state data, D.0/D.6 snapshots,
F/G rollback points and GPU incident evidence remain in place. Legacy service
folders and historical installers remain available for recovery.

Every gate uses the clean/pushed `agent/stage-h` SHA through
`/usr/local/libexec/ai-platform/autopilot-root-exec H <step>.sh <sha>` in order:
`00_preflight`, `10_build_install`, `20_cutover`, `30_smoke`, `40_rollback`,
`50_rollback_smoke`, `60_reactivate`, `70_reactivate_smoke`, `90_finalize`.
Preflight/build/switch/finalize scan installed callers, systemd/configuration,
process argv/open files, registered worktrees, release manifests and recovery
scripts. Active references block quarantine; historical references remain recorded
with a mandatory restore-before-use instruction.

The immutable manifest is `/var/lib/ai-platform/stage-h/<sha>/quarantine.json`.
Files move to `/usr/local/libexec/ai-server-quarantine/stage-h-<sha12>/` with Linux
`RENAME_NOREPLACE`, preserving inode, bytes, mode, owner/group, atime/mtime and
extended attributes. Rename necessarily updates ctime; no claim is made that
ctime is restorable. Symlinks, hardlinks, content/stat drift, missing/both copies,
conflicting restore destinations and cross-filesystem moves fail closed.
Interrupted partial moves can be restored or resumed using the same manifest.
No overwrite and no purge operation exists.

Planned rollback restores all four files exactly and runs the full accepted-G
compatibility smoke. Reactivation quarantines them again and repeats the smoke.
Each smoke uses kernel cursor guards and four real media paths with verified
Ollama drainage, authoritative cleanup and post-media inference. Hermes/external
inbound and the analysis timer remain paused. Messaging is SYNTHETIC/INTERNAL;
external inbound Telegram/Discord is DEFERRED/NOT TESTED; physical WVC reconnection
is NOT TESTED. A kernel fault requires paused containment to verified G, no further
GPU probes, no reboot, and an operator physical power-cycle.

## Retention and historical recovery

Do not invoke older installers or D.0/D.6/F recovery tooling against a quarantined
host until the H manifest has been restored through `40_rollback.sh`. Their source
and original snapshots are retained; H does not rewrite those recovery artifacts.
A later purge may be considered only after the H rollback/reactivation cycle,
a separately approved retention period, and a new reference/recovery audit. This
stage does not automatically delete the quarantine, its manifest, any old release,
worktree, model, incident evidence or stateful/domain data.

Rollback resolves the original manifest from the root-owned
`/var/lib/ai-platform/stage-h/deployment.json`, independently of later controller or
documentation commits. Repeated explicit rollback writes a separate recovery
receipt without overwriting the original acceptance evidence. The bridge still
requires a clean, pushed, authorized controller HEAD; it does not require rewinding
that branch to the deployed source merely to restore the four quarantined files.
