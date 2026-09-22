# Stage H — Legacy cleanup

Implement the migration-plan Stage H only.

This is a controlled cleanup, not a feature stage. Every candidate removal requires a
reference audit covering systemd/runtime, git worktrees, release symlinks/manifests and
known recovery tooling.

Safety rules:
- quarantine before irreversible deletion,
- retain enough metadata to restore every quarantined item,
- preserve D.0 and D.6 recovery evidence,
- preserve the most recent verified Stage F/G rollback points until the Stage H rollback
  cycle itself is proven,
- do not remove models merely to save space unless they are proven unused and outside
  required rollback paths,
- do not delete stateful/domain data.

Production gate must prove no active runtime path references quarantined artifacts,
all services/Platform API/messaging/media/WVC compatibility smoke remain healthy, and
rollback can restore the quarantined set exactly.

Only after the rollback/re-activation cycle is PASS may the final report recommend a later
retention-based purge. This Stage must not perform that irreversible purge automatically.
