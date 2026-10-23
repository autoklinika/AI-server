# DEV — static physical routing inside existing Gateway RM

**Not a production installer. No GPU sharing grant. No new coordinator.**

The existing single PriorityScheduler remains the only admission queue. The
optional setting AI_BRIDGE_GATEWAY_PHYSICAL_OLLAMA_ROUTES_JSON is **empty by
default**. If explicitly provided with a JSON object matching example.json,
the Gateway uses exact model names to send the already-admitted inference
requests to two fixed loopback Ollama endpoints. Unknown models, arbitrary
client targets, remote addresses and external leases fail closed.

Use separate, physically pinned and externally verified CUDA and Vulkan
Ollama processes. Startup pinning was verified by real GPU logs in
the 2026-10-23 staging experiment; no production unit or NVIDIA PCIe config
was changed.

This feature does NOT:
- identify live PCI BDF securely every time a runtime restarts;
- prove OS isolation from direct GPU device node access;
- perform per-device VRAM budgeting or an N1/N3 safety release;
- permit multi-slot Resource Manager SHARED use;
- safely switch Ollama, ComfyUI and Vision ownership in production.

The integrated Radeon 890M Vulkan backend has reported a fictitious ~111 GiB
memory limit even though system RAM was ~30 GiB. Keep the exact allowed
models small; do not deploy 27B on this basis.

Validation on the DEV branch:
- 25 focused routing tests including strict URL validation, streaming,
  existing single global queue, refusal of a foreign lease, unknown model,
  legacy-off compatibility, and failure to enable RADIO/max_concurrency>1.
- Extended Gateway, scheduler, lease and accelerator inventory regression PASS.
- One-shot real GPU proof passed: Qwen3 0.6B on AMD 890M; BGE-M3 on RTX;
  both through one *DEV Gateway* scheduler and the model-pinned Ollama runtimes.
- Independent RTX-only probe loaded Qwen3 0.6B + BGE-M3 together at 1441 MiB
  VRAM and served two concurrent requests. This is Ollama parallel behavior,
  not concurrent grants through Gateway.

Source report: docs/reports/RM_TWO_PHYSICAL_GPU_ROUTING_DEV_2026-10-23_PL.md
Raw measurements remain on AI Platform NVMe in
/srv/ai-data/staging/gpu-dual-route-20261023 .

Production acceptance still requires trusted process/service launch identity,
protected GPU device node access, anti-bypass checks, memory enforcement,
recovery/rollback and separate approval. Never enable this flag in the
production Gateway based solely on these DEV tests.
