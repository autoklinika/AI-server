#!/usr/bin/env python3
"""Emergency Stage L recovery when cutover failed before DB mutation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

BASE = Path("/opt/ai-platform/releases/stage-j-3b456a56343a")
CURRENT = Path("/opt/ai-platform/current")


def run(args, *, check=True):
    return subprocess.run(
        [str(x) for x in args],
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def pg(sql):
    return run([
        "/usr/sbin/runuser", "-u", "postgres", "--",
        "psql", "-X", "-d", "ai_bridge", "-Atqc", sql,
    ])


def hermes(args):
    return run([
        "/usr/sbin/runuser", "-u", "harrypotter", "--", "env",
        "HOME=/home/harrypotter",
        "XDG_RUNTIME_DIR=/run/user/1000",
        "systemctl", "--user", *args,
    ])


def main():
    require(CURRENT.resolve(strict=True) == BASE, "current runtime is not Stage J")
    require(pg("SELECT version_num FROM alembic_version") == "0003_knowledge_canonical",
            "database schema is not 0003")
    require(pg(
        "SELECT count(*) FROM pg_tables "
        "WHERE schemaname='public' AND tablename LIKE 'ers_%'"
    ) == "0", "ERS tables exist during emergency recovery")

    run(["systemctl", "start", "ai-gateway.service", "ai-bridge.service"])
    hermes(["start", "hermes-gateway.service"])
    run(["systemctl", "start", "ai-bridge-analysis.timer"])

    for _ in range(45):
        gateway = run(
            ["curl", "-fsS", "http://127.0.0.1:11435/health"],
            check=False,
        )
        bridge = run(
            ["curl", "-fsS", "http://192.168.1.55:8080/health"],
            check=False,
        )
        g_ok = False
        b_ok = False
        try:
            g_ok = json.loads(gateway).get("status") == "ok"
            b_ok = json.loads(bridge).get("status") == "ok"
        except Exception:
            pass
        h_ok = hermes(["is-active", "hermes-gateway.service"]) == "active"
        timer_ok = run([
            "systemctl", "is-active", "ai-bridge-analysis.timer"
        ], check=False) == "active"
        if g_ok and b_ok and h_ok and timer_ok:
            print("STAGE_L_EMERGENCY_RECOVERY=PASS")
            return
        time.sleep(1)
    raise RuntimeError("services did not recover")


if __name__ == "__main__":
    main()
