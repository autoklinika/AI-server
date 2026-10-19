# REVIEW ONLY — operator migration and rollback

No installable units are staged. This directory is a design/runbook, not an
installer. No steps that change the host or open GPU nodes were executed in DEV.
Every migration, restart and real device acceptance step below requires separate
operator/root approval and a maintenance window. One existing Gateway RM owns
scheduling; no second coordinator or root daemon.

## 1. Inventory and recovery prerequisites

Run the metadata-only audit from the repository root:

```sh
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m ai_bridge.gateway.host_gpu_audit
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest -q tests/test_host_gpu_audit.py
```

Audit exit 2 means BLOCKED, including when metadata looks nominal. Never run
`os_gpu_boundary.py` for a no-device-open audit: its legacy default probes open
nodes. This audit reads stat, ACL, NSS, /proc status and fixed systemctl show
properties only. It does not read environments, command lines or journal logs.
Missing tools, denied metadata, partial process visibility and unknown autostart
coverage cannot certify isolation. CPU tests are not OS acceptance.

Before any approved migration, operator must record and securely back up:

- All three accounts' primary and supplementary NSS memberships (`id` and the
  authoritative NSS source), including render/video and docker/lxd/admin access.
- Numeric `getfacl` and stat (type, uid/gid, mode, major/minor) for /dev/kfd,
  /dev/dri/renderD128 and every discovered DRM/AMD alias or alternative node;
  inspect /dev/dri, /dev/dri/by-path, bind mounts, containers and udev rules.
- Existing unit files and drop-ins, symlink enablement, active states, Restart,
  dependencies, sockets/timers and user-manager units. Inspect cron, desktop
  autostart, container restart policies and any other engine launch paths.
  Keep originals local: unit contents can contain credentials.
- Current observer behavior and GPU permissions it needs; it is reportedly active.
  Record enabled Ollama/ComfyUI with Restart=always as an autostart hazard even
  when inactive. Confirm these states on the real host, not from DEV assumptions.

Verify an independent SSH session and Tailscale connectivity; document a tested
recovery route before changing sessions. The remote connector depends on
harrypotter's lingering user manager. Preserve linger and remote services. Do not
terminate that user or reboot opportunistically. Plan a connector restart and
reconnection explicitly with the operator if required to refresh groups.

## 2. Approved migration sequence (operator only, not performed)

1. Reserve a maintenance window; capture the backup above and rollback owner.
   Drain the existing RM. Stop competing engine units and deliberately suppress
   their recorded autostart/restart paths. Preserve SSH, Tailscale and connector
   availability. Do not restore competing services automatically after a test.
2. Remove render AND video membership for harrypotter, ollama and ai-vision in
   authoritative NSS, including primary-group membership if applicable. Remove
   unintended ACL grants and world access for every GPU node. Establish persistent
   root:render 0660 device creation policy only after review. /dev/kfd spans AMD
   GPUs: the two-node rule does not prove isolation to one physical GPU.
3. Resolve Docker/LXD access: a principal allowed privileged containers or host
   device mounts can bypass DAC. Restrict that capability or classify the principal
   as trusted admin and narrow the claim. Root/admin remain trusted exceptions;
   unrestricted sudo cannot coexist with a claim of hostile-user isolation.
4. NSS edits do not update existing processes. Inventory /proc status Groups and
   all Gid fields; retire/restart affected sessions, user managers, background
   jobs and services under the availability plan. Existing open FDs can outlive
   DAC changes: operator must inspect holders and eliminate inherited GPU FDs.
   Reconnect through the tested recovery path and verify fresh group snapshots.
   Any hidden processes, unexplained holder or lost connection blocks acceptance.
5. Only then allow the system manager to add render to authorized managed engines.
   SupplementaryGroups EXTENDS NSS groups; it never removes video/render inherited
   from NSS. A user-manager DevicePolicy is not a global boundary. New unmanaged
   processes as each account must have no GPU DAC/ACL access.

## 3. Required reviewed engine profile, not a unit template

Review each fixed argv, environment and account before producing installable
system units. Evidence: `tools/run_rm_systemd_exclusive_three_engine_dev.sh`.
The pilot is not an installer and must not be run as part of this DEV delivery.

| Engine | Grounded pilot entry | Remaining acceptance requirement |
| --- | --- | --- |
| Ollama | /usr/local/bin/ollama serve, User=ollama | Pin environment/model directory, local endpoint and immutable executable |
| ComfyUI | /opt/comfyui/venv/bin/python /opt/comfyui/ComfyUI/main.py, User=harrypotter | Freeze full argv/directories, disable unreviewed custom nodes; review account separation |
| Vision | /opt/comfyui/venv/bin/python -I plus rocm_test_worker.py | Pilot worker is checkout-owned; no trusted production command established |

Required system-manager properties: `DevicePolicy=closed`, reset inherited
DeviceAllow entries before setting exactly `/dev/kfd rw` and
`/dev/dri/renderD128 rw`; `SupplementaryGroups=render` only after NSS cleanup;
explicit non-root User and primary Group; `PrivateDevices=no`,
`NoNewPrivileges=yes`, `KillMode=control-group`, `Restart=no`, bounded runtime and
stop timeout. Inspect effective merged properties, not merely a source file.
Closed also permits standard pseudo-devices, not only the two GPU nodes.

Executable, worker, interpreter, unit and parent-directory ownership must prevent
unmanaged users changing authorized code. Never install a root service that runs
a user-writable script. Even a non-root GPU-authorized unit is a bypass if its code
or arguments are user-controlled. Limit the existing RM's system-manager authority
to reviewed fixed profiles; no arbitrary systemd-run, argv, environment, unit
editing or engine API launch authority for unmanaged callers. Verify PID/starttime,
boot ID, InvocationID and cgroup ownership before admission. No permanent install
is included because these prerequisites are unresolved.

## 4. Separate real-host acceptance (requires explicit approval)

Keep N1 blocked throughout. Operator records each result with identity, boot,
time, unit properties, cgroup and exact node major/minor; do not publish secrets.

| Test | Required evidence |
| --- | --- |
| Each of three fresh unmanaged accounts | Read and write opens denied for both nodes; include fresh login and user-manager jobs |
| Old sessions/background tasks | No remaining render/video snapshots or GPU FDs outside approved units |
| Managed Ollama, ComfyUI, Vision, one at a time | Authorized node access succeeds; system-manager cgroup owns every worker/child; effective exact rules verified |
| Alternative nodes, aliases, bind mounts, containers | Unmanaged access denied; no Docker/LXD privileged escape; other GPU nodes denied in managed cgroups |
| Autostart and restart | No competing engine from enabled units, timers, sockets, user units, cron or containers; review persistence separately |
| Stop and handoff | Entire cgroup exits, no inherited descriptors or unexpected holders; unknown observations block next engine |
| Remote availability | SSH, Tailscale and connector reconnect after planned session refresh |

Device tests and workloads are future operator actions, not CPU tests. A managed
positive alone cannot demonstrate unmanaged denial. An empty KFD snapshot cannot
prove safe driver queue release. Physical E_safe remains NO-GO;
NonApprovingSafetyAdapter stays False, GPU_REUSE_SAFE=NOT_VERIFIED, no N1 grant.

## 5. Rollback (operator only)

On failed acceptance, leave RM admission blocked and stop newly authorized engines.
Using the saved authoritative records, restore exact NSS primary/supplementary
memberships, original ACLs/ownership/modes and persistent device rules; restore
unit files/drop-ins and the recorded enablement/restart configuration. Reload the
system manager only as part of the approved rollback. Refresh affected processes
under the same remote-availability plan; group restoration also needs new snapshots.
Restore only the previously approved active-service set in controlled order, never
blindly start all enabled engines. Verify SSH/Tailscale/connector and original
service availability, then rerun metadata inventory. Document any restored bypass:
rollback restores baseline availability, not isolation or physical E_safe approval.
