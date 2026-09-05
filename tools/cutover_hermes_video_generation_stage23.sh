#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
CONFIG_BACKUP="${HERMES_HOME}/config.yaml.pre-video-gen-stage23"
ENV_FILE="${HERMES_HOME}/video-gen.env"
ENV_BACKUP="${HERMES_HOME}/video-gen.env.pre-video-gen-stage23"
ENV_ABSENT_MARKER="${HERMES_HOME}/.video-gen-env-absent-pre-stage23"
DROPIN_DIR="${HOME}/.config/systemd/user/hermes-gateway.service.d"
DROPIN_FILE="${DROPIN_DIR}/30-video-gen.conf"
DROPIN_BACKUP="${DROPIN_FILE}.pre-video-gen-stage23"
DROPIN_ABSENT_MARKER="${HERMES_HOME}/.video-gen-dropin-absent-pre-stage23"

PROVIDER="${1:-fal}"
case "$PROVIDER" in
    fal) KEY_VAR="FAL_KEY" ;;
    xai) KEY_VAR="XAI_API_KEY" ;;
    deepinfra) KEY_VAR="DEEPINFRA_API_KEY" ;;
    *)
        printf 'FAIL: unsupported provider: %s\n' "$PROVIDER" >&2
        printf 'Supported providers: fal, xai, deepinfra\n' >&2
        exit 2
        ;;
esac

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service is not active"; exit 1; }

section "STAGE-23 HERMES VIDEO GENERATION CUTOVER"
say "Provider: $PROVIDER"
say "Required credential: $KEY_VAR"
say "Telegram target toolsets: [terminal, file, web, video_gen]"
say "No AI Gateway, Ollama, ventilation routing or reasoning settings are changed."
say "No paid generation is executed by this deployment script."

section "PRECHECK HERMES CAPABILITY"
[ -f "${HERMES_SOURCE}/toolsets.py" ] || { say "FAIL: Hermes toolsets.py missing"; exit 1; }
grep -q '"video_gen"' "${HERMES_SOURCE}/toolsets.py" || { say "FAIL: installed Hermes does not expose video_gen toolset"; exit 1; }
[ -d "${HERMES_SOURCE}/plugins/video_gen/${PROVIDER}" ] || {
    say "FAIL: installed Hermes has no bundled video provider: ${PROVIDER}"
    exit 1
}
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
p = Path(sys.argv[1])
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
if not isinstance(cfg, dict):
    raise SystemExit("FAIL: Hermes config is not a YAML mapping")
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
platform = cfg.get("platform_toolsets") or {}
telegram = platform.get("telegram") if isinstance(platform, dict) else None
print("agent.reasoning_effort:", repr(reasoning))
print("current platform_toolsets.telegram:", repr(telegram))
print("current video_gen:", repr(cfg.get("video_gen")))
if reasoning != "none":
    raise SystemExit("FAIL: expected literal agent.reasoning_effort='none'")
allowed = (["terminal", "file", "web"], ["terminal", "file", "web", "video_gen"])
if telegram not in allowed:
    raise SystemExit(f"FAIL: refusing to overwrite unexpected Telegram toolsets: {telegram!r}")
PY

section "ACQUIRE PROVIDER CREDENTIAL"
current_key="${!KEY_VAR-}"
if [ -z "$current_key" ] && [ -r "$ENV_FILE" ]; then
    current_key="$($HERMES_PYTHON - "$ENV_FILE" "$KEY_VAR" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k.strip() != key:
        continue
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
        v = v[1:-1]
    print(v)
    break
PY
)"
fi

if [ -z "$current_key" ]; then
    if [ -t 0 ]; then
        read -r -s -p "Enter ${KEY_VAR}: " current_key
        printf '\n'
    else
        say "FAIL: ${KEY_VAR} is not available."
        say "Export ${KEY_VAR} before running this script, or run interactively and enter it securely."
        exit 1
    fi
fi
[ -n "$current_key" ] || { say "FAIL: empty ${KEY_VAR}"; exit 1; }
export "${KEY_VAR}=${current_key}"
unset current_key
say "PASS: credential is available (value not displayed)"

section "BACKUP PRE-STAGE-23 STATE"
if [ ! -e "$CONFIG_BACKUP" ]; then
    cp --preserve=mode,timestamps "$HERMES_CONFIG" "$CONFIG_BACKUP"
    say "PASS: created config backup $CONFIG_BACKUP"

    if [ -e "$ENV_FILE" ]; then
        cp --preserve=mode,timestamps "$ENV_FILE" "$ENV_BACKUP"
        rm -f "$ENV_ABSENT_MARKER"
        say "PASS: backed up existing video env"
    else
        : > "$ENV_ABSENT_MARKER"
        chmod 600 "$ENV_ABSENT_MARKER"
        say "INFO: recorded that video env did not exist before Stage 23"
    fi

    if [ -e "$DROPIN_FILE" ]; then
        mkdir -p "$DROPIN_DIR"
        cp --preserve=mode,timestamps "$DROPIN_FILE" "$DROPIN_BACKUP"
        rm -f "$DROPIN_ABSENT_MARKER"
        say "PASS: backed up existing systemd drop-in"
    else
        : > "$DROPIN_ABSENT_MARKER"
        chmod 600 "$DROPIN_ABSENT_MARKER"
        say "INFO: recorded that video systemd drop-in did not exist before Stage 23"
    fi
else
    say "INFO: Stage-23 config backup already exists; preserving original pre-stage state"
fi

section "WRITE CREDENTIAL ENV FILE"
"$HERMES_PYTHON" - "$ENV_FILE" "$KEY_VAR" <<'PY'
from pathlib import Path
import os, sys, tempfile
path = Path(sys.argv[1])
key = sys.argv[2]
value = os.environ.get(key, "")
if not value:
    raise SystemExit(f"FAIL: {key} missing from process environment")
escaped = value.replace("\\", "\\\\").replace('"', '\\"')
content = f'{key}="{escaped}"\n'
path.parent.mkdir(parents=True, exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=path.name + ".stage23.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
print(f"PASS: wrote {path} with mode 0600")
PY

section "INSTALL USER SYSTEMD DROP-IN"
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN_FILE" <<EOF_DROPIN
[Service]
EnvironmentFile=${ENV_FILE}
EOF_DROPIN
chmod 600 "$DROPIN_FILE"
systemctl --user daemon-reload
say "PASS: installed $DROPIN_FILE"

section "ATOMIC HERMES CONFIG UPDATE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$PROVIDER" <<'PY'
from pathlib import Path
import os, sys, tempfile, yaml
path = Path(sys.argv[1])
provider = sys.argv[2]
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
if not isinstance(cfg, dict):
    raise SystemExit("FAIL: config is not a YAML mapping")
agent = cfg.setdefault("agent", {})
if not isinstance(agent, dict) or agent.get("reasoning_effort") != "none":
    raise SystemExit("FAIL: refusing update because agent.reasoning_effort is not literal 'none'")
platform = cfg.setdefault("platform_toolsets", {})
if not isinstance(platform, dict):
    raise SystemExit("FAIL: config.platform_toolsets is not a mapping")
current = platform.get("telegram")
allowed = (["terminal", "file", "web"], ["terminal", "file", "web", "video_gen"])
if current not in allowed:
    raise SystemExit(f"FAIL: refusing to overwrite unexpected Telegram toolsets: {current!r}")
platform["telegram"] = ["terminal", "file", "web", "video_gen"]
video = cfg.setdefault("video_gen", {})
if not isinstance(video, dict):
    raise SystemExit("FAIL: config.video_gen is not a mapping")
video["provider"] = provider
fd, tmp = tempfile.mkstemp(prefix=path.name + ".stage23.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, path.stat().st_mode)
    os.replace(tmp, path)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
print("PASS: enabled Telegram video_gen and configured provider", provider)
PY

section "VALIDATE INSTALLED HERMES RESOLUTION"
export HERMES_HOME
cd "$HERMES_SOURCE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$PROVIDER" <<'PY'
from pathlib import Path
import sys, yaml
config_path = Path(sys.argv[1])
provider = sys.argv[2]
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
platform = cfg.get("platform_toolsets") or {}
telegram = platform.get("telegram") if isinstance(platform, dict) else None
if telegram != ["terminal", "file", "web", "video_gen"]:
    raise SystemExit(f"FAIL: unexpected Telegram toolsets: {telegram!r}")
video = cfg.get("video_gen") or {}
if not isinstance(video, dict) or video.get("provider") != provider:
    raise SystemExit(f"FAIL: video_gen.provider mismatch: {video!r}")
from hermes_cli.tools_config import _get_platform_tools, _checklist_toolset_keys
resolved = set(_get_platform_tools(cfg, "telegram"))
configurable = set(_checklist_toolset_keys("telegram"))
resolved_configurable = resolved & configurable
expected = {"terminal", "file", "web", "video_gen"}
print("Hermes resolved configurable Telegram toolsets:", sorted(resolved_configurable))
if resolved_configurable != expected:
    raise SystemExit(f"FAIL: resolved configurable toolsets differ: {sorted(resolved_configurable)!r}")
import model_tools
model_tools._clear_tool_defs_cache()
defs = model_tools.get_tool_definitions(
    enabled_toolsets=sorted(resolved),
    quiet_mode=True,
    skip_tool_search_assembly=True,
)
visible = {
    str((tool.get("function") or {}).get("name") or "")
    for tool in defs
    if (tool.get("function") or {}).get("name")
}
base = {
    "terminal", "process_manage",
    "read_file", "write_file", "patch", "search_files",
    "web_search", "web_extract",
}
print("model-facing Telegram tools:", sorted(visible))
missing = base - visible
if missing:
    raise SystemExit(f"FAIL: existing Telegram tools disappeared: {sorted(missing)!r}")
if "video_generate" not in visible:
    raise SystemExit("FAIL: video_generate is not model-facing after Stage 23")
if any(name.startswith("kanban_") for name in visible):
    raise SystemExit("FAIL: kanban tools unexpectedly visible to Telegram model")
print("PASS: video_generate is model-facing and existing static tools remain present")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: hermes-gateway.service did not become active"; exit 1; }
say "PASS: Hermes service active"

section "WAIT FOR TELEGRAM + API"
"$HERMES_PYTHON" - "$STATE_FILE" <<'PY'
from pathlib import Path
import json, sys, time
path = Path(sys.argv[1])
deadline = time.monotonic() + 90
last = None
while time.monotonic() < deadline:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        time.sleep(1)
        continue
    last = state
    platforms = state.get("platforms") or {}
    if (
        state.get("gateway_state") == "running"
        and (platforms.get("telegram") or {}).get("state") == "connected"
        and (platforms.get("api_server") or {}).get("state") == "connected"
    ):
        print("PASS: Hermes gateway running, Telegram connected, API connected")
        break
    time.sleep(1)
else:
    print(json.dumps(last, ensure_ascii=False, indent=2) if last else "<no readable gateway_state>")
    raise SystemExit("FAIL: Hermes did not fully reconnect within 90 s")
PY

section "POSTCHECK"
"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
print("PASS: AI Gateway healthy")
PY

section "DONE"
say "PASS: Stage-23 Hermes video generation cutover completed"
say "Telegram toolsets: [terminal, file, web, video_gen]"
say "Video provider: $PROVIDER"
say "Credential: $KEY_VAR loaded via $ENV_FILE (value not displayed)"
say "Rollback: tools/rollback_hermes_video_generation_stage23.sh"
say "Next real test: ask Hermes on Telegram to generate one short 5-second 16:9 video."
