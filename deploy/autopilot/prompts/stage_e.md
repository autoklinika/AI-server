# Stage E — Platform API

Implement the migration-plan Stage E only.

Required v1 boundary:
- `/api/v1/ai`
- `/api/v1/jobs`
- `/api/v1/models`
- `/api/v1/systems`
- `/api/v1/health`

Required behavior:
- request/context envelope and correlation IDs,
- normalized error contract,
- stable job state representation backed by the existing Resource Manager v2,
- aggregated health that does not expose secrets, prompts or backend-private data,
- auth hooks/policy boundary even if the first policy remains simple,
- versioned contract tests,
- compatibility paths remain available during migration.

Production gate must prove that a new client no longer needs Ollama/Hermes/ComfyUI URLs
and that provider choice stays behind Platform API.

Stage E changes the Platform/Gateway boundary, not Hermes or messaging client code. Its
fresh autonomous compatibility evidence must therefore exercise the boundary it changes:
- real Platform API inference/jobs/models/systems/health,
- real WVC -> Gateway -> Qwen,
- real Hermes one-shot inference through the compatibility Gateway,
- correlated multi-client Hermes-namespace requests with distinct request/job IDs,
- Telegram and Discord connected state plus successful outbound delivery to configured
  home targets,
- matched D.6 messaging/media client bytes unchanged,
- real media render under Resource Manager admission.

The already-validated D.6 external Telegram multiuser, WAIT/START, /foto, /wideo and
Discord request/reply user paths remain the compatibility baseline in Stage E because
Stage E does not mutate those clients. Do not relabel that historical user-path evidence
as a fresh Stage E external-user PASS. Full fresh inbound multiuser/user-path validation
is mandatory in Stage F, where Hermes/messaging integration is actually changed.

Rollback target is the last verified Stage D.6 production release and its matched clients.
Do not remove Stage D compatibility or recovery evidence.
