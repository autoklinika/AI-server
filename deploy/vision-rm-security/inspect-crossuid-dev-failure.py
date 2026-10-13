#!/usr/bin/env python3
"""Read-only evidence collector after cross-UID DEV CPU-only failure.

Runs as root only to inspect restricted DEV artifacts. Never reads the
contents of authorization files or controller credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path("/srv/ai-data/evaluation/vision-rm-service")
MARKER = Path("/var/lib/ai-gateway-rm/dev-gpu-test.blocked")
RESULT = ROOT / "crossuid-cpu-result.json"
SOCKET = Path("/run/ai-vision-rm-broker/control.sock")
SAFE = re.compile(
    r"^(?:Traceback \(most recent call last\):|"
    r"\s*File \"/usr/local/libexec/ai-platform/[^\"]+\", line [0-9]+.*|"
    r"\s*File \"<frozen [^\"]+\", line [0-9]+.*|"
    r"\s*[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):[^\n]{0,240}|"
    r"\s*VISION_CROSS_UID_CPU_WORKER=PASS\s*|"
    r"\s*Running scope as unit:[^\n]{0,120}|"
    r"\s*Failed to (?:start|stop) unit:[^\n]{0,160})$"
)


def value(label: str, item: object) -> None:
    print(f"{label}={item}", flush=True)


def safe_stat(path: Path) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        value("DEV_EVIDENCE_SYMLINK_BLOCKED", path.name)
        return None
    return metadata


def job() -> None:
    meta = safe_stat(ROOT)
    if meta is None or not stat.S_ISDIR(meta.st_mode):
        value("DEV_JOB_ROOT", "MISSING_OR_UNTRUSTED")
        return
    entries = sorted(
        (p for p in ROOT.iterdir() if p.name.startswith("rm-job-")),
        key=lambda p: p.stat().st_mtime_ns if not p.is_symlink() else 0,
        reverse=True,
    )
    value("DEV_JOB_COUNT", len(entries))
    for index, folder in enumerate(entries[:3], start=1):
        info = safe_stat(folder)
        if info is None or not stat.S_ISDIR(info.st_mode):
            value(f"DEV_JOB_{index}", "UNTRUSTED")
            continue
        value(f"DEV_JOB_{index}_UID", info.st_uid)
        for name in ("ready.pid", "authorized.json", "worker.log"):
            path = folder / name
            item = safe_stat(path)
            value(f"DEV_JOB_{index}_{name.replace('.', '_')}_EXISTS", item is not None)
            if name != "worker.log" or item is None or not stat.S_ISREG(item.st_mode):
                continue
            # Only allowlisted diagnostic lines. Never output arbitrary log text,
            # bearer values, worker tokens, or authorization JSON.
            data = path.read_bytes()[-24576:].decode("utf-8", errors="replace")
            lines = [line for line in data.splitlines() if SAFE.fullmatch(line)]
            value(f"DEV_JOB_{index}_WORKER_LOG_SAFE_LINES", len(lines))
            for line in lines[-22:]:
                if any(sensitive in line.lower() for sensitive in
                       ("token", "secret", "bearer", "authorization", "credential")):
                    line = line.split(":", 1)[0] + ": [REDACTED]"
                print("DEV_WORKER_DIAGNOSTIC:", line, flush=True)


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("read-only inspection requires sudo; no service restarts")
    value("DEV_DIAGNOSTIC_MODE", "READ_ONLY")
    for label, item in (
        ("DEV_BLOCK_MARKER_PRESENT", MARKER),
        ("DEV_CPU_RESULT_PRESENT", RESULT),
        ("DEV_BROKER_SOCKET_PRESENT", SOCKET),
    ):
        value(label, safe_stat(item) is not None)
    if safe_stat(RESULT) is not None:
        # Read ONLY the known fixed CPU-only payload shape, no other keys.
        try:
            result = json.loads(RESULT.read_text())
            expected = {"status", "worker_uid", "rm_control_credential_absent", "gpu_imports"}
            value("DEV_CPU_RESULT_SCHEMA_EXPECTED", set(result) == expected)
            if set(result) == expected:
                value("DEV_CPU_RESULT_STATUS", result.get("status") == "cpu_only")
                value("DEV_CPU_RESULT_UID_994", result.get("worker_uid") == 994)
                value("DEV_CPU_SECRET_ABSENT", result.get("rm_control_credential_absent") is True)
                value("DEV_CPU_GPU_IMPORTS_FALSE", result.get("gpu_imports") is False)
        except (OSError, ValueError, TypeError):
            value("DEV_CPU_RESULT_PARSE", "FAIL")
    job()
    for unit in ("ai-vision-rm-dev-gateway", "ai-vision-rm-broker",
                 "ai-vision-rm-runner", "ai-gateway", "ollama"):
        p = subprocess.run(
            ["systemctl", "show", unit + ".service",
             "-p", "ActiveState", "-p", "SubState", "-p", "Result"],
            capture_output=True, text=True, timeout=4, check=False
        )
        state = ",".join(p.stdout.strip().splitlines())
        value("DEV_SERVICE_" + unit.replace("-", "_"), state or "UNAVAILABLE")


if __name__ == "__main__":
    main()
