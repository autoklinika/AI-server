#!/usr/bin/env bash
set -euo pipefail

CURRENT="/opt/ai-platform/current"
WRAPPER="/usr/local/bin/generate-video-ltx23"
OUTPUT_DIR="$(mktemp -d /tmp/stage-e-media-smoke.XXXXXX)"

fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[[ -f "$CURRENT/RELEASE" ]] || fail "active release stamp missing"
grep -qx 'stage=E' "$CURRENT/RELEASE" || fail "active release is not Stage E"
[[ -x "$WRAPPER" ]] || fail "media wrapper missing"
grep -Fq '/opt/ai-platform/current/services/ai-bridge' "$WRAPPER" \
  || fail "media wrapper is not release-managed"
command -v ffprobe >/dev/null || fail "ffprobe not found"

BRIDGE_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value)"
GATEWAY_PID_BEFORE="$(systemctl show ai-gateway.service -p MainPID --value)"
COMFY_PID_BEFORE="$(systemctl show comfyui.service -p MainPID --value)"

"$WRAPPER" --preflight >/dev/null

ACTIVE_PYTHON="$CURRENT/services/ai-bridge/.venv/bin/python"
[[ -x "$ACTIVE_PYTHON" ]] || fail "active release Python missing"

PYTHONPATH="$CURRENT/services/ai-bridge/src:$CURRENT/services/ai-bridge/tools" \
"$ACTIVE_PYTHON" - "$WRAPPER" "$OUTPUT_DIR" <<'PY'
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

wrapper = sys.argv[1]
output_dir = Path(sys.argv[2])

from hermes_resource_queue import acquire_resource

GATEWAY = "http://127.0.0.1:11435"
COMFY = "http://127.0.0.1:8188"

def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("unexpected JSON shape")
    return value

def counts():
    status = get_json(GATEWAY + "/status")
    leases = status.get("resource_leases") or {}
    return status.get("active_count"), status.get("queued_count"), leases.get("lease_count")

def assert_idle():
    if counts() != (0, 0, 0):
        raise RuntimeError("Resource Manager not idle")
    queue = get_json(COMFY + "/queue")
    if (queue.get("queue_running") or []) or (queue.get("queue_pending") or []):
        raise RuntimeError("ComfyUI not idle")

if get_json(GATEWAY + "/health").get("status") != "ok":
    raise RuntimeError("Gateway unhealthy")
assert_idle()

lease = acquire_resource(
    target=None,
    source="stage-e-media-smoke",
    priority=50,
    workload="media-video",
)
try:
    status = get_json(GATEWAY + "/status")
    leases = (status.get("resource_leases") or {}).get("leases") or []
    matching = [
        item for item in leases
        if item.get("source") == "stage-e-media-smoke" and item.get("priority") == 50
    ]
    if status.get("active_count") != 1 or status.get("queued_count") != 0 or len(matching) != 1:
        raise RuntimeError("media lease not active")

    env = os.environ.copy()
    env["HERMES_RESOURCE_LEASE_ID"] = lease.lease_id
    process = subprocess.run(
        [
            wrapper,
            "--prompt", "Static workshop scene, a small metal gear on a clean workbench.",
            "--width", "640",
            "--height", "384",
            "--duration-seconds", "1",
            "--fps", "24",
            "--seed", "424242",
            "--timeout", "1800",
            "--output-dir", str(output_dir),
            "--json",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=1900,
    )
    if process.returncode != 0:
        raise RuntimeError("Stage30 render failed")

    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Stage30 returned no output")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        raise RuntimeError("Stage30 final output is not JSON") from None
    if payload.get("ok") is not True:
        raise RuntimeError("Stage30 returned failure")

    path = Path(str(payload.get("path") or ""))
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("generated media artifact missing")
    if payload.get("frames") != 25 or payload.get("fps") != 24:
        raise RuntimeError("unexpected Stage30 metadata")

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_read_frames",
            "-of", "json", str(path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0:
        raise RuntimeError("ffprobe failed")
    streams = json.loads(probe.stdout).get("streams") or []
    if len(streams) != 1:
        raise RuntimeError("unexpected stream count")
    video = streams[0]
    if video.get("codec_name") != "h264":
        raise RuntimeError("unexpected codec")
    if (video.get("width"), video.get("height")) != (640, 384):
        raise RuntimeError("unexpected dimensions")
    if Fraction(str(video.get("avg_frame_rate") or "0/1")) != Fraction(24, 1):
        raise RuntimeError("unexpected fps")
    if int(video.get("nb_read_frames") or 0) != 25:
        raise RuntimeError("unexpected frame count")

    queue = get_json(COMFY + "/queue")
    if (queue.get("queue_running") or []) or (queue.get("queue_pending") or []):
        raise RuntimeError("ComfyUI not idle after render")
    if counts() != (1, 0, 1):
        raise RuntimeError("media lease was not held for full render")
finally:
    lease.release()

assert_idle()
print("PASS: Stage E real media smoke")
PY

[[ "$(systemctl show ai-bridge.service -p MainPID --value)" == "$BRIDGE_PID_BEFORE" ]] \
  || fail "AI Bridge restarted during media smoke"
[[ "$(systemctl show ai-gateway.service -p MainPID --value)" == "$GATEWAY_PID_BEFORE" ]] \
  || fail "AI Gateway restarted during media smoke"
[[ "$(systemctl show comfyui.service -p MainPID --value)" == "$COMFY_PID_BEFORE" ]] \
  || fail "ComfyUI restarted during media smoke"

echo "PASS: Stage E media runtime validation"
