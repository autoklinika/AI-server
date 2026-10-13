"""Shared private Gateway transport for scoped Vision Benchmark Runner.

Intentionally no unscoped executable runner: all GPU jobs must enter a
dedicated systemd user cgroup via vision_rm_scoped_executor.py.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class VisionExecutionError(RuntimeError):
    """Fail-closed Vision GPU execution or resource ownership error."""


def call(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    # A string prefix is not a loopback guarantee: 127.0.0.1:port@host
    # would send the controller bearer outside the machine.
    parsed=urlsplit(base)
    try:
        port=parsed.port
    except ValueError as exc:
        raise ValueError("Gateway must be private loopback") from exc
    if (parsed.scheme!="http" or parsed.hostname not in ("127.0.0.1","localhost")
            or port is None or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("","/")
            or parsed.query or parsed.fragment):
        raise ValueError("Gateway must be private loopback")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Gateway API path must be absolute")
    raw = json.dumps(payload).encode() if payload is not None else None
    headers={"Content-Type":"application/json"} if raw else {}
    credential=os.environ.get("VISION_RM_EXECUTOR_TOKEN")
    token_path=os.environ.get("VISION_RM_EXECUTOR_TOKEN_FILE")
    if credential and token_path:
        raise VisionExecutionError("ambiguous RM control credential")
    if token_path:
        from pathlib import Path
        credential_file=Path(token_path)
        info=credential_file.stat()
        if (not credential_file.is_absolute() or not credential_file.is_file()
                or credential_file.is_symlink() or info.st_uid!=0
                or info.st_mode & 0o027):
            raise VisionExecutionError("untrusted protected RM control credential")
        credential=credential_file.read_text(encoding="utf-8").strip()
    if credential:
        headers["X-AI-Vision-Executor-Token"]=credential
    req = Request(base.rstrip("/") + path, method=method, data=raw,
                  headers=headers)
    with urlopen(req, timeout=6) as response:
        return json.load(response)
