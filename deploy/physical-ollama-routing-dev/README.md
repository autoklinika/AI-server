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


## DEV memory and runtime containment extension (23 October 2026)

Physical routing requires **three explicitly configured settings**; production
defaults still do not enable any of them:

- AI_BRIDGE_GATEWAY_PHYSICAL_GPU_DEV_MODE=true (hard fail unless localhost)
- AI_BRIDGE_GATEWAY_PHYSICAL_OLLAMA_ROUTES_JSON=(review example.json)
- AI_BRIDGE_GATEWAY_PHYSICAL_GPU_BUDGET_JSON=(review memory-budget.example.json)

The Gateway calls the **same single PriorityScheduler** and checks the selected
runtime's /api/ps before dispatch. Memory estimates for every exact model,
host physical MemTotal/MemAvailable and NVIDIA-SMI VRAM total/used/free are
checked before submission. Missing metrics, unknown resident model, too little
physical RAM/VRAM, oversized context, CPU-offload overrides and unbounded model
keepalive are refused without CPU fallback. This is **logical admission**;
NVIDIA VRAM is not cgroup-memory limited. Do not assign a large AMD model based
on Vulkan's fictitious ~111 GiB reading.

Draft, **not installed**, system-manager unit profiles:
- systemd/ai-rm-ollama-amd-dev.service — DevicePolicy closed, only
  /dev/dri/renderD128, MemoryMax 6G, 1 model, only small DEV Qwen;
- systemd/ai-rm-ollama-rtx-dev.service — DevicePolicy closed, only CUDA
  /dev/nvidia devices, MemoryMax 4G (CPU-side memory only), up to 2 models.
  Requires the verified ai-egpu-gen3-ha.service boot gate.

Static systemd-analyze verify PASS. Both units have Restart=no,
RuntimeMaxSec=360, KillMode=control-group, no Install section. The unit
profiles are **not permitted to start automatically or on production.**
No production model store or systemd service has been changed.

**Security finding:** in an actual unprivileged user-manager transient unit,
DevicePolicy=closed did NOT stop access to /dev/dri/renderD128
(OPEN_SUCCEEDED). By contrast, cgroup MemoryMax=48M killed an attempted 96M
allocation (systemd result oom-kill). An earlier host audit independently found
that users/processes outside the RM can open a GPU device.
Therefore root-managed/system-manager enforcement and host-wide access
restrictions remain **NOT VERIFIED**. They cannot be inferred from static
files, process exit, an empty GPU owner list, or a successful DEV inference.

An operator-only, unexecuted negative probe is prepared:
run_system_scope_gpu_negative_dev.sh + os_gpu_access_probe.py. It requires
root authorization and uses transient system-manager units with bounded
runtime. It will not install, enable, stop or restart production services.
**Do not run from ChatGPT unattended.** Before considering any production
cutover, review the scripts, run the bounded probes with explicit operator
authorization and collect evidence. Passing the local device filter alone
does NOT establish global OS exclusivity or GPU_REUSE_SAFE.
