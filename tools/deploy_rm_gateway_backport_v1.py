#!/usr/bin/env python3
"""Operator-only Gateway cutover/rollback, without touching Stage O release.

Default --check is read-only. --apply/--rollback require interactive sudo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "candidate"
MANIFEST = ROOT / "RM_GATEWAY_CANDIDATE_SHA256.json"
OLD = Path("/opt/ai-platform/releases/stage-o-28e3ea214660")
CURRENT = Path("/opt/ai-platform/current")
OVERLAY = Path("/opt/ai-platform/gateway-overlays/rm-engine-adapters-v1-0016bbe-hwpass")
DROPIN = Path("/etc/systemd/system/ai-gateway.service.d/99-rm-engine-adapters-v1.conf")
CONTENT = ("# RM engine adapters V1 — approved single-Gateway source overlay; "
           "Stage O remains immutable.\n"
           "[Service]\n"
           f"Environment=\"PYTHONPATH={OVERLAY}/src\"\n")
MODIFIED = {
    "gateway/app.py", "gateway/resource_leases.py",
    "gateway/engine_state.py", "gateway/engine_lifecycle.py",
}
RESULT = ROOT / "RM_GATEWAY_CUTOVER_RESULT.json"


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmd(*args):
    p = subprocess.run(args, text=True, capture_output=True, timeout=35)
    require(p.returncode == 0, "system command failed: " + " ".join(args))
    return p.stdout.strip()


def json_get(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:11435" + path, timeout=3) as r:
        return json.load(r)


def http_code(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:11435" + path, timeout=3) as r:
            return r.status
    except (OSError, ValueError):
        return 0


def current_idle(require_alive=True):
    require(CURRENT.resolve() == OLD, "Stage O baseline changed")
    require(cmd("systemctl", "get-default") == "multi-user.target", "host mode changed")
    for unit in ("ollama.service", "ai-bridge.service", "comfyui.service",
                 "ssh.service", "tailscaled.service"):
        require(cmd("systemctl", "is-active", unit) == "active", "service down: " + unit)
    for marker in ("/var/lib/ai-platform-gpu/residency.blocked",
                   "/var/lib/ai-platform-gpu/managed-worker.dirty",
                   "/home/harrypotter/.local/state/ai-platform/gpu-residency.blocked"):
        require(not Path(marker).exists(), "GPU DIRTY: " + marker)
    from urllib.request import build_opener, ProxyHandler
    opener = build_opener(ProxyHandler({}))
    with opener.open("http://127.0.0.1:11434/api/ps", timeout=4) as res:
        require(json.load(res).get("models") == [], "resident Ollama models")
    with opener.open("http://127.0.0.1:8188/ai-platform/residency", timeout=4) as res:
        r = json.load(res)
    require(r.get("schema_version") == 1 and
            all(r.get(k) == 0 for k in ("queue_running", "queue_pending", "loaded_models"))
            and r.get("cleanup_pending") is False, "ComfyUI busy/unknown")
    if require_alive:
        require(cmd("systemctl", "is-active", "ai-gateway.service") == "active",
                "Gateway not active")
        snap = json_get("/status")
        require(snap.get("active_count") == 0 and snap.get("queued_count") == 0
                and snap.get("admission_blocked") is False
                and snap.get("resource_leases", {}).get("lease_count") == 0
                and snap.get("gpu_residency", {}).get("state") == "llm",
                "Gateway busy, blocked or transition in progress")


def verify_candidate():
    require(CAND.is_dir(), "missing staged candidate")
    require(MANIFEST.is_file(), "missing staged candidate checksums")
    expected = json.loads(MANIFEST.read_text())
    observed = {}
    require(not any("__pycache__" in path.parts for path in CAND.rglob("*")),
            "staged Python cache present; rebuild before installation")
    for category in ("src", "benchmarks"):
        folder = CAND / category
        require(folder.is_dir() and not folder.is_symlink(),
                "missing candidate component: " + category)
        for path in folder.rglob("*"):
            require(not path.is_symlink(), "candidate symlink denied")
            if path.is_file() and "__pycache__" not in path.parts:
                observed[path.relative_to(CAND).as_posix()] = sha(path)
    require(observed == expected, "candidate modified or unmanifested")
    baseline_src = OLD / "services/ai-gateway/src/ai_bridge"
    for path in (CAND / "src/ai_bridge").rglob("*.py"):
        rel = path.relative_to(CAND / "src/ai_bridge").as_posix()
        if rel not in MODIFIED:
            require((baseline_src / rel).is_file()
                    and sha(path) == sha(baseline_src / rel),
                    "non-approved Python change: " + rel)
    prod_bench = OLD / "services/ai-gateway/benchmarks"
    for path in (CAND / "benchmarks").rglob("*"):
        if path.is_file():
            require(sha(path) == sha(prod_bench / path.relative_to(CAND / "benchmarks")),
                    "benchmarks changed")
    require(sha(CAND / "src/ai_bridge/gateway/residency.py") ==
            sha(baseline_src / "gateway/residency.py"), "residency not from Stage O")
    require(sha(CAND / "src/ai_bridge/gateway/scheduler.py") ==
            sha(baseline_src / "gateway/scheduler.py"), "scheduler not from Stage O")


def smoke(expect_new):
    deadline = time.monotonic() + 35
    last = None
    while time.monotonic() < deadline:
        try:
            health = json_get("/health")
            state = json_get("/status")
            good = (health.get("status") == "ok"
                    and health.get("ollama") == "ok"
                    and state.get("active_count") == 0
                    and state.get("queued_count") == 0
                    and state.get("admission_blocked") is False
                    and state.get("resource_leases", {}).get("lease_count") == 0
                    and state.get("gpu_residency", {}).get("state") == "llm")
            if good and expect_new:
                rm = state.get("resource_manager", {})
                good = (rm.get("schema_version") == 1
                        and rm.get("state") == "IDLE"
                        and rm.get("active_engine") is None
                        and {e.get("id") for e in rm.get("engines", [])}
                            == {"ollama", "comfyui", "vision"}
                        and next(e for e in rm["engines"] if e["id"] == "vision")
                            .get("execution_available") is False)
            elif good:
                good = "resource_manager" not in state
            if (good and http_code("/control/") == 200
                    and http_code("/api/v1/benchmarks") == 200
                    and http_code("/api/tags") == 200
                    and cmd("systemctl", "is-active", "ai-gateway.service") == "active"):
                return
            last = "smoke not yet ready"
        except Exception as e:
            last = type(e).__name__
        time.sleep(0.6)
    raise RuntimeError("Gateway smoke failed: " + str(last))


def installed_overlay_ok():
    require(DROPIN.is_file() and DROPIN.read_text() == CONTENT,
            "unknown override; refusing rollback")
    require(OVERLAY.is_dir(), "installed source missing")
    expected = json.loads((OVERLAY / "SOURCE_SHA256.json").read_text())
    for rel, digest in expected.items():
        require(sha(OVERLAY / rel) == digest, "overlay modified: " + rel)


def install_overlay():
    if OVERLAY.exists():
        # A previous interrupted application may have finished staging but
        # not installed the drop-in. Reuse only the root-owned exact candidate.
        require(OVERLAY.is_dir() and not OVERLAY.is_symlink(),
                "invalid pre-existing overlay")
        expected = json.loads((OVERLAY / "SOURCE_SHA256.json").read_text())
        require(expected == json.loads(MANIFEST.read_text()),
                "pre-existing overlay manifest changed")
        for rel, digest in expected.items():
            path = OVERLAY / rel
            require(path.is_file() and not path.is_symlink()
                    and path.stat().st_uid == 0 and sha(path) == digest,
                    "pre-existing overlay file changed: " + rel)
        return
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    temp = OVERLAY.parent / (OVERLAY.name + ".building")
    require(not temp.exists(), "stale build directory")
    temp.mkdir(mode=0o755)
    try:
        for category in ("src", "benchmarks"):
            shutil.copytree(CAND / category, temp / category)
        shutil.copy2(MANIFEST, temp / "SOURCE_SHA256.json")
        for file in temp.rglob("*"):
            require(not file.is_symlink(), "installed symlink denied")
            file.chmod(0o755 if file.is_dir() else 0o644)
        os.rename(temp, OVERLAY)
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise
    installed_hashes = json.loads(MANIFEST.read_text())
    for rel, digest in installed_hashes.items():
        require(sha(OVERLAY / rel) == digest, "installed checksum mismatch")


def set_override():
    require(not DROPIN.exists(), "Gateway override already exists")
    # Atomic publication: interrupted writes cannot leave a partial systemd
    # configuration file for the next boot.
    import tempfile
    fd, temp_name = tempfile.mkstemp(prefix=".99-rm-engine-", dir=DROPIN.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(CONTENT)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, DROPIN)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def rollback_internal():
    if DROPIN.exists():
        require(DROPIN.read_text() == CONTENT, "unexpected override bytes")
    cmd("systemctl", "stop", "ai-gateway.service")
    if DROPIN.exists():
        DROPIN.unlink()
    cmd("systemctl", "daemon-reload")
    cmd("systemctl", "start", "ai-gateway.service")
    smoke(False)


def run(action):
    data = {
        "schema": 1, "action": action, "result": "BLOCKED",
        "prior_release": str(OLD), "candidate": str(OVERLAY),
        "driver_reuse": "NOT_VERIFIED", "vision_gpu_grant": "NOT_ADMITTED",
    }
    RESULT.write_text(json.dumps(data, indent=2) + "\n")
    try:
        if action in ("check", "apply"):
            verify_candidate()
        if action == "check":
            require(not DROPIN.exists(), "unknown existing gateway overlay")
            current_idle()
            data["result"] = "PREFLIGHT_PASS"
        else:
            require(os.geteuid() == 0 and sys.stdin.isatty(),
                    "apply/rollback requires interactive sudo, run as operator")
            if action == "apply":
                require(not DROPIN.exists(), "existing override")
                current_idle()
                install_overlay()
                # Stop only Gateway; the known production release stays intact.
                cmd("systemctl", "stop", "ai-gateway.service")
                try:
                    set_override()
                    cmd("systemctl", "daemon-reload")
                    cmd("systemctl", "start", "ai-gateway.service")
                    smoke(True)
                    current_idle()
                    data["result"] = "GATEWAY_CUTOVER_PASS"
                except BaseException:
                    # Always attempt old Gateway recovery, without deleting markers.
                    try:
                        rollback_internal()
                        data["rollback_result"] = "OLD_GATEWAY_RESTORED"
                    except BaseException as recovery:
                        data["rollback_result"] = ("ROLLBACK_FAILED: " +
                                                   type(recovery).__name__)
                    raise
            else:
                installed_overlay_ok()
                # An unhealthy/dead Gateway may still require rollback; in that
                # case check both engines and dirty markers independently.
                gateway = subprocess.run(
                    ("systemctl", "is-active", "ai-gateway.service"),
                    capture_output=True, text=True, timeout=5)
                current_idle(require_alive=(gateway.returncode == 0
                                            and gateway.stdout.strip() == "active"))
                rollback_internal()
                current_idle()
                data["result"] = "OLD_GATEWAY_ROLLBACK_PASS"
    except BaseException as error:
        data["reason"] = type(error).__name__ + ": " + str(error)[:240]
    RESULT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps(data, indent=2, sort_keys=True), flush=True)
    return 0 if data["result"] != "BLOCKED" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    opts = parser.parse_args()
    raise SystemExit(run("apply" if opts.apply else "rollback" if opts.rollback else "check"))
