#!/usr/bin/env python3
"""Cooperative RM V1: disable competing boot autostarts, then start idle ComfyUI.

Default is read-only. --apply needs operator TTY and sudo. No GPU allocation,
unload, driver reset, N1 grants, UID/GID, production binaries, or Gateway restart.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

import restore_cooperative_v1 as base

AUTOSTART = ("comfyui.service", "ollama-preload.service", "ai-bridge-analysis.timer")
CORE = base.START
LOCK = Path(__file__).with_suffix(".lock")
COMFY = "comfyui.service"


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=30)
    state = p.stdout.strip()
    # systemctl is-enabled uses exit 1 for a correctly disabled unit.
    # Accept ONLY the two explicitly known (state, exit-code) pairs.
    if args[:2] == ("systemctl", "is-enabled"):
        if (p.returncode, state) in ((0, "enabled"), (1, "disabled")):
            return state
        raise RuntimeError("unexpected unit enablement: " + " ".join(args))
    if p.returncode:
        raise RuntimeError("operation failed: " + " ".join(args))
    return state


def local_json(port, path, *, seconds=3):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=seconds) as result:
        return json.load(result)


def no_active_work():
    health = local_json(11435, "/health")
    state = local_json(11435, "/status")
    running = local_json(11434, "/api/ps")
    if health.get("status") != "ok" or health.get("ollama") != "ok":
        raise RuntimeError("Gateway or Ollama unhealthy")
    if (state.get("gpu_residency", {}).get("state") != "llm"
            or state["gpu_residency"].get("recovery_required") is not False
            or state.get("max_concurrency") != 1
            or state.get("admission_blocked") is not False
            or any(state.get(key) != 0 for key in ("active_count", "queued_count"))
            or state.get("resource_leases", {}).get("lease_count") != 0):
        raise RuntimeError("RM busy, blocked or residency uncertain")
    if running.get("models") != []:
        raise RuntimeError("Ollama has loaded models; refusing ComfyUI startup")


def expected_known_enablement():
    # A prior interrupted application may already have disabled some/all units.
    # Only accept enabled/disabled, never masked/static/not-found/ambiguous.
    for name in AUTOSTART:
        command("systemctl", "is-enabled", name)


def no_other_gpu_users():
    base.idle(True)  # root fuser for cross-UID owners; fails closed on unknown


def check_before():
    base.baseline(started=CORE)  # all other services off + pinned production SHA
    expected_known_enablement()
    no_active_work()
    base.idle(False)  # read-only KFD check, cross-UID fuser deferred to --apply


def read_comfy_ready():
    if base.prop(COMFY, "ActiveState") != "active":
        raise RuntimeError("ComfyUI service not active")
    hardware = local_json(8188, "/system_stats")
    devices = hardware.get("devices", [])
    if not isinstance(devices, list) or not any(
        isinstance(d, dict) and "AMD Radeon 890M" in str(d.get("name", ""))
        for d in devices
    ):
        raise RuntimeError("ComfyUI is not using the expected GPU")
    snapshot = local_json(8188, "/ai-platform/residency")
    if not (snapshot.get("schema_version") == 1
            and snapshot.get("queue_running") == 0
            and snapshot.get("queue_pending") == 0
            and snapshot.get("loaded_models") == 0
            and snapshot.get("cleanup_pending") is False):
        raise RuntimeError("ComfyUI residency extension not idle/ready")
    queue = local_json(8188, "/queue")
    if queue.get("queue_running") != [] or queue.get("queue_pending") != []:
        raise RuntimeError("ComfyUI queue not empty")


def wait_ready():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if base.prop(COMFY, "ActiveState") != "active":
            raise RuntimeError("ComfyUI startup failed")
        try:
            read_comfy_ready()
            return
        except (OSError, ValueError, RuntimeError):
            time.sleep(.5)
    raise RuntimeError("ComfyUI readiness timeout")


def apply():
    check_before()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError("operator terminal required for --apply")
    command("sudo", "-v")
    base.baseline(started=CORE)
    no_active_work()
    no_other_gpu_users()
    # These units were already inactive, so disable affects NEXT BOOT only.
    # Resume safely after a prior partial/complete disable; do not reenable.
    needs_disable = tuple(
        unit for unit in AUTOSTART
        if command("systemctl", "is-enabled", unit) == "enabled"
    )
    if needs_disable:
        command("sudo", "-n", "systemctl", "disable", *needs_disable)
    for name in AUTOSTART:
        if command("systemctl", "is-enabled", name) != "disabled":
            raise RuntimeError("autostart disable not verified: " + name)
    base.baseline(started=CORE)
    no_active_work()
    no_other_gpu_users()

    started = False
    try:
        # Start one managed systemd engine for the current session only.
        # Treat even a failed start command as possibly having spawned a unit.
        started = True
        command("sudo", "-n", "systemctl", "start", COMFY)
        wait_ready()
        no_active_work()
        for unit in CORE:
            if base.prop(unit, "ActiveState") != "active":
                raise RuntimeError("core service changed: " + unit)
        for name in AUTOSTART:
            if command("systemctl", "is-enabled", name) != "disabled":
                raise RuntimeError("autostart changed unexpectedly: " + name)
    except BaseException:
        if started:
            # Stop only this newly started engine, never Gateway or Ollama.
            try:
                command("sudo", "-n", "systemctl", "stop", COMFY)
            except Exception:
                pass  # leave failure explicit, operator must inspect systemd
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    opts = parser.parse_args()
    with tempfile.NamedTemporaryFile(mode="w", prefix="rm-autostart-", suffix=".json",
                                     dir=Path.cwd(), delete=False) as f:
        report_path = Path(f.name)
    report = {"status": "BLOCKED", "apply": opts.apply, "automatic_n1": "NOT_ADMITTED"}
    def save():
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    save()
    print("REPORT=" + str(report_path), flush=True)
    try:
        if os.geteuid() == 0:
            raise RuntimeError("run as normal operator, not root")
        with LOCK.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if opts.apply:
                apply()
                report["status"] = "AUTOSTART_DISABLED_COMFY_READY"
            else:
                check_before()
                report["status"] = "READ_ONLY_PREFLIGHT_PASS"
                report["gpu_visibility"] = "CROSS_UID_FUSER_REQUIRED_ON_APPLY"
    except BaseException as err:
        report["reason"] = type(err).__name__ + ": " + str(err)
    save()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
