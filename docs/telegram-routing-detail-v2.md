# Telegram routing incident — follow-up to runtime audit v1

2026-09-09. Analysis reference: production main `92ceea7bc4bc2b2af30da313b22108e9d686c265` (Stage30).

The host report contains two allowed numeric identities and a home channel matching ID_1. The latest eight image and eight video requests all have ID_1 as both request and result target. There is no ingress identity or timestamp in that report, so it does not prove which requests were initiated by ID_2, or where the reported misrouting occurs. Do not remove the home channel or reset sessions on this evidence alone.

## Correction to v1

The `foto.present=false` result checks the wrong path. Stage28 installs the Python photo dispatcher directly as `/usr/local/bin/hermes-foto-dispatch`, not as `libexec/hermes_foto_dispatch.py`. Also, a Stage30 video dispatcher differs from the Stage29 baseline by design. The actively imported Stage30 primitives are in `hermes_video_dispatch_base.py`; a matching leftover `hermes_video_dispatch_stage26.py` does not verify them. v1 is historical; use the detail audit below for these checks.

## New read-only detail audit

`tools/audit_hermes_telegram_routing_detail.py` compares the actual photo entrypoint, video shell wrapper, Stage30 dispatcher and active base with the pinned main reference. It reports sanitized on-disk gateway route construction and execution helper code, plus a source-file/process-start timing hint. File timestamps are not proof of loaded code.

A strict AST whitelist permits only the small Stage26 string-construction grammar to be evaluated with two fictional chat identities, a fictional topic and an empty identity. There are no Hermes imports, shell executions from the route fragment, Telegram API calls, renders, model calls or production writes. The only subprocesses are read-only git and systemctl queries. Unexpected route code is reported and its probe is refused. String/number literals in code summaries are masked except for a small fixed set of routing syntax strings. The audit does not read `.env`, prompts or job records.

This does NOT test authentication, incoming Telegram events, the loaded gateway, subprocess environment sanitization or actual delivery. An empty-source case without an explicit prefix is not proof that a stale environment survives the runner's filtering.

Run with the existing Hermes Python and `-B` from a checkout with the Stage30 reference commit available. No service restart, main checkout, installation or source patch is required.

## Verification

Eight new unit tests passed locally, including distinct routes, pinned-route detection, refusal of arbitrary calls, literal redaction and the corrected installed path. The dedicated GitHub Actions workflow runs these tests too. A passing test suite is not a confirmed production repair. No main merge is authorized by this diagnostic commit.
