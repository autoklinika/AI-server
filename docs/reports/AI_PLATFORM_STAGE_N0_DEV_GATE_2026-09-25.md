# AI Platform — Stage N0 heterogeneous accelerator readiness — Dev Gate

Date: 2026-09-25
Baseline: `main` after Stage M production closure.

## Scope

Stage N0 prepares the platform for a future discrete local accelerator without
requiring or pretending that such hardware is currently installed. It does not
change production workload placement, GPU ownership transitions, model selection,
or provider execution paths.

## Delivered

- `AcceleratorRegistry` schema v1 with explicit accelerator identity, node,
  kind, backend, memory class/capacity, locality, enabled state and workload classes.
- provider-to-accelerator bindings separate from the logical provider registry.
- fail-closed `AcceleratorRequirements` filtering for backend, memory class,
  locality and minimum verified memory.
- default `local-primary` inventory for today's shared unified-memory compute pool.
- Gateway `/status` and `/health` accelerator snapshots with per-device residency.
- Platform API `/observability` and `/health` exposure for future Control Center.
- legacy `gpu_residency` preserved unchanged as compatibility alias for the current
  primary shared pool.
- disabled future accelerators are descriptive only and cannot become candidates.
- `deploy/gateway-accelerators.example.json` showing a disabled future discrete
  device without claiming installation or health.
- `tools/accelerator_readiness.py` for read-only static contract validation.
- ADR 0014 defining N0/N1 ownership and safety boundary.

## Explicit non-goals

N0 does not probe PCIe/OCuLink, drivers, CUDA/ROCm, VRAM, power or thermals. It
does not create per-device leases, perform fallback, move models, benchmark a
nonexistent card or activate multi-GPU execution. Those are N1 gates after hardware
is physically installed.

## Validation

Focused accelerator, Platform API, provider registry and GPU-residency tests:
`133 passed`.

Full AI-server regression suite after all N0 changes:

```text
1016 passed, 11 warnings in 11.08s
```

Additional checks:

- `git diff --check`: PASS
- Python compileall for `src`, `tests` and readiness tool: PASS
- static readiness check against the example inventory: PASS; disabled external
  CUDA device correctly produced no eligible candidate.

No sudo, service restart, production cutover, database migration or hardware
configuration was performed as part of this development gate.
