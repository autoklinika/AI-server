"""Fixed parked ROCm payload; GPU imports happen ONLY after parent sends GO.

No arguments and no arbitrary commands. A denied N1 grant closes this worker
without ever importing torch, HIP or touching /dev/kfd. This is an execution
gate, NOT a proof of GPU_REUSE_SAFE.
"""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    sys.stdout.buffer.write(b"READY\n")
    sys.stdout.buffer.flush()
    if sys.stdin.buffer.read(1) != b"G":
        return 3
    from pathlib import Path
    import runpy
    path = Path(__file__).with_name("rocm_test_worker.py")
    # Fixed source in the same trusted checkout, no client-supplied path.
    runpy.run_path(str(path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
