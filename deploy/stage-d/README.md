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
9. Run media/Telegram smoke and rollback validation before closing D.0.

Production cutover is not performed by committing these scripts.
