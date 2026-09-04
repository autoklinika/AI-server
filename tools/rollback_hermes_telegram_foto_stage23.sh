#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_STATE="${HERMES_HOME}/gateway_state.json"
SKILL_DIR="${HERMES_HOME}/skills/foto"
SKILL_FILE="${SKILL_DIR}/SKILL.md"
SKILL_MARKER="${HERMES_HOME}/.stage23-foto-skill.sha256"
ROLLBACK_STATE="${HERMES_HOME}/.stage23-foto-rollback-config"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "ROLLBACK STAGE-23 HERMES TELEGRAM /FOTO"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing: $HERMES_PYTHON"
[ -r "$ROLLBACK_STATE" ] || fail "rollback state missing: $ROLLBACK_STATE"
rollback_config="$(cat "$ROLLBACK_STATE")"
[ -r "$rollback_config" ] || fail "rollback config missing: $rollback_config"
say "Config source: $rollback_config"

section "VERIFY MANAGED /FOTO SKILL"
if [ -e "$SKILL_FILE" ]; then
    [ -r "$SKILL_MARKER" ] || fail "$SKILL_FILE exists but Stage-23 marker is missing; refusing to delete it"
    expected_sha="$(cat "$SKILL_MARKER")"
    current_sha="$(sha256sum "$SKILL_FILE" | awk '{print $1}')"
    say "managed SHA: $expected_sha"
    say "current SHA: $current_sha"
    [ "$current_sha" = "$expected_sha" ] || fail "/foto skill was modified after Stage-23; refusing destructive rollback"
else
    say "INFO: /foto skill file already absent"
fi

section "RESTORE CONFIG"
cp --preserve=mode,timestamps "$rollback_config" "${HERMES_CONFIG}.stage23.rollback.tmp"
mv -f "${HERMES_CONFIG}.stage23.rollback.tmp" "$HERMES_CONFIG"
say "PASS: restored Hermes config"

section "REMOVE STAGE-23 SKILL"
if [ -e "$SKILL_FILE" ]; then
    rm -f "$SKILL_FILE"
    rmdir "$SKILL_DIR" 2>/dev/null || true
fi
rm -f "$SKILL_MARKER" "$ROLLBACK_STATE"
say "PASS: removed Stage-23 /foto skill and state markers"

section "VALIDATE RESTORED CONFIG"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
reasoning = (cfg.get("agent") or {}).get("reasoning_effort")
telegram = (cfg.get("platform_toolsets") or {}).get("telegram")
print("agent.reasoning_effort:", repr(reasoning), "type:", type(reasoning).__name__)
print("platform_toolsets.telegram:", repr(telegram))
if not isinstance(reasoning, str) or reasoning != "none":
    raise SystemExit("FAIL: rollback config does not preserve literal reasoning_effort='none'")
if telegram != ["terminal", "file", "web"]:
    raise SystemExit(f"FAIL: expected Stage-22 Telegram profile after rollback, got {telegram!r}")
print("PASS: restored Stage-22 Telegram profile")
PY

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || fail "Hermes did not become active"

section "WAIT FOR TELEGRAM + API"
"$HERMES_PYTHON" - "$HERMES_STATE" <<'PY'
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
say "PASS: Stage-23 /foto rollback completed"
say "Telegram profile restored to: [terminal, file, web]"
