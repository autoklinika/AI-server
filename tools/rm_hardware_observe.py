"""Explicit, sanitized, read-only hardware diagnostic for AI Platform DEV.

Run only on an authorized Linux host. No driver changes, GPU allocations,
model launches, resource leases or updates to production state occur.
"""

from __future__ import annotations

import argparse
import json

from ai_bridge.gateway.resource_hardware import (
    collect_linux_hardware,
    public_hardware_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-nvidia",
        type=int,
        default=None,
        help="Expected NVIDIA GPU count (detect disappearance, not identity replacement)",
    )
    parser.add_argument(
        "--expected-amd",
        type=int,
        default=None,
        help="Expected AMD DRM card count (detect disappearance)",
    )
    args = parser.parse_args(argv)

    try:
        reading = collect_linux_hardware(
            expected_nvidia=args.expected_nvidia,
            expected_amd=args.expected_amd,
        )
    except (ValueError, OSError):
        print(
            json.dumps(
                {
                    "mode": "read_only",
                    "result": "UNKNOWN",
                    "reason_codes": ["hardware_collection_failed"],
                    "authorizes_execution": False,
                    "allocation_attribution": "unverified",
                    "memory_domain_mapping": "unverified",
                },
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps(public_hardware_summary(reading), sort_keys=True, indent=2))
    # The memory relation is intentionally unverified even on an otherwise
    # successful hardware observation. Return nonzero only for probe failures.
    return 2 if reading.issues or not reading.devices else 0


if __name__ == "__main__":
    raise SystemExit(main())
