#!/usr/bin/env bash
set -euo pipefail

CURRENT="/opt/ai-platform/current"
WRAPPER="/usr/local/bin/generate-video-ltx23"
OUTPUT_DIR="/tmp/stage-d0-media-smoke"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -f "$CURRENT/RELEASE" ]] || fail "active release stamp missing"
grep -qx 'stage=D' "$CURRENT/RELEASE" || fail "active release is not Stage D"
grep -qx 'phase=D.0' "$CURRENT/RELEASE" || fail "active release is not D.0"
[[ -x "$WRAPPER" ]] || fail "media wrapper missing: $WRAPPER"
grep -Fq '/opt/ai-platform/current/services/ai-bridge' "$WRAPPER" \
  || fail "media wrapper is not release-managed"
command -v ffprobe >/dev/null || fail "ffprobe not found"

BRIDGE_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value)"
GATEWAY_PID_BEFORE="$(systemctl show ai-gateway.service -p MainPID --value)"
HERMES_PID_BEFORE="$(systemctl --user show hermes-gateway.service -p MainPID --value 2>/dev/null || true)"
COMFY_PID_BEFORE="$(systemctl show comfyui.service -p MainPID --value 2>/dev/null || true)"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

echo "===== D.0 MEDIA RUNTIME VALIDATION ====="
say "release=$(readlink -f "$CURRENT")"
say "wrapper=$WRAPPER"
say "output_dir=$OUTPUT_DIR"

echo
echo "===== PREFLIGHT ====="
"$WRAPPER" --preflight >/dev/null
say "PASS: Stage30 standard preflight"

echo
echo "===== RESOURCE MANAGER + REAL RENDER ====="
ACTIVE_PYTHON="$CURRENT/services/ai-bridge/.venv/bin/python"
[[ -x "$ACTIVE_PYTHON" ]] || fail "active release Python missing: $ACTIVE_PYTHON"

PYTHONPATH="$CURRENT/services/ai-bridge/src:$CURRENT/services/ai-bridge/tools" \
"$ACTIVE_PYTHON" - "$WRAPPER" "$OUTPUT_DIR" <<'PY'
from __future__ import annotations

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


def get_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"unexpected JSON shape from {url}")
    return value


def scheduler_counts() -> tuple[int | None, int | None, int | None]:
    status = get_json(GATEWAY + "/status")
    leases = status.get("resource_leases") or {}
    return (
        status.get("active_count"),
        status.get("queued_count"),
        leases.get("lease_count"),
    )


def assert_idle(label: str) -> None:
    counts = scheduler_counts()
    if counts != (0, 0, 0):
        raise RuntimeError(
            f"{label}: Resource Manager not idle "
            f"active={counts[0]} queued={counts[1]} leases={counts[2]}"
        )


def assert_comfy_idle(label: str) -> None:
    queue = get_json(COMFY + "/queue")
    running = queue.get("queue_running") or []
    pending = queue.get("queue_pending") or []
    if running or pending:
        raise RuntimeError(
            f"{label}: ComfyUI queue not idle "
            f"running={len(running)} pending={len(pending)}"
        )


assert_idle("precheck")
assert_comfy_idle("precheck")

lease = acquire_resource(
    target=None,
    source="d0-media-smoke",
    priority=50,
)
try:
    status = get_json(GATEWAY + "/status")
    leases = (status.get("resource_leases") or {}).get("leases") or []
    matching = [
        item
        for item in leases
        if item.get("source") == "d0-media-smoke"
        and item.get("priority") == 50
    ]
    if (
        status.get("active_count") != 1
        or status.get("queued_count") != 0
        or len(matching) != 1
    ):
        raise RuntimeError(f"media lease not active as expected: {status}")

    env = os.environ.copy()
    env["HERMES_RESOURCE_LEASE_ID"] = lease.lease_id
    process = subprocess.run(
        [
            wrapper,
            "--prompt",
            (
                "Static workshop scene, a small metal gear on a clean workbench, "
                "subtle realistic light movement, locked camera."
            ),
            "--width",
            "640",
            "--height",
            "384",
            "--duration-seconds",
            "1",
            "--fps",
            "24",
            "--seed",
            "424242",
            "--timeout",
            "1800",
            "--output-dir",
            str(output_dir),
            "--json",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=1900,
    )
    print(process.stdout, end="")
    if process.returncode != 0:
        raise RuntimeError(f"Stage30 render failed rc={process.returncode}")

    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Stage30 render returned no output")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Stage30 final output is not JSON: {lines[-1][:500]}"
        ) from exc
    if payload.get("ok") is not True:
        raise RuntimeError(f"Stage30 returned failure: {payload}")

    path = Path(str(payload.get("path") or ""))
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"generated media artifact missing/empty: {path}")
    if payload.get("frames") != 25 or payload.get("fps") != 24:
        raise RuntimeError(f"unexpected Stage30 render metadata: {payload}")

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {probe.stdout[:2000]}")
    info = json.loads(probe.stdout)
    streams = info.get("streams") or []
    if len(streams) != 1:
        raise RuntimeError(f"unexpected video stream count: {info}")
    video = streams[0]
    fps = Fraction(str(video.get("avg_frame_rate") or "0/1"))
    frames = int(video.get("nb_read_frames") or 0)
    if video.get("codec_name") != "h264":
        raise RuntimeError(f"unexpected codec: {video}")
    if (video.get("width"), video.get("height")) != (640, 384):
        raise RuntimeError(f"unexpected dimensions: {video}")
    if fps != Fraction(24, 1):
        raise RuntimeError(f"unexpected fps: {video}")
    if frames != 25:
        raise RuntimeError(f"unexpected frame count: {video}")

    assert_comfy_idle("post-render")
    held = scheduler_counts()
    if held != (1, 0, 1):
        raise RuntimeError(
            "media lease was not held for entire render: "
            f"active={held[0]} queued={held[1]} leases={held[2]}"
        )

    print(
        "PASS: real Stage30 media render under Resource Manager lease "
        f"path={path} codec=h264 size=640x384 fps=24 frames=25"
    )
finally:
    lease.release()

assert_idle("post-release")
assert_comfy_idle("post-release")
print("PASS: Resource Manager and ComfyUI returned to idle")
PY

echo
echo "===== PID REGRESSION CHECK ====="
BRIDGE_PID_AFTER="$(systemctl show ai-bridge.service -p MainPID --value)"
GATEWAY_PID_AFTER="$(systemctl show ai-gateway.service -p MainPID --value)"
HERMES_PID_AFTER="$(systemctl --user show hermes-gateway.service -p MainPID --value 2>/dev/null || true)"
COMFY_PID_AFTER="$(systemctl show comfyui.service -p MainPID --value 2>/dev/null || true)"

say "AI Bridge before=$BRIDGE_PID_BEFORE after=$BRIDGE_PID_AFTER"
say "AI Gateway before=$GATEWAY_PID_BEFORE after=$GATEWAY_PID_AFTER"
say "Hermes before=$HERMES_PID_BEFORE after=$HERMES_PID_AFTER"
say "ComfyUI before=$COMFY_PID_BEFORE after=$COMFY_PID_AFTER"

[[ "$BRIDGE_PID_AFTER" == "$BRIDGE_PID_BEFORE" ]] || fail "AI Bridge restarted during media smoke"
[[ "$GATEWAY_PID_AFTER" == "$GATEWAY_PID_BEFORE" ]] || fail "AI Gateway restarted during media smoke"
[[ "$HERMES_PID_AFTER" == "$HERMES_PID_BEFORE" ]] || fail "Hermes restarted during media smoke"
[[ "$COMFY_PID_AFTER" == "$COMFY_PID_BEFORE" ]] || fail "ComfyUI restarted during media smoke"

rm -rf "$OUTPUT_DIR"

echo
echo "D.0 MEDIA RUNTIME VALIDATION: PASS"
