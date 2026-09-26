#!/usr/bin/env python3
"""Controlled Discord technical-only plugin production gate.

Mutates only the user-owned Hermes ai-platform-messaging plugin and restarts
only hermes-gateway.service. AI Platform services are never restarted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "integrations/hermes/ai-platform-messaging"
LIVE = Path("/srv/ai-data/hermes/plugins/ai-platform-messaging")
HERMES = Path("/srv/ai-data/hermes")
STATE_ROOT = HERMES / "ai-platform-discord-policy"
GATEWAY_STATE = HERMES / "gateway_state.json"
PLATFORM_STATUS = "http://127.0.0.1:11435/status"
POLICY_SMOKE = ROOT / "deploy/discord-technical/policy_smoke.py"
HERMES_PYTHON = HERMES / "hermes-agent/venv/bin/python"
FILES = ("__init__.py", "plugin.yaml")


def require(value, message="gate condition failed"):
    if not value:
        raise RuntimeError(message)


def run(args, *, env=None, timeout=120, check=True):
    result = subprocess.run(
        [str(x) for x in args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.stdout.strip()


def user_systemctl(*args, timeout=120, check=True):
    uid = os.getuid()
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    return run(
        ["systemctl", "--user", *args],
        env=env,
        timeout=timeout,
        check=check,
    )


def gateway_service_active():
    return (
        user_systemctl(
            "is-active",
            "hermes-gateway.service",
            timeout=10,
            check=False,
        )
        == "active"
    )


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(root):
    return {name: digest(Path(root) / name) for name in FILES}


def git_sha():
    return run(["git", "-C", ROOT, "rev-parse", "HEAD"])


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_once(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def platform_idle():
    with urlopen(PLATFORM_STATUS, timeout=15) as response:
        state = json.load(response)
    require(state.get("active_count") == 0, "AI Platform has active jobs")
    require(state.get("queued_count") == 0, "AI Platform has queued jobs")
    leases = state.get("resource_leases") or {}
    require(leases.get("lease_count") == 0, "AI Platform has active leases")


def gateway_snapshot():
    require(GATEWAY_STATE.is_file(), "Hermes gateway state missing")
    data = read_json(GATEWAY_STATE)
    require(data.get("gateway_state") == "running", "Hermes gateway not running")
    platforms = data.get("platforms") or {}
    for name in ("telegram", "discord", "api_server"):
        require((platforms.get(name) or {}).get("state") == "connected",
                f"Hermes {name} not connected")
    require(int(data.get("active_agents") or 0) == 0, "Hermes has active agents")
    return {
        "pid": int(data["pid"]),
        "telegram": platforms["telegram"]["state"],
        "discord": platforms["discord"]["state"],
        "api_server": platforms["api_server"]["state"],
    }


def wait_gateway(previous_pid=None, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            require(gateway_service_active())
            last = gateway_snapshot()
            if previous_pid is None or last["pid"] != previous_pid:
                return last
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"Hermes reconnect timeout: {last}")


def stop_gateway():
    previous = None
    if GATEWAY_STATE.exists():
        try:
            previous = int(read_json(GATEWAY_STATE).get("pid") or 0)
        except Exception:
            previous = None
    user_systemctl("stop", "hermes-gateway.service")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = user_systemctl(
            "is-active",
            "hermes-gateway.service",
            timeout=10,
            check=False,
        )
        if state in ("inactive", "failed"):
            return previous
        time.sleep(0.5)
    raise RuntimeError("Hermes did not stop")


def start_gateway(previous_pid=None):
    user_systemctl("start", "hermes-gateway.service")
    return wait_gateway(previous_pid)


def replace_tree(source):
    source = Path(source)
    require(all((source / name).is_file() for name in FILES), "plugin source incomplete")
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    staging = LIVE.with_name(".ai-platform-messaging-" + uuid4().hex)
    old = LIVE.with_name(".ai-platform-messaging-old-" + uuid4().hex)
    shutil.copytree(source, staging)
    moved_old = False
    try:
        if LIVE.exists():
            os.replace(LIVE, old)
            moved_old = True
        os.replace(staging, LIVE)
    except Exception:
        if LIVE.exists() and not moved_old:
            shutil.rmtree(LIVE, ignore_errors=True)
        if moved_old and old.exists() and not LIVE.exists():
            os.replace(old, LIVE)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    if old.exists():
        shutil.rmtree(old)
    LIVE.chmod(0o775)
    for name in FILES:
        (LIVE / name).chmod(0o664)


def candidate_contract():
    require(CANDIDATE.is_dir(), "candidate plugin missing")
    source = (CANDIDATE / "__init__.py").read_text(encoding="utf-8")
    manifest = (CANDIDATE / "plugin.yaml").read_text(encoding="utf-8")
    require("version: 1.1.0" in manifest, "candidate manifest version mismatch")
    for marker in (
        "discord-technical-only",
        "/api/v1/knowledge/ask",
        "general Hermes agent",
        "Foto, wideo i pozostałe załączniki są wyłączone",
        'if _safe_command(event) == "voice"',
        'source.platform.value == "discord"',
    ):
        require(marker in source, f"candidate policy marker missing: {marker}")
    run([sys.executable, "-m", "py_compile", CANDIDATE / "__init__.py"])


def installed_candidate():
    require(LIVE.is_dir(), "installed plugin missing")
    require(hashes(LIVE) == hashes(CANDIDATE), "installed plugin does not match candidate")


def state_dir(source_sha):
    return STATE_ROOT / source_sha


def preflight(source_sha):
    require(source_sha == git_sha(), "source SHA does not match worktree HEAD")
    require(len(source_sha) == 40, "invalid source SHA")
    require(
        run(["git", "-C", ROOT, "status", "--porcelain"]) == "",
        "worktree must be clean",
    )
    candidate_contract()
    require(POLICY_SMOKE.is_file(), "policy smoke missing")
    require(HERMES_PYTHON.is_file(), "Hermes python missing")
    require(LIVE.is_dir(), "live plugin missing")
    require("ai-platform-messaging" in (HERMES / "config.yaml").read_text(encoding="utf-8"))
    platform_idle()
    gateway_snapshot()
    target = state_dir(source_sha)
    require(not (target / "accepted.json").exists(), "candidate already accepted")
    return {
        "source_sha": source_sha,
        "candidate_hashes": hashes(CANDIDATE),
        "baseline_hashes": hashes(LIVE),
    }


def ensure_baseline(source_sha):
    state = state_dir(source_sha)
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    baseline = state / "baseline-plugin"
    if baseline.exists():
        return
    shutil.copytree(LIVE, baseline)
    write_once(state / "baseline.json", {
        "source_sha": source_sha,
        "plugin_hashes": hashes(baseline),
        "captured_at": int(time.time()),
        "gateway": gateway_snapshot(),
    })


def install_and_restart(source):
    """Planned transition while Hermes is healthy and AI Platform is idle."""
    platform_idle()
    require(gateway_service_active(), "Hermes must be active before planned transition")
    before = gateway_snapshot()
    previous_pid = stop_gateway()
    replace_tree(source)
    after = start_gateway(previous_pid or before["pid"])
    return {"before": before, "after": after}


def force_restore_and_start(source):
    """Recovery transition that also works when Hermes is already stopped."""
    platform_idle()
    previous_pid = None
    if GATEWAY_STATE.exists():
        try:
            previous_pid = int(read_json(GATEWAY_STATE).get("pid") or 0) or None
        except Exception:
            previous_pid = None
    if gateway_service_active():
        stopped_pid = stop_gateway()
        previous_pid = stopped_pid or previous_pid
    replace_tree(source)
    return start_gateway(previous_pid)


def cutover(source_sha):
    ensure_baseline(source_sha)
    evidence = install_and_restart(CANDIDATE)
    installed_candidate()
    write_once(state_dir(source_sha) / "cutover.json", {
        "source_sha": source_sha,
        "candidate_hashes": hashes(CANDIDATE),
        "gateway": evidence,
        "time": int(time.time()),
    })


def run_policy_smoke(source_sha, name):
    installed_candidate()
    platform_idle()
    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES)
    env["PYTHONPATH"] = str(HERMES / "hermes-agent")
    raw = run([HERMES_PYTHON, POLICY_SMOKE], env=env, timeout=420)
    result = json.loads(raw.splitlines()[-1])
    require(result.get("status") == "PASS", "Discord policy smoke failed")
    for key in (
        "telegram_passthrough",
        "discord_general_agent_bypassed",
        "discord_knowledge_rag",
        "discord_citations",
        "discord_media_blocked",
        "discord_voice_command_passthrough",
        "discord_voice_rag",
        "tts",
    ):
        require(result.get(key) is True, f"smoke evidence failed: {key}")
    gateway = gateway_snapshot()
    platform_idle()
    write_once(state_dir(source_sha) / f"{name}.json", {
        "source_sha": source_sha,
        "status": "PASS",
        "policy": result,
        "gateway": gateway,
        "time": int(time.time()),
    })


def rollback(source_sha):
    state = state_dir(source_sha)
    baseline = state / "baseline-plugin"
    require(baseline.is_dir(), "baseline snapshot missing")
    install_and_restart(baseline)
    require(hashes(LIVE) == read_json(state / "baseline.json")["plugin_hashes"])
    write_once(state / "rollback.json", {
        "source_sha": source_sha,
        "status": "PASS",
        "gateway": gateway_snapshot(),
        "time": int(time.time()),
    })


def rollback_smoke(source_sha):
    state = state_dir(source_sha)
    baseline = read_json(state / "baseline.json")
    require(hashes(LIVE) == baseline["plugin_hashes"])
    platform_idle()
    gateway = gateway_snapshot()
    write_once(state / "rollback-smoke.json", {
        "source_sha": source_sha,
        "status": "PASS",
        "gateway": gateway,
        "time": int(time.time()),
    })


def reactivate(source_sha):
    install_and_restart(CANDIDATE)
    installed_candidate()
    write_once(state_dir(source_sha) / "reactivate.json", {
        "source_sha": source_sha,
        "status": "PASS",
        "gateway": gateway_snapshot(),
        "time": int(time.time()),
    })


def finalize(source_sha):
    state = state_dir(source_sha)
    require((state / "smoke.json").is_file())
    require((state / "rollback-smoke.json").is_file())
    require((state / "final-smoke.json").is_file())
    installed_candidate()
    write_once(state / "accepted.json", {
        "source_sha": source_sha,
        "status": "PASS",
        "plugin_version": "1.1.0",
        "candidate_hashes": hashes(CANDIDATE),
        "telegram_unchanged": True,
        "discord_policy": "technical-knowledge-only",
        "time": int(time.time()),
    })


def recover_to_baseline(source_sha):
    state = state_dir(source_sha)
    baseline = state / "baseline-plugin"
    if not baseline.is_dir():
        return
    try:
        if LIVE.is_dir() and hashes(LIVE) == hashes(baseline):
            if not gateway_service_active():
                start_gateway()
            return
    except Exception:
        pass
    try:
        force_restore_and_start(baseline)
        require(hashes(LIVE) == hashes(baseline))
    except Exception:
        # Do not mask the original failure, but leave a loud recovery marker.
        marker = state / "RECOVERY_FAILED"
        marker.write_text(str(int(time.time())), encoding="utf-8")
        raise


def all_gate(source_sha):
    evidence = preflight(source_sha)
    print("DISCORD_TECHNICAL_PREFLIGHT=PASS", flush=True)
    try:
        cutover(source_sha)
    except Exception:
        recover_to_baseline(source_sha)
        raise
    print("DISCORD_TECHNICAL_CUTOVER=PASS", flush=True)
    try:
        run_policy_smoke(source_sha, "smoke")
        print("DISCORD_TECHNICAL_SMOKE=PASS", flush=True)
    except Exception:
        recover_to_baseline(source_sha)
        rollback_smoke(source_sha)
        raise

    rollback(source_sha)
    print("DISCORD_TECHNICAL_ROLLBACK=PASS", flush=True)
    rollback_smoke(source_sha)
    print("DISCORD_TECHNICAL_ROLLBACK_SMOKE=PASS", flush=True)

    try:
        reactivate(source_sha)
        print("DISCORD_TECHNICAL_REACTIVATE=PASS", flush=True)
        run_policy_smoke(source_sha, "final-smoke")
        print("DISCORD_TECHNICAL_FINAL_SMOKE=PASS", flush=True)
    except Exception:
        recover_to_baseline(source_sha)
        raise

    finalize(source_sha)
    print("DISCORD_TECHNICAL_PRODUCTION_GATE=PASS", flush=True)


def main():
    require(len(sys.argv) == 3 and sys.argv[1] == "all",
            "usage: gate.py all <source-sha>")
    source_sha = sys.argv[2]
    all_gate(source_sha)


if __name__ == "__main__":
    main()
