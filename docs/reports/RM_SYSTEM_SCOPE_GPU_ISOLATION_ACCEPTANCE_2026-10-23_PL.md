# AI Platform — systemd GPU isolation DEV acceptance (23.10.2026)

**SYSTEM_SCOPE_ALLOW_DENY_PASS_2_OF_2.**
**GLOBAL_HOST_GPU_EXCLUSIVITY=NOT_VERIFIED. GPU_REUSE_SAFE=NOT_VERIFIED.**
**N1_GPU_GRANTS=NOT_ADMITTED. PRODUCTION_UNCHANGED=YES.**

Host: harrypotter-AI-Series. Probe ran through systemd --system,
not systemd --user. Both transient units terminated with SUCCESS,
with no permanent installation and no reboot/driver/service changes.

## Real operator test

| Observed device operation | AMD unit | RTX unit |
|---|---|---|
| Open AMD renderD128 | ACCESS_GRANTED | ACCESS_DENIED |
| Open NVIDIA nvidia0 | ACCESS_DENIED | ACCESS_GRANTED |
| Open NVIDIA nvidiactl | Not tested | ACCESS_GRANTED |
| Open /dev/kfd | ACCESS_DENIED | ACCESS_DENIED |
| Open RTX renderD129 | ACCESS_DENIED | Not tested |
| Transient unit result | success, 52 ms | success, 33 ms |
| Actual model inference under these units | NOT TESTED | NOT TESTED |

System manager cleaned up both one-shot units. Subsequent systemctl show:
LoadState=not-found, ActiveState=inactive, MainPID=0.
The tests verify allow/deny only in the two named cgroups, and do
not prove driver teardown or a host-wide access restriction.

Data integrity: local operator logs were independently checked;
SHA256 of each log and a machine-readable summary are in
RM_SYSTEM_SCOPE_GPU_ACCESS_EVIDENCE_2026-10-23.json.
Original logs are kept on NVMe under
/srv/ai-data/staging/gpu-dual-route-20261023/.

## New read-only whole-host DEV audit

Gateway DEV module gpu_host_boundary_audit_dev.py inspects fixed GPU
device permissions, known systemd services, current visible GPU file
descriptors, physical PCI identity and GET of the direct Ollama API.
It performs no GPU computation and does not grant GPU ownership.

Actual host observations:
- NVIDIA device nodes (nvidia0, nvidiactl, UVM) have world-writable
  permissions 0666. Ordinary processes may open them outside RM.
- AMD renderD128 and /dev/kfd are available to the render group;
  platform accounts retain membership of render and video.
- Ollama, Gateway and ComfyUI currently use DevicePolicy=auto.
- ComfyUI PID 4937 under /system.slice/comfyui.service retains
  handles to /dev/kfd and /dev/dri/renderD128 while RM reports IDLE.
  This is not proof of active GPU computation, but it shows why
  RM IDLE must not be equated with driver / GPU release.
- Unprivileged GET /api/version on the direct local Ollama port
  127.0.0.1:11434 returned HTTP 200. This proves reachability
  of an API path outside Gateway; it did not test unauthorized
  inference or prove all API operations are allowed.
- RTX after test: P8, 2 MiB VRAM, PCIe Gen3 x4, Xid=0, AER=0.
  Production RM: IDLE, recovery_required=false, active=0, queued=0.

Audit verdict: BLOCKED, with diagnostic findings:
WORLD_WRITABLE_GPU_DEVICE,
ACTIVE_SERVICE_GPU_ACCESS_NOT_CGROUP_RESTRICTED,
GPU_FILE_DESCRIPTORS_OBSERVED,
DIRECT_OLLAMA_API_REACHABLE_OUTSIDE_GATEWAY.

Audit evidence is incomplete for hidden process namespaces, open
kernel contexts and alternate device aliases. An empty owner list
would not constitute a driver safety proof, either. No global
positive GPU grants can be issued by this audit.

## DEV status and next acceptance gates

1. Test model inference on both physical GPUs INSIDE trusted transient
   system-manager cgroups, rather than merely testing os.open.
   Check model, backend, PCI ID, boot-ID, PID birth, cgroup identity,
   shutdown/cleanup, quotas and CPU fallback refusal.
2. Expand device negative tests to relevant GPU aliases, while preserving
   the devices necessary for legitimate CUDA/Vulkan inference.
3. Design full OS-level isolation of unmanaged users and processes:
   DAC/ACL/render/video membership, preexisting processes and FDs,
   alternative GPUs, direct Ollama endpoints, and containers.
4. Complete safe abnormal-stop, hard timeout, process orphan,
   memory OOM, host recovery and rollback tests.
5. Preserve a single existing Resource Manager scheduler with its
   Radeon priorities and existing engine lifecycle. No new coordinator.
6. Only after full DEV acceptance test production-sized Qwen 27B,
   Hermes/Telegram and ComfyUI/Vision, then request a distinct
   operator-approved production cutover.

No firmware, BIOS, GRUB, driver, PCIe Gen3+HA, GPU power cap,
production units or global permissions were changed during this audit.

**STATUS: SYSTEM-SCOPE PASS, HOST-WIDE NO-GO, NOT PRODUCTION READY.**


## DEV regression, reproducibility and evidence

- 394/394 selected CPU and ASGI regression tests PASS on the actual host:
  physical GPU routing, budget refusal, priority scheduling, job lifecycle,
  resource leases, engine lifecycle, ComfyUI readiness, scope profile
  static validation and new negative global-boundary audit.
- Test suite evidence stays on NVMe:
  /srv/ai-data/staging/gpu-dual-route-20261023/rm-system-scope-dev-regression.log
- machine evidence reviewed against the two original transient-unit logs;
  their SHA256 is preserved in the attached JSON, without publishing
  unredacted host logs.
- The DEV audit is intentionally exit status 2 (BLOCKED), so an operator
  cannot mistake a passing cgroup test for approval of global N1 grants.
- Draft PR #178 contains only DEV changes and no production activation.
