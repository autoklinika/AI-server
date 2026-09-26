# Stage O — AI Control Center

Stage O is a runtime-only production release for AI Control Center.
It preserves the accepted Stage M database/schema contract 0005_crt_projection
and does not run Alembic migrations or mutate Knowledge/ERS/CRT data.

The first production baseline is pinned to stage-m-8e6d21eff33d. After a
Stage O release is accepted, the next Stage O patch uses that accepted release
as its rollback baseline. An active Stage O release is trusted only when its
immutable release metadata and matching accepted.json evidence agree. Unaccepted
or unknown active releases fail closed, except for the explicit recovery rollback
path after a failed smoke.

Gate sequence: preflight, immutable build, cutover, smoke, rollback,
rollback smoke, reactivation, final smoke and finalize.

Control Center is exposed through the LAN-bound AI Bridge at /control/.
The browser transport forwards only an explicit allowlist to the loopback
Platform API. Arbitrary /ai, shell, sudo and infrastructure backends are not exposed.

Before production use, install the updated privilege bridge once so Stage O
is authorized from the dedicated agent/stage-o worktree.
