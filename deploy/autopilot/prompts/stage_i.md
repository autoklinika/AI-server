# Stage I — Observability & operations hardening

Implement Stage I only. It is the P2 observability step that follows completed Stage H and precedes Knowledge Service.

Goals:
- add a bounded metadata-only Platform API observability contract;
- expose request counters/latency, Resource Manager queue/admission, active lease count, GPU residency summary, bounded recent-job timing/state summaries, logical provider/model/node, process RSS/CPU and job-retention metadata;
- extend Platform health with lease/GPU state;
- emit structured Platform-request log records correlated by request ID;
- keep all existing provider, scheduler, messaging, WVC and media semantics unchanged.

Hard privacy/safety rules:
- never persist or expose prompts, response bodies, auth headers/tokens, chat IDs, user content, exception text or raw dynamic URLs;
- avoid high-cardinality labels; only bounded counters and existing technical IDs are allowed;
- no new public listener, firewall rule, model, GPU policy, persistent metrics database, Prometheus/Grafana dependency or Knowledge Service;
- do not change WVC advisory/control policy.

Release contract:
- stage=I, migration=observability-v1, observability_contract_version=1;
- verified rollback is stage-h-b9362bdae1c3;
- preserve active Hermes ingress and ai-bridge-analysis.timer across switch/rollback/reactivation;
- candidate smoke must prove /api/v1/observability; rollback smoke must prove the endpoint is absent on H;
- run fresh Platform API, WVC, Hermes and messaging-boundary inference smoke plus media preflight/client integrity;
- do not run an additional heavy LTX render: Stage I does not modify media code and fresh real Telegram/Discord foto/wideo evidence exists from post-H acceptance. Do not relabel that historical evidence as a fresh Stage I media PASS.

The Stage I root bridge may be used only after its allowlist extension has passed CI, merged to main and been installed from clean current main. Never bypass the privilege bridge.
