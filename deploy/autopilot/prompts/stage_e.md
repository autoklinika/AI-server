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

Production gate must prove that a new client no longer needs Ollama/Hermes/ComfyUI URLs,
that provider choice stays behind Platform API, and that existing WVC, Telegram multiuser,
Discord and media behavior remains operational.

Rollback target is the last verified Stage D.6 production release and its matched clients.
Do not remove Stage D compatibility or recovery evidence.
