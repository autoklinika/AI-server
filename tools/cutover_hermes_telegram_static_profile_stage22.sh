#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
STATE_FILE="${HERMES_HOME}/gateway_state.json"
BACKUP="${HERMES_HOME}/config.yaml.pre-telegram-static-stage22"
TARGET_PROFILE="terminal,file,web"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service is not active"; exit 1; }

section "STAGE-22 TELEGRAM STATIC PROFILE CUTOVER"
say "Target Telegram toolsets: [terminal, file, web]"
say "Only Hermes Telegram tool selection is changed."
say "CLI/global toolsets, reasoning, Gateway, Ollama and ventilation routing are untouched."
say "Backup: $BACKUP"

section "PRECHECK"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
p = Path(sys.argv[1])
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
platform = cfg.get("platform_toolsets") or {}
telegram = platform.get("telegram") if isinstance(platform, dict) else None
print("agent.reasoning_effort:", repr(reasoning))
print("current platform_toolsets.telegram:", repr(telegram))
if reasoning != "none":
    raise SystemExit("FAIL: expected literal agent.reasoning_effort='none'")
PY

"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    s = json.load(r)
print("Gateway active_count:", s.get("active_count"), "queued_count:", s.get("queued_count"), "max_concurrency:", s.get("max_concurrency"))
print("PASS: AI Gateway healthy")
PY

section "BACKUP"
if [ ! -e "$BACKUP" ]; then
    cp --preserve=mode,timestamps "$HERMES_CONFIG" "$BACKUP"
    say "PASS: created backup $BACKUP"
else
    [ -r "$BACKUP" ] || { say "FAIL: existing backup is not readable: $BACKUP"; exit 1; }
    say "INFO: backup already exists; preserving it unchanged: $BACKUP"
fi

section "ATOMIC CONFIG UPDATE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import os, sys, tempfile, yaml

path = Path(sys.argv[1])
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

agent = cfg.setdefault("agent", {})
if not isinstance(agent, dict):
    raise SystemExit("FAIL: config.agent is not a mapping")
if agent.get("reasoning_effort") != "none":
    raise SystemExit("FAIL: refusing to change config because agent.reasoning_effort is not literal 'none'")

platform = cfg.setdefault("platform_toolsets", {})
if not isinstance(platform, dict):
    raise SystemExit("FAIL: config.platform_toolsets is not a mapping")
platform["telegram"] = ["terminal", "file", "web"]

fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".stage22.", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp_name, path.stat().st_mode)
    os.replace(tmp_name, path)
finally:
    try:
        os.unlink(tmp_name)
    except FileNotFoundError:
        pass
print("PASS: wrote platform_toolsets.telegram = ['terminal', 'file', 'web'] atomically")
PY

section "VALIDATE CONFIG + INSTALLED HERMES RESOLUTION"
cd "$HERMES_SOURCE"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
p = Path(sys.argv[1])
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
platform = cfg.get("platform_toolsets") or {}
telegram = platform.get("telegram") if isinstance(platform, dict) else None
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
print("raw platform_toolsets.telegram:", repr(telegram))
print("agent.reasoning_effort:", repr(reasoning))
if telegram != ["terminal", "file", "web"]:
    raise SystemExit(f"FAIL: unexpected Telegram toolsets: {telegram!r}")
if reasoning != "none":
    raise SystemExit("FAIL: reasoning_effort changed unexpectedly")

from hermes_cli.tools_config import _get_platform_tools
resolved = sorted(_get_platform_tools(cfg, "telegram"))
print("Hermes resolved Telegram toolsets:", resolved)
if set(resolved) != {"terminal", "file", "web"}:
    raise SystemExit(f"FAIL: installed Hermes resolved unexpected toolsets: {resolved!r}")
print("PASS: installed Hermes resolves the target Telegram profile")
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
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=3) as r:
    s = json.load(r)
print("Gateway active_count:", s.get("active_count"), "queued_count:", s.get("queued_count"))
print("PASS: AI Gateway healthy")
PY

section "DONE"
say "PASS: Stage-22 Telegram static profile cutover completed"
say "Telegram profile is now: [terminal, file, web]"
say "Rollback script: tools/rollback_hermes_telegram_static_profile_stage22.sh"
say "Backup retained: $BACKUP"
say "Next: measure one short Telegram reply, then test one real Telegram tool task."
