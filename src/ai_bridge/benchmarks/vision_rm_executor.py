"""Shared private Gateway transport for scoped Vision Benchmark Runner.

Intentionally no unscoped executable runner: all GPU jobs must enter a
dedicated systemd user cgroup via vision_rm_scoped_executor.py.
"""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


class VisionExecutionError(RuntimeError):
    """Fail-closed Vision GPU execution or resource ownership error."""


def call(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    if not (base.startswith("http://127.0.0.1:") or base.startswith("http://localhost:")):
        raise ValueError("Gateway must be private loopback")
    if not path.startswith("/"):
        raise ValueError("Gateway API path must be absolute")
    raw = json.dumps(payload).encode() if payload is not None else None
    headers={"Content-Type":"application/json"} if raw else {}
    credential=os.environ.get("VISION_RM_EXECUTOR_TOKEN")
    token_path=os.environ.get("VISION_RM_EXECUTOR_TOKEN_FILE")
    if credential and token_path:
        raise VisionExecutionError("ambiguous RM control credential")
    if token_path:
        from pathlib import Path
        path=Path(token_path)
        info=path.stat()
        if (not path.is_absolute() or not path.is_file() or info.st_uid!=0
                or info.st_mode & 0o027):
            raise VisionExecutionError("untrusted protected RM control credential")
        credential=path.read_text(encoding="utf-8").strip()
    if credential:
        headers["X-AI-Vision-Executor-Token"]=credential
    req = Request(base.rstrip("/") + path, method=method, data=raw,
                  headers=headers)
    with urlopen(req, timeout=6) as response:
        return json.load(response)
