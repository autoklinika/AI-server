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
