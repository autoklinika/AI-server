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
with both `unload_models` and `free_memory`, then verifies empty running/pending
queues and `torch_vram_total` within the explicitly configured idle workspace ceiling on every device (zero by default). `/free` is asynchronous;
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


The first guarded production render exposed two additional facts. The legacy
`generate-image` and `generate-image-edit` binaries independently preloaded Qwen
outside RM after rendering. Stage F now versions these renderers, removes all
local Ollama unload/preload actions and requires a live RM external-use token.
Rollback restores their exact archived bytes. The new renderers never perform
provider residency transitions themselves.

ComfyUI retained exactly 32 MiB after `/free`, with an empty queue, matching
PyTorch's documented default persistent HIP BLAS workspace. Production explicitly
allows at most 33,554,432 reserved bytes per device after cleanup; no larger
allocation is accepted. This is a bounded workspace allowance, not a claim that
all GPU process/context memory disappears. See [PyTorch HIP memory/workspace
semantics](https://docs.pytorch.org/docs/main/notes/hip.html). Any Ollama model
reappearing before cleanup completes also fails closed. The initial production
attempt correctly remained blocked and is not Stage F acceptance evidence.
