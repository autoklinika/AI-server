# Stage E recovery investigation

Production validation: **PASS** for `stage-e-38fff86f7704` after the complete
candidate/rollback/reactivation cycle. D.6 r2 is the verified rollback release;
D.0/D.6 releases, client bundles and recovery evidence are retained.

The previous supervisor's `40_rollback` passed but `50_rollback_smoke` failed.
Its `BLOCKED_ROLLBACK_FAILED` status combines those two exit codes; it does not
mean release restoration itself failed. Fresh privileged read-only preflight,
Gateway/Bridge health, Hermes connectivity, matched client bytes, WVC inference,
Hermes one-shot inference and media preflight passed on the actual D.6 runtime.

The messaging smoke reproduced a concrete failure: Telegram outbound delivery
succeeded, while bare `hermes send --to discord` failed because no Discord home
channel was configured. The historical rollback runtime retained completed WVC,
Hermes and three synthetic messaging inference jobs immediately before its smoke
failure, consistent with the reproduced outbound failure. Historical candidate
logs suppress error details, so an exact historical candidate failure location
cannot be established from those logs alone.

The repair resolves the Discord home destination when configured; otherwise it
accepts only a single explicitly configured free-response channel also present
as a channel in the existing directory. Ambiguous or absent configuration fails
preflight. It does not change Hermes configuration or select an arbitrary DM or
user. Destination identifiers and message bodies are never logged or committed.
Delivery now requires structured success with no skipped/error result, because
the installed CLI can return zero for skipped delivery. Safe local code locations
and exception classes identify future gate failures without dumping runtime data.

The remote repair `f709cd2` was incorporated by fast-forward. It isolates Hermes
one-shot correlation during smoke and restores messaging ingress in `finally`;
it also permits rollback from a dangling candidate symlink. The ordinary full
suite passed without the old scheduling workaround before the additional gate
repair. New regression tests reject skipped delivery and ambiguous destinations.
The full production cycle must still pass before Stage E can be completed.


Independent review also identified a second supervisor failure: after the planned
rollback smoke, an emergency rollback following reactivation reused the exclusive
`rollback-smoke-started.json` filename. It could fail before checking runtime even
when restore succeeded. Repeated recovery smoke now writes separate immutable
`recovery-smoke-<nonce>` records. It never overwrites a failed attempt or supplies
missing planned-cycle evidence to finalization. Regression tests cover both a
prior successful and prior failed planned rollback smoke.


The first repaired candidate (`a1ece13`) passed CI/build/cutover, but live and
recovery smoke failed at the new one-shot isolation assertion. D.6 restoration
passed and Hermes reconnected. User-systemd records show Hermes exits with
status 1 on shutdown, leaving `ActiveState=failed` after stop. Isolation now
requires an inactive/failed state **and** zero main/control PIDs **and** no
remaining cgroup processes, rather than interpreting `failed` as still running.
The smoke still fails for a surviving process. No client code or service policy
was changed. The failed candidate and its immutable evidence remain preserved.


Process absence uses the kernel's recursive `cgroup.events` populated field;
read errors fail closed, and a missing event file is accepted only when the
cgroup directory is also gone. This avoids Python glob traversal suppressing
inspection errors. Semantics: [Linux cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html#un-populated-notification).


Final result: all nine production steps passed for source
`38fff86f7704fcee92d66a750c033a9ec69ff084`. Candidate smoke, fresh D.6 rollback
smoke and final candidate smoke each exercised real inference, outbound delivery
and admitted media. Final Gateway/Bridge/ComfyUI identities were stable, Hermes
connected, and queues/leases idle. Independent review and exact-source CI passed
(764 tests). The earlier failed candidates and immutable attempts are retained
for diagnosis; none was converted into PASS. See the [production gate](AI_PLATFORM_STAGE_E_PRODUCTION_GATE.md).

Validation logs and temporary render artifacts are classified KEEP outside Git
until the Stage H reference/retention audit; they support this recovery cycle and
must not be confused with production/domain data. D.0/D.6 recovery remains protected.
