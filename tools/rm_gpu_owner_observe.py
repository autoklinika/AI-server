"""Read-only P2-A3 inspection: GPU process visibility and AMD memory apertures.

For a deliberately authorized, one-shot DEV hardware check only. Does not
connect to Resource Manager, read secrets, expose PIDs/UUIDs or start models.
"""

from __future__ import annotations

import argparse
import json
import time

from ai_bridge.gateway.resource_gpu_process import collect_compute_processes
from ai_bridge.gateway.resource_hardware import collect_linux_hardware
from ai_bridge.gateway.resource_memory_domains import (
    collect_amd_apertures,
    summarize_memory_relation,
)
from ai_bridge.gateway.resource_ownership import summarize_ownership


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-nvidia", type=int, default=None)
    parser.add_argument("--expected-amd", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        hardware = collect_linux_hardware(
            expected_nvidia=args.expected_nvidia,
            expected_amd=args.expected_amd,
        )
        processes = collect_compute_processes(hardware)
        apertures = collect_amd_apertures(hardware)
        now_ns = time.monotonic_ns()
        # RM process identities are NOT in the current lease status contract.
        ownership = summarize_ownership(
            hardware, processes, None, now_ns=now_ns
        )
        memory = summarize_memory_relation(hardware, apertures, now_ns=now_ns)
    except (OSError, ValueError, TypeError):
        print(json.dumps({
            "mode": "read_only",
            "result": "UNKNOWN",
            "reason_codes": ["inspection_failed"],
            "authorizes_execution": False,
        }, sort_keys=True))
        return 2
    print(json.dumps({
        "ownership": ownership,
        "memory": memory,
    }, sort_keys=True, indent=2))
    # A successful read has no authority to grant GPU resources.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
