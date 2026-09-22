# Stage F — Hermes without patch-in-place

Implement the migration-plan Stage F only.

Before any production mutation, capture an immutable recovery snapshot sufficient to
restore the current Hermes state: exact upstream/local commit identity, dirty diff/patch,
required config/state, and the current Platform integration artifacts. Never publish secrets.

Move queue/context/media integration out of ad-hoc patch-in-place wherever possible and
use Platform/Messaging adapter boundaries or an upstream-supported extension point.
The intended final Hermes source checkout must be clean or have only an explicitly
documented minimal upstream-supported extension, with exact version/commit recorded.

Production gate must cover:
- Telegram multiuser isolation,
- Telegram normal chat plus /foto and /wideo,
- Discord,
- WAIT/START queue UX,
- media dispatch,
- Platform API / Resource Manager integration,
- final Hermes gateway connected/healthy.

Rollback must restore the verified Stage E runtime plus the captured Hermes snapshot.
Do not advance if any currently working messaging path regresses.
