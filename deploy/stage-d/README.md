# Stage D deployment tooling

Stage D evolves AI Gateway into Resource Manager v2. These scripts are intentionally separate from `deploy/stage-c/`: Stage C guards correctly froze scheduler behavior and must remain valid recovery evidence.

## D.0 guarantees

- exact committed source is used for both AI Bridge and AI Gateway;
- release contains checksums and a richer manifest;
- installation rebuilds virtualenvs in their final `/opt/ai-platform/releases/<id>` paths;
- install and validation do not activate the release;
- activation requires Resource Manager idle state and canonical release-managed systemd units;
- rollback targets the previously active release;
- canonical systemd install/restore does not restart running services;
- production Gateway-default env policy is migrated with a captured, reversible baseline and no implicit restart;
- Stage A release-path drop-ins remain recoverable as compatibility evidence, but are not the D.0 desired state.

## First D.0 production cutover order

1. Build release.
2. Install release without activation.
3. Validate installed release while Stage C remains active.
4. Apply the reversible Gateway-default production env policy.
5. Install canonical systemd units.
6. Confirm manager configuration and idle gate.
7. Activate Stage D release.
8. Run `validate_wvc_gateway_runtime.sh`; when CM5 is disconnected this validates the ingest contract and a real ventilation-priority Gateway/Qwen request without requiring live telemetry.
9. Run `validate_media_runtime.sh` for a real Stage30 render under a Resource Manager external lease, then verify the actual Telegram `/wideo` user path.
10. Run rollback validation before closing D.0. For the D.0 production gate use an explicit known-good target, e.g. `rollback_release.sh stage-c-provider-abstraction-20260921-r3`; the no-argument form remains an immediate-previous emergency rollback.

Production cutover is not performed by committing these scripts.


## D.1 validation handoff

D.1 adds semantic `priority_class` admission while preserving legacy numeric
priorities and FIFO. It is **READY FOR PRODUCTION VALIDATION**, not deployed.
See the [D.1 report](../../docs/reports/AI_PLATFORM_STAGE_D1_SEMANTIC_PRIORITY_2026-09-21_PL.md)
for test evidence and remaining checks. At that stage the builder carried D.0 metadata. D.6 preparation below supersedes
that historical metadata blocker; clean committed source is still required.

## D.3 validation handoff

D.3 adds static capability/provider/node inventory and validates known HTTP job
assignment. It is **READY FOR SUPERVISOR VALIDATION**, with no production change.
See the [D.3 report](../../docs/reports/AI_PLATFORM_STAGE_D3_DESCRIPTORS_2026-09-22_PL.md).
Defaults are packaged in Python; optional `AI_BRIDGE_GATEWAY_REGISTRY` accepts a
JSON object matching [the example](../gateway-registry.example.json), not a file
path. Omit it to use the existing three providers on `AI_BRIDGE_NODE_ID`.
The Gateway rejects topology changes and does not enable multi-node dispatch.
The historical D.0 metadata blocker is resolved by D.6 preparation below;
recovery/build guards are unchanged.

## D.6 preparation

**READY FOR PRODUCTION VALIDATION — implementation ready for supervisor validation.**
The current builder emits D.6 / schema 3 / resource-manager-v2, Resource Manager
contract 2 and D.1–D.5 subcontracts 1. Provider contracts remain 1. Historical
D.0/C artifacts remain recovery targets. Current runtime validators require D.6.

[Runbook](D6_VALIDATION_RUNBOOK.md) contains the automated coverage matrix, WVC
regression, Telegram multiuser/Discord, real media and rollback gates. New offline
`validate_release_metadata.py` and `validate_rollback_readiness.py` check release
identity and preserved artifact checksums. `observe_validation.py` provides a
read-only health/count snapshot for later authorized live tests. None proves a
production PASS. No cutover or service operation was performed in preparation.
