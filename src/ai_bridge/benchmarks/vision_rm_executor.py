"""Shared private Gateway transport for scoped Vision Benchmark Runner.

Intentionally no unscoped executable runner: all GPU jobs must enter a
dedicated systemd user cgroup via vision_rm_scoped_executor.py.
"""
from __future__ import annotations

import json
from urllib.request import Request, urlopen


class VisionExecutionError(RuntimeError):
    """Fail-closed Vision GPU execution or resource ownership error."""


def call(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    if not (base.startswith("http://127.0.0.1:") or base.startswith("http://localhost:")):
        raise ValueError("Gateway must be private loopback")
    if not path.startswith("/"):
        raise ValueError("Gateway API path must be absolute")
    raw = json.dumps(payload).encode() if payload is not None else None
    req = Request(base.rstrip("/") + path, method=method, data=raw,
                  headers={"Content-Type":"application/json"} if raw else {})
    with urlopen(req, timeout=6) as response:
        return json.load(response)
