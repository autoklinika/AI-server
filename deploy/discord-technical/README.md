# Discord technical-only production policy

This gate deploys only the user-owned Hermes `ai-platform-messaging` plugin.
It does not restart AI Gateway, AI Bridge, Ollama or ComfyUI.

## Contract

- Telegram remains on the existing Hermes path.
- Authorized Discord text/voice is intercepted before the general Hermes agent.
- Discord answers come only from Platform API `/api/v1/conversation/turn`, which uses Knowledge RAG with
  `context.domain=ecu-repair`.
- Discord photo/video/media and general Hermes commands are blocked.
- Native `/voice` control remains available.
- Text replies include Knowledge citations; voice reads only the answer.

## Production gate

`gate.py all <source-sha>` performs:

1. idle/connectivity/source preflight,
2. baseline snapshot,
3. Hermes-only cutover,
4. real Knowledge/TTS internal smoke,
5. planned rollback,
6. rollback connectivity smoke,
7. reactivation,
8. final real Knowledge/TTS smoke,
9. immutable acceptance evidence.

On candidate smoke failure the baseline plugin is automatically restored.
The gate runs as the Hermes owner and uses the user's systemd bus; no sudo is
required.

## Post-acceptance drift guard

Accepted evidence is not treated as proof that the live Hermes filesystem still
matches the accepted plugin. Operators can verify the live invariant without a
restart:

`gate.py verify <accepted-source-sha>`

The command fails closed when live plugin hashes differ from the immutable
accepted candidate or when Hermes/Discord/Telegram/API connectivity is not healthy.
A newer clean gate worktree may verify an older accepted source SHA only when the
candidate plugin hashes still exactly match that accepted immutable evidence.

To repair drift deliberately:

`gate.py reconcile <accepted-source-sha>`

Reconcile reinstalls the accepted candidate, restarts only Hermes, runs the full
technical quality policy smoke and writes immutable reconciliation evidence.
Re-running `gate.py all <accepted-source-sha>` is idempotent: it verifies an
already matching live plugin or automatically reconciles detected plugin drift.
