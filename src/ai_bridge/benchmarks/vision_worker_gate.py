"""Parked subprocess gate for a trusted Vision GPU Benchmark executor.

No torch/ROCm imports, no GPU work before active RM use token. Parent starts
this process, attests its PID, then sends one-use authorization via pipe.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


def _verify(base: str, lease: str, use: str) -> None:
    if not base.startswith("http://127.0.0.1:") and not base.startswith("http://localhost:"):
        raise ValueError("Gateway must be loopback")
    req = Request(f"{base}/resource/leases/{lease}/uses/{use}", method="GET")
    with urlopen(req, timeout=5) as res:
        data = json.load(res)
    if data != {"provider": "vision-local", "capability": "image-analysis"}:
        raise RuntimeError("unexpected Vision ownership")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate-fd", type=int)
    ap.add_argument("--ready-file", type=Path)
    ap.add_argument("--auth-file", type=Path)
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("args", nargs=argparse.REMAINDER)
    p = ap.parse_args()
    if p.ready_file is not None and p.auth_file is not None and p.gate_fd is None:
        # Dedicated systemd user scope. No image/model/ROCm imports happen
        # before this parked process receives an authorized use ID.
        with p.ready_file.open("x", encoding="ascii") as ready:
            ready.write(str(os.getpid()) + "\n")
            ready.flush()
            os.fsync(ready.fileno())
        started = time.monotonic()
        while not p.auth_file.is_file():
            if time.monotonic() - started > 120:
                raise RuntimeError("Vision scope authorization timed out")
            time.sleep(0.05)
        raw = p.auth_file.read_text(encoding="utf-8")[:4096]
    else:
        if p.gate_fd is None or p.gate_fd < 3 or p.ready_file is not None or p.auth_file is not None:
            raise ValueError("exactly one authorization transport required")
        with os.fdopen(p.gate_fd, "r", encoding="utf-8", closefd=True) as pipe:
            raw = pipe.readline(4096)
    authorization = json.loads(raw)
    if set(authorization) != {"lease_id", "use_id"}:
        raise ValueError("missing Vision authorization")
    _verify(p.gateway, authorization["lease_id"], authorization["use_id"])
    args = p.args[1:] if p.args[:1] == ["--"] else p.args
    # execv replaces the parked process; PID and process birth time are stable.
    os.execv(p.python, [p.python, p.script, *args])


if __name__ == "__main__":
    main()
