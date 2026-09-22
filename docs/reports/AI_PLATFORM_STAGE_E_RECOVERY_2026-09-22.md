# Stage E recovery investigation

Production validation remains pending. D.6 r2 is the verified rollback release;
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
