"""Fixed two-phase hardware lifecycle worker, not a scheduler or E_safe adapter.

READY: no torch import or GPU context
G: run fixed 64x64 GPU operation, print structured result
X: exit voluntarily after supervisor has observed live GPU ownership
"""
from __future__ import annotations

import json
import select
import sys


def main():
    if len(sys.argv) != 1:
        return 2
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    if not select.select([sys.stdin.buffer], [], [], 10)[0]:
        return 3
    if sys.stdin.buffer.read(1) != b"G":
        return 4
    try:
        import torch
        import runpy
        from pathlib import Path
        fixed = Path(__file__).with_name("rocm_test_worker.py")
        run_fixed = runpy.run_path(str(fixed))["run_fixed"]
        result = run_fixed(torch)
    except Exception as exc:
        print(json.dumps({"status": "WORKER_FAILED", "error_type": type(exc).__name__,
                          "detail": str(exc)[:200]}), file=sys.stderr, flush=True)
        return 5
    print(json.dumps(result, sort_keys=True), flush=True)
    # Intentional observation window: a live process still owns its context.
    if not select.select([sys.stdin.buffer], [], [], 10)[0]:
        return 6
    if sys.stdin.buffer.read(1) != b"X":
        return 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
