#!/usr/bin/env python3
"""Read-only Stage N0 accelerator inventory validator.

This tool validates static inventory and evaluates hypothetical routing
constraints. It does not probe drivers, power state, PCIe links or GPUs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_bridge.providers.accelerators import AcceleratorRegistry, AcceleratorRequirements
from ai_bridge.providers.registry import local_descriptor_registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--provider", default="ollama-local")
    parser.add_argument("--backend", action="append", default=[])
    parser.add_argument("--memory-class", action="append", default=[])
    parser.add_argument("--min-memory-bytes", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    registry = AcceleratorRegistry.model_validate_json(args.inventory.read_text())
    providers = local_descriptor_registry()
    registry.validate_references(providers)
    requirements = AcceleratorRequirements(
        backends=tuple(args.backend),
        memory_classes=tuple(args.memory_class),
        min_memory_bytes=args.min_memory_bytes,
    )
    matches = registry.candidates(args.provider, requirements)
    print(json.dumps({
        "schema_version": 1,
        "mode": "static-readiness-only",
        "provider": args.provider,
        "requirements": requirements.model_dump(mode="json"),
        "eligible_accelerators": [item.accelerator_id for item in matches],
        "inventory": registry.snapshot(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
