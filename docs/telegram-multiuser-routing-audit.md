# Telegram multi-user media routing incident — diagnostic stage

Date: 2026-09-09. Baseline: `main` at `8ea1da072298ef6753bc41f36f04c1d8a1b4f3c7`.

## Reported symptom

Two Telegram users use the bot. A command from one account generates a photo/video,
but the generated file is delivered to the other account. Treat this as a privacy
incident: use only non-sensitive synthetic media until both accounts are verified.

## Scope and findings

This commit is **diagnostic tooling, not a confirmed fix**. It changes neither the
running gateway nor dispatchers, generators, models, configuration, credentials,
allowlists or production main. Root cause needs installed-runtime evidence.

The checked repository's photo dispatcher and Stage29 video dispatcher capture
`target` before starting a worker, persist it in `request.json`, and use the saved
target for delivery. The Stage26 gateway patch builds the route from `source`.
However, marker presence alone is not behavioral proof; a missing source does not
explicitly fail closed in that patch. The read of the pinned upstream Hermes
`79445a496c86a19332ad786494b8384d2167e2d0` shows explicit numeric Telegram targets
are parsed before home-channel fallback. None of those code reads proves what is
currently running, or establishes the source of the reported misdelivery.

## Run on the AI server

Use the installed Hermes Python (contains PyYAML):

```bash
/srv/ai-data/hermes/hermes-agent/venv/bin/python -B \
  tools/audit_hermes_telegram_routing.py --repo "$HOME/AI-server"
```

No sudo, service restart, bot API call, model invocation, generation, state cleanup,
configuration write or worktree switch is needed. The audit invokes only read-only
`git` and `systemctl` queries and reads local files. Do not paste full `.env`,
configuration, request records, worker logs or journal output into a public issue.
The report deliberately omits prompts, errors, file names, tokens and numeric IDs.
Aliases ID_1, ID_2 etc. are consistent within one report, but not between runs.

The audit reports route-related `.env`/top-level YAML settings; expected vs custom
quick commands; gateway markers; startup process environment; installed dispatcher
comparison to the production baseline; and the latest eight jobs per media type.
It does not fully evaluate nested platform policies or per-profile configuration.

## Interpretation and next gate

- A missing marker, unexpected wrapper, different installed source or different
  initial HERMES_HOME requires verifying the actual runtime before patching.
- A persistent `HERMES_SESSION_CHAT_ID` is suspicious but is not on its own proof
  that it overrode the request route.
- A request/result target mismatch is a local inconsistency. A matching target is
  not proof that this was the invoking chat or that Telegram received the media.
- `/proc/<pid>/environ` represents startup environment, not task-local ContextVars.
- All jobs targeting the home account is evidence to investigate, not proof of
  which account initiated each job. The audit cannot reconstruct absent ingress
  attribution; use harmless tagged A/B tests and per-request tracing as needed.

After identifying the failing boundary, bind the exact event's platform/chat/topic
and caller to each job, reject missing/inconsistent routes before rendering, keep
error notifications bound to that route, and prohibit default-recipient fallback.
Check both users sequentially and with overlapping jobs, including photo editing,
T2V, I2V, HQ, render failure, missing route, and stale global state. Preserve local
inference and the Stage29 tiled-VAE parameters. Do not reinstall an old video stage
or merge to main without explicit approval.

## Tool tests

```bash
python3 -m unittest discover -s tests -p 'test_telegram_routing_audit.py' -v
```

These tests validate the audit and redaction. They do not validate production
Telegram delivery and must not be described as a successful repair.
