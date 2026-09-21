#!/usr/bin/env bash
set -euo pipefail

RELEASE_ID="${1:?usage: $0 RELEASE_ID}"
TARGET="/opt/ai-platform/releases/$RELEASE_ID"
CURRENT="/opt/ai-platform/current"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -d "$TARGET" ]] || fail "installed release missing: $TARGET"
[[ -f "$TARGET/RELEASE" ]] || fail "RELEASE stamp missing"
grep -qx "release_id=$RELEASE_ID" "$TARGET/RELEASE" || fail "release id mismatch"
grep -qx 'stage=C' "$TARGET/RELEASE" || fail "not a Stage C release"

CURRENT_BEFORE="$(readlink -f "$CURRENT")"
BRIDGE_PID_BEFORE="$(systemctl show ai-bridge.service -p MainPID --value)"
GATEWAY_PID_BEFORE="$(systemctl show ai-gateway.service -p MainPID --value)"
WRAPPER_SHA_BEFORE="$(sha256sum /usr/local/bin/generate-video-ltx23 | awk '{print $1}')"

echo "===== INSTALLED RELEASE CHECKSUMS ====="
(
  cd "$TARGET"
  sudo sha256sum -c metadata/SHA256SUMS >/dev/null
)
say "PASS: installed release checksums"

PYTHON="$TARGET/services/ai-bridge/.venv/bin/python"
GENERATOR="$TARGET/services/ai-bridge/tools/local_video/generate_ltx23_stage30.py"

echo "===== INSTALLED PROVIDER IMPORTS ====="
"$PYTHON" - <<'PY'
from ai_bridge.providers.contracts import LLMProvider, AgentProvider, MediaGenerationProvider
from ai_bridge.providers.ollama import OllamaAdapter
from ai_bridge.providers.hermes import HermesAdapter
from ai_bridge.providers.comfyui import ComfyUIAdapter
print("PASS: installed Stage C provider imports")
PY

echo "===== INSTALLED STAGE30 STANDARD PREFLIGHT ====="
"$PYTHON" "$GENERATOR" --preflight >/dev/null
say "PASS: installed Stage30 standard preflight"

echo "===== INSTALLED STAGE30 HQ + I2V PREFLIGHT ====="
"$PYTHON" "$GENERATOR" --i2v-preflight --upscale-2x >/dev/null
say "PASS: installed Stage30 HQ + I2V preflight"

echo "===== VERIFY PRODUCTION UNCHANGED ====="
[[ "$(readlink -f "$CURRENT")" == "$CURRENT_BEFORE" ]]   || fail "current release changed during validation"
[[ "$(systemctl show ai-bridge.service -p MainPID --value)" == "$BRIDGE_PID_BEFORE" ]]   || fail "AI Bridge PID changed during validation"
[[ "$(systemctl show ai-gateway.service -p MainPID --value)" == "$GATEWAY_PID_BEFORE" ]]   || fail "AI Gateway PID changed during validation"
[[ "$(sha256sum /usr/local/bin/generate-video-ltx23 | awk '{print $1}')" == "$WRAPPER_SHA_BEFORE" ]]   || fail "/wideo wrapper changed during validation"

say "PASS: current release unchanged"
say "PASS: AI Bridge PID unchanged"
say "PASS: AI Gateway PID unchanged"
say "PASS: /wideo wrapper unchanged"
echo "INSTALLED STAGE C RELEASE VALIDATION: PASS"
