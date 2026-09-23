# GPU residency recovery and Stage F validation

A transition failure is fail-closed, not an invitation to release the lease.
Keep the last verified release and record the Gateway status, boot ID, kernel
journal cursor, provider inventories, ComfyUI queue/memory and worker identities.
Do not erase the marker or restart Ollama as routine handoff behavior.

1. Pause Hermes, analysis timer and all other inference/media producers. Stop and
   reap external workers so none can submit another ComfyUI prompt. Preserve their
   job directories and logs. An empty queue alone cannot prove a worker is gone.
2. On any new MES failure, ring-full, GPU reset or timeout, stop ingress immediately
   and mark a GPU blocker. Do not continue model/media probes or claim a driver fix.
3. When the kernel is healthy, drain existing requests. Explicitly unload every
   Ollama resident using `POST /api/generate` with model name, no prompt,
   `keep_alive: 0`, `stream: false`; verify `/api/ps` has zero models.
4. Verify ComfyUI queue empty, request `/free` with both flags true, and poll
   `/system_stats` until every device reports `torch_vram_total` within its configured idle ceiling
   (production: 32 MiB persistent HIP BLAS workspace; default: zero). Keep closed
   on missing evidence, a busy queue or timeout. No service restart is needed.
5. Only after workers are proven stopped and both providers free, archive the
   residency marker with the recovery evidence, stop the Gateway, remove its live
   marker, and start the verified release. Verify empty RM state before resuming
   producers. This is an explicit recovery operation, never automatic TTL cleanup.

Acceptance order: full local suite; immutable build/install; kernel cursor and
production smoke; bounded Qwen inference; admitted media; no new kernel errors;
ComfyUI idle/free; Qwen loads and infers again; planned rollback and rollback smoke;
reactivation/final smoke; reports and GitHub CI/review/merge. The rollback restores
snapshot client/source/config bytes without depending on a healthy candidate.
Rollback to Stage E does not inherit Stage F isolation: keep media ingress paused
and manually establish empty provider residency before any bounded rollback
compatibility probe. Never run the legacy heavy-media smoke with resident Ollama.

Messaging evidence is **SYNTHETIC/INTERNAL**. Real external inbound Telegram and
Discord transport remains **DEFERRED/NOT TESTED**, never PASS. Existing outbound
compatibility evidence and historical D.6 results do not change that boundary.


For a repairable closed candidate, the Stage F supervisor can build a replacement
while retaining the original verified Stage E recovery snapshot. It refuses live
media workers, stops producers and the Gateway, uses the reviewed residency code
with the verified E Python to unload/free both providers, archives the latch, and
only then activates the replacement. It never restarts Ollama. A failed cleanup
leaves ingress closed. Do not restore or discard failed harness evidence merely
because the render produced an artifact; cleanup is part of acceptance.
