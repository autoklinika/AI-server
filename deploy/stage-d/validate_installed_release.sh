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
grep -qx 'stage=D' "$TARGET/RELEASE" || fail "not a Stage D release"

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
BRIDGE_ENTRY="$TARGET/services/ai-bridge/.venv/bin/ai-bridge"
ANALYSIS_ENTRY="$TARGET/services/ai-bridge/.venv/bin/ai-bridge-analyze-ventilation"

echo "===== FINAL-PATH ENTRYPOINTS ====="
[[ -x "$BRIDGE_ENTRY" ]] || fail "installed AI Bridge entrypoint missing"
[[ -x "$ANALYSIS_ENTRY" ]] || fail "installed analysis entrypoint missing"
BRIDGE_SHEBANG="$(head -1 "$BRIDGE_ENTRY")"
ANALYSIS_SHEBANG="$(head -1 "$ANALYSIS_ENTRY")"
echo "ai-bridge: $BRIDGE_SHEBANG"
echo "analysis:  $ANALYSIS_SHEBANG"
[[ "$BRIDGE_SHEBANG" == "#!$TARGET/services/ai-bridge/.venv/bin/python"* ]]   || fail "AI Bridge entrypoint is not bound to installed release"
[[ "$ANALYSIS_SHEBANG" == "#!$TARGET/services/ai-bridge/.venv/bin/python"* ]]   || fail "analysis entrypoint is not bound to installed release"
[[ "$BRIDGE_SHEBANG" != *"/tmp/"* ]] || fail "AI Bridge entrypoint references /tmp"
[[ "$ANALYSIS_SHEBANG" != *"/tmp/"* ]] || fail "analysis entrypoint references /tmp"
say "PASS: installed entrypoints use final release path"

echo "===== INSTALLED PROVIDER IMPORTS ====="
"$PYTHON" - <<'PY'
from ai_bridge.providers.contracts import LLMProvider, AgentProvider, MediaGenerationProvider, EmbeddingProvider, KnowledgeBackend
from ai_bridge.providers.ollama import OllamaAdapter
from ai_bridge.providers.hermes import HermesAdapter
from ai_bridge.providers.comfyui import ComfyUIAdapter
print("PASS: installed Stage D provider contract imports")
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
echo "INSTALLED STAGE D RELEASE VALIDATION: PASS"
