# ComfyUI started on demand by existing RM — DEV only (2026-10-23)

**NO PRODUCTION DEPLOY. No second scheduler or coordinator.**

## Cause of persistent ROCm context

Production comfyui.service is enabled via multi-user.target and Restart=always.
An effective drop-in on ai-gateway.service adds Requires=comfyui.service and
After=comfyui.service. Consequently ComfyUI is started on boot, before Hermes
needs any image. After a Hermes /foto request, RM currently frees ComfyUI
models by /free, but does NOT stop the service or close all AMD KFD/DRM handles.
A persistent live ComfyUI process with zero loaded models is NOT evidence of
physically released GPU. It may remain in ROCm with RM=IDLE.

Hermes /foto ALREADY reserves the existing RM priority queue and uses the
external provider comfyui-local through /resource/leases/{id}/uses. The
existing RM must remain the owner of process admission; no Hermes-level
scheduler, Docker coordinator or new root daemon is introduced.

## Implemented in DEV Gateway (disabled by default)

- gateway_comfy_ondemand_dev_mode=False in Settings by default.
- Accepts an independently injected, trusted controller ONLY for an isolated
  loopback ComfyUI port other than 8188. Production service is never targeted.
- Requires localhost Gateway, one existing RM scheduler slot and RADIO disabled.
  Does not yet allow combining the separate dual-GPU routing candidate with
  ComfyUI on-demand, until concurrency/isolation testing.
- External use start: lease pinned -> persistent residency marker -> managed
  process start/attestation -> existing GPUResidency.enter_media -> execute.
- End: existing GPUResidency.leave_media unloads models and checks local
  reserved bytes but deliberately HOLDS the marker/state. The managed service
  then stops its process and verifies process/cgroup identity. Only after
  successful stop is the recovery marker cleared and RM returned to LLM.
- Crash or any incomplete start/free/stop produces BLOCKED/recovery_required.
  The existing priority queue keeps the original lease and does NOT grant
  another GPU user based merely on ComfyUI HTTP /free.
- ServiceIdentity carries boot_id, invocation, PID, cgroup and PID birth ticks.
  The actual trusted OS controller remains NOT_ADMITTED: without an injected
  approved controller Gateway refuses to enable DEV on-demand.
- GPU_REUSE_SAFE remains NOT_VERIFIED; the mechanism tests own-process
  lifecycle only, not the complete kernel/driver queue E_safe.

## Evidence and current restrictions

- CPU/ASGI unit and integration tests exercise Hermes-compatible
  media-image lease -> start -> media -> free -> stop -> release and queued
  lower-priority work, including failed start, failed free, failed stop, crash,
  identity drift and recovery marker persistence.
- This is NOT a real GPU start/stop; production ComfyUI still holds AMD
  /dev/kfd and /dev/dri/renderD128, and we must not launch a second AMD
  ComfyUI engine concurrently.
- A DEV sample system-manager unit file is stored beside this README.
  It is not installed and intentionally contains no [Install] section,
  so does not modify boot/autostart.
- The unit is a candidate and requires independent hardening/acceptance:
  root-owned credentials, service identity (PID/birth/cgroup/InvocationID),
  DeviceAllow, memory ceiling, model paths, atomic stop/recovery and
  secure **bounded** delegation of systemd actions. A user-manager
  DevicePolicy=closed DID NOT enforce device denial in earlier real tests.

## Remaining DEV acceptance before production cutover

1. With operator-approved maintenance window, stop or isolate production
   ComfyUI only after confirming Gateway/RM, Hermes and all jobs are idle;
   safely undo the Gateway boot Requires=comfyui.service dependency in a
   staged release with the original unit/drop-in saved for rollback.
2. Deploy only the separately reviewed, fixed root-owned systemd unit.
   Validate real disabled/short-lived startup and restricted GPU open.
   Test real light image generation and cleanup under a trusted lease.
3. Verify loss of worker during work, watchdog/timeout, cgroup kill,
   memory OOM, restart, stale PID and boot ID, escaped descendants,
   foreign GPU opens and slow/incomplete ROCm cleanup.
4. Preserve production Hermes /foto endpoint reachability. Current
   production image dispatch uses the existing ComfyUI endpoint; DEV uses
   an isolated port. There must be an explicit, reviewed endpoint switch
   or retained port 8188 after the old service is stopped, never two
   servers binding one port.
5. Verify that Gateway starts and remains available even with ComfyUI
   stopped. Current Gateway Requires=comfyui.service drop-in must be
   removed transactionally; do not simply disable ComfyUI at boot.
6. Then full Hermes/Telegram, WVC/Knowledge, Vision and two-GPU integration
   tests, restore backups on failure and require explicit separate
   production approval.

No production service has been stopped, restarted, reconfigured or masked.
Do not manually stop the current comfyui.service while Gateway still
Requires it. Legacy Ollama/ComfyUI scheduling remains unchanged.
