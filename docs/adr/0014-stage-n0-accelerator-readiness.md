# ADR 0014 — Stage N0 accelerator readiness

Status: development implementation.

Stage N0 prepares AI Platform for a future local discrete accelerator without
changing today's execution topology. No external GPU is assumed to exist and no
driver, PCIe/OCuLink, CUDA or ROCm activation is performed.

## Decision

AI Platform gains a versioned `AcceleratorRegistry` independent of the existing
provider registry. Providers continue to describe software execution boundaries;
accelerators describe compute resources they may be allowed to use.

The default inventory contains one explicit `local-primary` accelerator representing
the current shared local compute pool. Its backend and total memory are intentionally
`unknown` unless configured from verified deployment facts. This avoids turning
hardware assumptions into platform contracts.

Each accelerator records:

- stable `accelerator_id` and `node_id`;
- integrated/discrete/virtual kind;
- backend (`rocm`, `cuda`, `vulkan`, `cpu`, `unknown`);
- unified/dedicated/host memory class and optional verified byte capacity;
- locality, enabled state and workload classes;
- explicit provider bindings.

`AcceleratorRequirements` evaluates backend, memory class, locality and minimum
known memory. Unknown memory fails closed when a minimum is requested. Disabled
devices are never candidates.

## Runtime boundary

N0 is descriptive only. Scheduler admission, ResourceLeaseRegistry and the current
single shared residency transition remain authoritative. `gpu_residency` stays in
Gateway and Platform API for compatibility.

A new `accelerators` snapshot exposes the versioned inventory plus residency for
`local-primary`. Other configured devices are reported as `unmanaged` until a later
hardware activation stage gives them independent residency managers.

Clients must continue to request capabilities, never card names. No domain API,
Knowledge API, ERS or CRT contract may depend on a vendor or accelerator ID.

## N1 boundary

N1 begins only after hardware exists. It must add verified device discovery,
driver/backend health, per-device residency and leases, provider-to-device runtime
binding, workload placement/fallback, power/thermal evidence, transfer/concurrency
benchmarks and a rollback-capable production gate.

N0 explicitly does not claim that a configured future device is installed, healthy
or usable. `tools/accelerator_readiness.py` is static validation only.
