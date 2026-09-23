# Shared local GPU residency ownership

The September 22 incident began seconds after a heavy ComfyUI render while Ollama
retained a model with `OLLAMA_KEEP_ALIVE=-1`. The architectural defect was treating
finished inference as released GPU memory. The timing supports overlapping
residency as the primary repair target; it does not establish a fixed driver or
prove the exact kernel failure mechanism. Reboot restored ROCm gfx1150 detection,
short inference and explicit model unload (operator-verified September 23).

Resource Manager media-capable reservations are exclusive even when configured
LLM concurrency exceeds one. Priority/FIFO ordering remains unchanged. Existing
HTTP/streaming work drains before the reservation becomes active; its prompt
compiler can use Ollama under the same reservation. The external ComfyUI phase
pins ownership before any asynchronous provider call. New LLM jobs remain queued;
leased LLM calls cannot bypass the media pin.

Before returning an external use token, the Gateway checks ComfyUI idle, lists
Ollama residents, requests each model's unload with an empty `/api/generate`
request and `keep_alive: 0`, and polls `/api/ps` to an empty list. No Ollama restart
is part of this protocol. See [Ollama generate](https://docs.ollama.com/api/generate)
and [resident inventory](https://docs.ollama.com/api/ps).

On explicit external-use completion, it checks ComfyUI's queue, sends `/free`
with both `unload_models` and `free_memory`, then verifies zero loaded models, no
pending cleanup flags, empty running/pending queues and `torch_vram_total` within the explicitly configured idle workspace ceiling on every device (zero by default). `/free` is asynchronous;
its HTTP success alone is insufficient. This check uses the installed ComfyUI
`server.py` and `main.py` behavior. GPU driver/context overhead is not represented
as Torch residency and is not claimed to vanish.

Timeout, malformed evidence, cancellation or provider failure retains the
external pin and blocks dispatch. Neither DELETE lease nor TTL can revoke an
external owner's GPU authority. A dirty marker survives Gateway restarts;
restart cannot silently reopen admission. The marker defaults to
`~/.local/state/ai-platform/gpu-residency.blocked` and may be configured through
`AI_BRIDGE_GATEWAY_GPU_MARKER`. Production uses `/var/lib/ai-platform-gpu/residency.blocked`
through a systemd `StateDirectory`, compatible with `ProtectHome` and `ProtectSystem`. Transition timeout defaults to 90 seconds; media
clients allow 120 seconds. Status exposes the transition state and recovery flag.

Only the Gateway may authorize local GPU work. Direct Ollama inference, model
preload, ComfyUI UI submissions and independent render workers are prohibited
while this shared pool is managed. Inventory/health endpoints are not proof of
safe execution. A single Gateway process owns this local queue; multiple ASGI
workers are unsupported. Preserve the marker across deployments and reboots.

This document describes the **current single shared accelerator pool**. It must
not become a permanent assumption of AI Platform. A future external GPU/accelerator
is modeled as another `accelerator_id` / resource pool with its own residency,
cleanup evidence and recovery state. The current global marker/ownership model
must be evolved to per-device or per-pool state before two accelerators are used
concurrently. One accelerator's dirty state must not be silently interpreted as
proof that another accelerator is safe, nor should hardware selection leak into
domain or Knowledge Service contracts.


The first guarded production render exposed two additional facts. The legacy
`generate-image` and `generate-image-edit` binaries independently preloaded Qwen
outside RM after rendering. Stage F now versions these renderers, removes all
local Ollama unload/preload actions and requires a live RM external-use token.
Rollback restores their exact archived bytes. The new renderers never perform
provider residency transitions themselves.

ComfyUI retained exactly 32 MiB after `/free`, with an empty queue, matching
PyTorch's documented default persistent HIP BLAS workspace. The LTX run additionally retained a 2 MiB allocator segment containing a small
buffer. Production explicitly allows at most 64 MiB reserved per device after
cleanup, and independently requires zero loaded models; no larger allocation is
accepted. This is a bounded workspace allowance, not a claim that
all GPU process/context memory disappears. See [PyTorch HIP memory/workspace
semantics](https://docs.pytorch.org/docs/main/notes/hip.html). Any Ollama model
reappearing before cleanup completes also fails closed. The initial production
attempt correctly remained blocked and is not Stage F acceptance evidence.

Media prompt compilers also run through the admitted lease. Stage F bounds their
responses to 512 tokens and disables reasoning for this translation task; the
previous unbounded video compiler exceeded its 90-second deadline. Media was
correctly denied while the abandoned HTTP call was still draining. A compiler
fallback is never accepted as passing internal E2E evidence.


The supported custom-node extension `deploy/comfyui/ai_platform_residency.py`
reports `/ai-platform/residency`: model-registry count, queue sizes and pending
cleanup flags, without consuming flags or modifying models. The Gateway requires
this evidence before and after every media phase; an absent/invalid endpoint fails
closed. This covers dynamic allocations outside Torch's allocator counters. The
extension is pinned to ComfyUI source `ace9172e95038ac25015c419713aa7755f739034`.
Deployment installs/removes the route with a quiesced ComfyUI restart and records
its new process identity. Normal media transitions restart neither ComfyUI nor
Ollama. Each smoke proves ComfyUI identity unchanged throughout execution.

The only legacy exception is a planned Stage E rollback with external ingress
paused and a freshly restarted ComfyUI process that has executed no media. The
supervisor verifies provider memory/queues without requiring the removed extension;
all candidate runtime handoffs require authoritative model-registry evidence.


ComfyUI's worker condition can miss a `/free` notification delivered during an
existing cleanup cycle: the flags remain set while an empty queue waits for a
new notification. RM retries the idempotent `/free` request within the same total
timeout, and requires the pending flags to clear. It never treats a fixed sleep,
a successful POST, or zero models alone as cleanup completion. A production
attempt demonstrated this condition and correctly remained fail-closed.

## Residual GPU failure after successful isolation

On September 23 at 11:21:36 CEST, G final validation produced MES WAIT_REG_MEM
failures seven seconds after a video finished, with zero Ollama residents in all
stable media observations. The guard contained ingress; verified F was restored
without GPU probes or restarts. This demonstrates that the residency repair does
not eliminate every GPU/media failure. The remaining mechanism is unresolved; do
not claim a driver fix or silently relax cleanup requirements. See the
[G incident](../reports/AI_PLATFORM_STAGE_G_PRODUCTION_GATE.md).
