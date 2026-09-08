#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SKILL_DIR="${HERMES_HOME}/skills/wideo"
OUTPUT_DIR="/srv/ai-data/hermes-media/video"
BACKUP_DIR="${HERMES_HOME}/stage23-local-video-backup"
LIBEXEC_DIR="/usr/local/libexec/ai-server"
GENERATOR_DST="${LIBEXEC_DIR}/generate_video.py"
CLI_DST="/usr/local/bin/generate-video"
TELEGRAM_DST="/usr/local/bin/generate-video-telegram"
COMFY_URL="http://127.0.0.1:8188"

MODEL_NAME="wan2.2_ti2v_5B_fp16.safetensors"
TEXT_NAME="umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE_NAME="wan2.2_vae.safetensors"

MODEL_URL="https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/${MODEL_NAME}"
TEXT_URL="https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/${TEXT_NAME}"
VAE_URL="https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/${VAE_NAME}"

MODEL_SHA256="456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e"
TEXT_SHA256="c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68"
VAE_SHA256="e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/local_video"
GENERATOR_SRC="${SOURCE_DIR}/generate_video.py"
TELEGRAM_SRC="${SOURCE_DIR}/generate-video-telegram"
SKILL_SRC="${SOURCE_DIR}/SKILL.md"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*" >&2; exit 1; }

[[ -r "$GENERATOR_SRC" ]] || fail "missing $GENERATOR_SRC"
[[ -r "$TELEGRAM_SRC" ]] || fail "missing $TELEGRAM_SRC"
[[ -r "$SKILL_SRC" ]] || fail "missing $SKILL_SRC"
command -v curl >/dev/null || fail "curl is required"
command -v python3 >/dev/null || fail "python3 is required"
command -v sha256sum >/dev/null || fail "sha256sum is required"

section "STAGE-23 LOCAL VIDEO"
say "Architecture: Hermes /wideo -> local wrapper -> ComfyUI -> Wan2.2 TI2V-5B -> local MP4"
say "Cloud video providers are not configured or used."
say "Existing FLUX image generation remains untouched."

section "SERVICE PRECHECK"
COMFY_SCOPE=""
if systemctl is-active --quiet comfyui.service 2>/dev/null; then
  COMFY_SCOPE="system"
elif systemctl --user is-active --quiet comfyui.service 2>/dev/null; then
  COMFY_SCOPE="user"
else
  fail "comfyui.service is not active"
fi

if ! systemctl --user is-active --quiet hermes-gateway.service 2>/dev/null; then
  fail "hermes-gateway.service is not active"
fi

if ! curl -fsS --max-time 5 "${COMFY_URL}/system_stats" >/dev/null; then
  fail "ComfyUI API is not reachable at ${COMFY_URL}"
fi
say "PASS: ComfyUI API reachable"
say "PASS: Hermes gateway active"

section "COMFYUI CAPABILITY PRECHECK"
python3 - "$COMFY_URL" <<'PY'
import json, sys, urllib.request
url = sys.argv[1].rstrip('/') + '/object_info'
required = {
    'UNETLoader', 'CLIPLoader', 'VAELoader', 'CLIPTextEncode',
    'ModelSamplingSD3', 'Wan22ImageToVideoLatent', 'KSampler',
    'VAEDecode', 'CreateVideo', 'SaveVideo', 'LoadImage',
}
with urllib.request.urlopen(url, timeout=30) as r:
    info = json.load(r)
missing = sorted(required - set(info))
print('required nodes:', ', '.join(sorted(required)))
if missing:
    raise SystemExit('FAIL: installed ComfyUI is too old; missing nodes: ' + ', '.join(missing))
print('PASS: installed ComfyUI exposes every Wan2.2/API node required by Stage 23')
PY

section "DISCOVER COMFYUI PATHS"
if [[ "$COMFY_SCOPE" == "system" ]]; then
  MAIN_PID="$(systemctl show comfyui.service -p MainPID --value)"
  WORKDIR="$(systemctl show comfyui.service -p WorkingDirectory --value 2>/dev/null || true)"
else
  MAIN_PID="$(systemctl --user show comfyui.service -p MainPID --value)"
  WORKDIR="$(systemctl --user show comfyui.service -p WorkingDirectory --value 2>/dev/null || true)"
fi

COMFY_ROOT=""
if [[ "$MAIN_PID" =~ ^[0-9]+$ ]] && [[ "$MAIN_PID" != "0" ]] && [[ -e "/proc/${MAIN_PID}/cwd" ]]; then
  COMFY_ROOT="$(readlink -f "/proc/${MAIN_PID}/cwd" 2>/dev/null || true)"
fi
if [[ -z "$COMFY_ROOT" && -n "$WORKDIR" && -d "$WORKDIR" ]]; then
  COMFY_ROOT="$WORKDIR"
fi
[[ -n "$COMFY_ROOT" && -d "$COMFY_ROOT" ]] || fail "could not discover ComfyUI working directory"

COMFY_MODELS_DIR="$(python3 - "$COMFY_URL" "$COMFY_ROOT" <<'PY'
from pathlib import Path
import json, sys, urllib.request
base = sys.argv[1].rstrip('/')
root = Path(sys.argv[2])
with urllib.request.urlopen(base + '/system_stats', timeout=10) as r:
    stats = json.load(r)
argv = list((stats.get('system') or {}).get('argv') or [])
models = None
for i, arg in enumerate(argv):
    if arg == '--models-directory' and i + 1 < len(argv):
        models = argv[i + 1]
        break
    if isinstance(arg, str) and arg.startswith('--models-directory='):
        models = arg.split('=', 1)[1]
        break
path = Path(models).expanduser() if models else (root / 'models')
if not path.is_absolute():
    path = root / path
print(path.resolve())
PY
)"

[[ -n "$COMFY_MODELS_DIR" ]] || fail "could not resolve ComfyUI models directory"
LEGACY_MODELS_DIR="${COMFY_ROOT}/models"
say "ComfyUI root:       $COMFY_ROOT"
say "ComfyUI models dir: $COMFY_MODELS_DIR"
if [[ "$LEGACY_MODELS_DIR" != "$COMFY_MODELS_DIR" ]]; then
  say "Legacy/default dir:  $LEGACY_MODELS_DIR"
fi

MODEL_DIR="${COMFY_MODELS_DIR}/diffusion_models"
TEXT_DIR="${COMFY_MODELS_DIR}/text_encoders"
VAE_DIR="${COMFY_MODELS_DIR}/vae"
mkdir -p "$MODEL_DIR" "$TEXT_DIR" "$VAE_DIR" || fail "cannot create/access ComfyUI model directories"

LEGACY_MODEL_PATH="${LEGACY_MODELS_DIR}/diffusion_models/${MODEL_NAME}"
LEGACY_TEXT_PATH="${LEGACY_MODELS_DIR}/text_encoders/${TEXT_NAME}"
LEGACY_VAE_PATH="${LEGACY_MODELS_DIR}/vae/${VAE_NAME}"

verify_sha() {
  local path="$1" expected="$2"
  [[ -s "$path" ]] || return 1
  printf '%s  %s\n' "$expected" "$path" | sha256sum --check --status
}

section "DISK PRECHECK"
NEEDS_DOWNLOAD=0
if ! verify_sha "${MODEL_DIR}/${MODEL_NAME}" "$MODEL_SHA256" && ! verify_sha "$LEGACY_MODEL_PATH" "$MODEL_SHA256"; then
  NEEDS_DOWNLOAD=1
fi
if ! verify_sha "${TEXT_DIR}/${TEXT_NAME}" "$TEXT_SHA256" && ! verify_sha "$LEGACY_TEXT_PATH" "$TEXT_SHA256"; then
  NEEDS_DOWNLOAD=1
fi
if ! verify_sha "${VAE_DIR}/${VAE_NAME}" "$VAE_SHA256" && ! verify_sha "$LEGACY_VAE_PATH" "$VAE_SHA256"; then
  NEEDS_DOWNLOAD=1
fi
if (( NEEDS_DOWNLOAD > 0 )); then
  AVAIL_BYTES="$(df -B1 --output=avail "$COMFY_MODELS_DIR" | tail -n1 | tr -d ' ')"
  MIN_BYTES=$((24 * 1024 * 1024 * 1024))
  if [[ "$AVAIL_BYTES" =~ ^[0-9]+$ ]] && (( AVAIL_BYTES < MIN_BYTES )); then
    fail "less than 24 GiB free on ComfyUI models filesystem; refusing model download"
  fi
else
  say "PASS: all required weights already exist either in the active or recoverable legacy location"
fi
say "PASS: storage precheck"

section "BACKUP PRE-STAGE-23 FILES"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

backup_root_file() {
  local src="$1" name="$2"
  if [[ -e "${BACKUP_DIR}/${name}" || -e "${BACKUP_DIR}/${name}.absent" ]]; then
    say "INFO: preserved existing Stage-23 backup marker for $src"
    return
  fi
  if sudo test -e "$src"; then
    sudo cp -a "$src" "${BACKUP_DIR}/${name}"
    sudo chown "$(id -u):$(id -g)" "${BACKUP_DIR}/${name}"
    say "PASS: backed up $src"
  else
    : > "${BACKUP_DIR}/${name}.absent"
    say "INFO: recorded absent pre-stage file $src"
  fi
}

backup_root_file "$GENERATOR_DST" "generate_video.py"
backup_root_file "$CLI_DST" "generate-video"
backup_root_file "$TELEGRAM_DST" "generate-video-telegram"

if [[ ! -e "${BACKUP_DIR}/skill-wideo" && ! -e "${BACKUP_DIR}/skill-wideo.absent" ]]; then
  if [[ -e "$HERMES_SKILL_DIR" ]]; then
    cp -a "$HERMES_SKILL_DIR" "${BACKUP_DIR}/skill-wideo"
    say "PASS: backed up existing Hermes wideo skill"
  else
    : > "${BACKUP_DIR}/skill-wideo.absent"
    say "INFO: recorded that wideo skill did not exist before Stage 23"
  fi
fi

section "PLACE LOCAL WAN2.2 MODELS"
MODELS_CHANGED=0

place_model() {
  local url="$1" dst="$2" expected_sha="$3" legacy="$4"

  if [[ -s "$dst" ]]; then
    say "Verifying active model: $(basename "$dst")"
    if verify_sha "$dst" "$expected_sha"; then
      say "PASS: active file checksum OK: $dst"
      return
    fi
    local bad="${dst}.corrupt.$(date +%Y%m%d-%H%M%S)"
    mv -f "$dst" "$bad"
    say "WARN: active file checksum mismatch; moved to $bad"
  fi

  if [[ "$legacy" != "$dst" && -s "$legacy" ]]; then
    say "Checking previously downloaded legacy copy: $legacy"
    if verify_sha "$legacy" "$expected_sha"; then
      mkdir -p "$(dirname "$dst")"
      mv -f "$legacy" "$dst"
      MODELS_CHANGED=1
      say "PASS: moved verified existing file into active ComfyUI models directory: $dst"
      return
    fi
    local legacy_bad="${legacy}.corrupt.$(date +%Y%m%d-%H%M%S)"
    mv -f "$legacy" "$legacy_bad"
    say "WARN: legacy file checksum mismatch; moved to $legacy_bad"
  fi

  local part="${dst}.part"
  say "Downloading: $(basename "$dst")"
  curl --fail --location --retry 4 --retry-delay 5 --continue-at - --output "$part" "$url"
  [[ -s "$part" ]] || fail "download produced empty file: $part"
  say "Verifying SHA-256: $(basename "$dst")"
  if ! verify_sha "$part" "$expected_sha"; then
    rm -f "$part"
    fail "SHA-256 mismatch after download: $(basename "$dst"); partial file removed"
  fi
  mv -f "$part" "$dst"
  sync "$dst" || true
  MODELS_CHANGED=1
  say "PASS: downloaded and verified $dst"
}

place_model "$MODEL_URL" "${MODEL_DIR}/${MODEL_NAME}" "$MODEL_SHA256" "$LEGACY_MODEL_PATH"
place_model "$TEXT_URL" "${TEXT_DIR}/${TEXT_NAME}" "$TEXT_SHA256" "$LEGACY_TEXT_PATH"
place_model "$VAE_URL" "${VAE_DIR}/${VAE_NAME}" "$VAE_SHA256" "$LEGACY_VAE_PATH"

if (( MODELS_CHANGED > 0 )); then
  section "RESTART COMFYUI TO REFRESH MODEL CATALOG"
  if [[ "$COMFY_SCOPE" == "system" ]]; then
    sudo systemctl restart comfyui.service
    sudo systemctl is-active --quiet comfyui.service || fail "comfyui.service did not restart cleanly"
  else
    systemctl --user restart comfyui.service
    systemctl --user is-active --quiet comfyui.service || fail "user comfyui.service did not restart cleanly"
  fi

  READY=0
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 "${COMFY_URL}/system_stats" >/dev/null 2>&1; then
      READY=1
      break
    fi
    sleep 1
  done
  (( READY == 1 )) || fail "ComfyUI API did not return after restart"
  say "PASS: ComfyUI restarted and API is reachable"
else
  say "INFO: model files already active; ComfyUI restart not required"
fi

section "INSTALL LOCAL GENERATOR"
sudo install -d -m 0755 "$LIBEXEC_DIR"
sudo install -m 0755 "$GENERATOR_SRC" "$GENERATOR_DST"
sudo install -m 0755 "$TELEGRAM_SRC" "$TELEGRAM_DST"

TMP_CLI="$(mktemp)"
cat > "$TMP_CLI" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/python3 /usr/local/libexec/ai-server/generate_video.py "$@"
EOF
sudo install -m 0755 "$TMP_CLI" "$CLI_DST"
rm -f "$TMP_CLI"
say "PASS: installed $CLI_DST"
say "PASS: installed $TELEGRAM_DST"

section "INSTALL HERMES /WIDEO SKILL"
mkdir -p "$HERMES_SKILL_DIR"
install -m 0644 "$SKILL_SRC" "${HERMES_SKILL_DIR}/SKILL.md"
mkdir -p "$OUTPUT_DIR"
chmod 0755 "$(dirname "$OUTPUT_DIR")" "$OUTPUT_DIR" || true
say "PASS: installed ${HERMES_SKILL_DIR}/SKILL.md"

section "GENERATOR PREFLIGHT"
PREFLIGHT_OUT="$(mktemp)"
set +e
"$CLI_DST" --preflight >"$PREFLIGHT_OUT" 2>&1
PREFLIGHT_RC=$?
set -e
cat "$PREFLIGHT_OUT"
rm -f "$PREFLIGHT_OUT"
if (( PREFLIGHT_RC != 0 )); then
  fail "local video preflight failed after installation"
fi

section "RESTART HERMES"
systemctl --user restart hermes-gateway.service
systemctl --user is-active --quiet hermes-gateway.service || fail "Hermes gateway did not restart cleanly"
say "PASS: Hermes gateway active"

section "FINAL CHECKS"
[[ -x "$CLI_DST" ]] || fail "$CLI_DST is not executable"
[[ -x "$TELEGRAM_DST" ]] || fail "$TELEGRAM_DST is not executable"
[[ -r "${HERMES_SKILL_DIR}/SKILL.md" ]] || fail "wideo skill missing"
curl -fsS --max-time 5 "${COMFY_URL}/system_stats" >/dev/null || fail "ComfyUI stopped responding"
say "PASS: local video tool installed"
say "PASS: no cloud video API key/provider was configured"

section "DONE"
say "Stage 23 local video is installed but no render was started automatically."
say "First hardware smoke test:"
say "  /usr/local/bin/generate-video --preset smoke --prompt 'A small red robot waves at the camera, static workshop background, gentle camera push-in'"
say "Telegram skill command: /wideo"
say "Rollback: tools/rollback_hermes_local_video_stage23.sh"
