"""Parked subprocess gate for a trusted Vision GPU Benchmark executor.

No torch/ROCm imports, no GPU work before active RM use token. Parent starts
this process, attests its PID, then sends one-use authorization via pipe.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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
    ap.add_argument("--gate-fd", type=int, required=True)
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("args", nargs=argparse.REMAINDER)
    p = ap.parse_args()
    if p.gate_fd < 3:
        raise ValueError("unexpected gate descriptor")
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
