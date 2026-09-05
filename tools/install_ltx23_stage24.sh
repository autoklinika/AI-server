#!/usr/bin/env bash
set -euo pipefail

COMFY_URL="http://127.0.0.1:8188"
LIBEXEC_DIR="/usr/local/libexec/ai-server"
GENERATOR_DST="${LIBEXEC_DIR}/generate_ltx23.py"
CLI_DST="/usr/local/bin/generate-video-ltx23"
BACKUP_DIR="/srv/ai-data/hermes/stage24-ltx23-backup"

CHECKPOINT="ltx-2.3-22b-dev-fp8.safetensors"
TEXT_ENCODER="gemma_3_12B_it_fp4_mixed.safetensors"
DISTILLED_LORA="ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors"
GEMMA_LORA="gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors"
UPSCALER="ltx-2.3-spatial-upscaler-x2-1.1.safetensors"

CHECKPOINT_URL="https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/main/${CHECKPOINT}"
TEXT_ENCODER_URL="https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/${TEXT_ENCODER}"
DISTILLED_LORA_URL="https://huggingface.co/Comfy-Org/ltx-2.3/resolve/main/split_files/loras/${DISTILLED_LORA}"
GEMMA_LORA_URL="https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/loras/${GEMMA_LORA}"
UPSCALER_URL="https://huggingface.co/Lightricks/LTX-2.3/resolve/main/${UPSCALER}"

CHECKPOINT_SHA="28606c5b5a06ce56f896d4dfcb20f212739e07a68fbe48e53638188449d26450"
TEXT_ENCODER_SHA="aaca463d11e6d8d2a4bdb0d6299214c15ef78a3f73e0ef8113d5a9d0219b3f6d"
DISTILLED_LORA_SHA="31e0c0195fb841bf31af78e8b60858f489e87ddcea4a5239abc80943da65e3ac"
GEMMA_LORA_SHA="87bcabeac9bec9f374232b5122d6511c2b2112d479e50176149e944b3712eb4a"
UPSCALER_SHA="5f416311fa8172b65af67530758964708d29a317b830d689a51143b7f91913ed"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GENERATOR_SRC="${SCRIPT_DIR}/local_video/generate_ltx23.py"

say(){ printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$1"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

command -v curl >/dev/null || fail "curl required"
command -v sha256sum >/dev/null || fail "sha256sum required"
command -v python3 >/dev/null || fail "python3 required"
[[ -r "$GENERATOR_SRC" ]] || fail "missing $GENERATOR_SRC"

section "LTX-2.3 22B STAGE 24"
say "Benchmark install only. Hermes /wideo is not changed yet."
say "Target: local ComfyUI + LTX-2.3 dev FP8 + Gemma 3 12B FP4 + distilled LoRA."

section "DISCOVER ACTIVE COMFYUI"
COMFY_SCOPE=""
if systemctl is-active --quiet comfyui.service 2>/dev/null; then
  COMFY_SCOPE="system"
elif systemctl --user is-active --quiet comfyui.service 2>/dev/null; then
  COMFY_SCOPE="user"
else
  fail "comfyui.service is not active"
fi
curl -fsS --max-time 10 "${COMFY_URL}/system_stats" >/dev/null || fail "ComfyUI API unreachable"

if [[ "$COMFY_SCOPE" == "system" ]]; then
  PID="$(systemctl show comfyui.service -p MainPID --value)"
else
  PID="$(systemctl --user show comfyui.service -p MainPID --value)"
fi
[[ "$PID" =~ ^[1-9][0-9]*$ ]] || fail "invalid ComfyUI PID"

MODELS_DIR="$(python3 - "$PID" <<'PY'
import pathlib, shlex, sys
pid=sys.argv[1]
raw=pathlib.Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
args=[x.decode() for x in raw if x]
for i,a in enumerate(args):
    if a == '--models-directory' and i+1 < len(args):
        print(args[i+1]); raise SystemExit
    if a.startswith('--models-directory='):
        print(a.split('=',1)[1]); raise SystemExit
cwd=pathlib.Path(f'/proc/{pid}/cwd').resolve()
print(str(cwd/'models'))
PY
)"
[[ -n "$MODELS_DIR" ]] || fail "could not detect models directory"
say "ComfyUI models dir: $MODELS_DIR"

CHECKPOINT_DIR="$MODELS_DIR/checkpoints"
TEXT_DIR="$MODELS_DIR/text_encoders"
LORA_DIR="$MODELS_DIR/loras"
UPSCALER_DIR="$MODELS_DIR/latent_upscale_models"
mkdir -p "$CHECKPOINT_DIR" "$TEXT_DIR" "$LORA_DIR" "$UPSCALER_DIR"

section "NODE PREFLIGHT"
python3 - "$COMFY_URL" <<'PY'
import json,sys,urllib.request
required={
'CheckpointLoaderSimple','LoraLoaderModelOnly','LTXAVTextEncoderLoader','CLIPTextEncode',
'LTXVConditioning','EmptyLTXVLatentVideo','LTXVAudioVAELoader','LTXVEmptyLatentAudio',
'LTXVConcatAVLatent','CFGGuider','RandomNoise','KSamplerSelect','ManualSigmas',
'SamplerCustomAdvanced','LTXVSeparateAVLatent','VAEDecode','LTXVAudioVAEDecode',
'CreateVideo','SaveVideo'}
with urllib.request.urlopen(sys.argv[1].rstrip('/')+'/object_info',timeout=60) as r: info=json.load(r)
missing=sorted(required-set(info))
if missing:
    print('Missing nodes:', ', '.join(missing))
    raise SystemExit(2)
print('PASS: all benchmark nodes are available')
PY

section "DISK PRECHECK"
AVAIL="$(df -B1 --output=avail "$MODELS_DIR" | tail -1 | tr -d ' ')"
MIN=$((55 * 1024 * 1024 * 1024))
if [[ "$AVAIL" =~ ^[0-9]+$ ]] && (( AVAIL < MIN )); then
  fail "need at least 55 GiB free before LTX-2.3 model install"
fi
say "PASS: at least 55 GiB free"

verify(){ local p="$1" sha="$2"; [[ -s "$p" ]] && printf '%s  %s\n' "$sha" "$p" | sha256sum -c --status; }
download(){
  local url="$1" dst="$2" sha="$3"
  if verify "$dst" "$sha"; then say "PASS: existing $(basename "$dst")"; return; fi
  if [[ -e "$dst" ]]; then mv "$dst" "${dst}.bad.$(date +%Y%m%d-%H%M%S)"; fi
  local part="${dst}.part"
  say "Downloading $(basename "$dst") ..."
  curl --fail --location --retry 4 --retry-delay 5 --continue-at - --output "$part" "$url"
  [[ -s "$part" ]] || fail "empty download: $part"
  printf '%s  %s\n' "$sha" "$part" | sha256sum -c --status || { rm -f "$part"; fail "SHA-256 mismatch: $(basename "$dst")"; }
  mv "$part" "$dst"
  say "PASS: downloaded + verified $(basename "$dst")"
}

section "DOWNLOAD OFFICIAL LTX-2.3 MODEL SET"
download "$CHECKPOINT_URL" "$CHECKPOINT_DIR/$CHECKPOINT" "$CHECKPOINT_SHA"
download "$TEXT_ENCODER_URL" "$TEXT_DIR/$TEXT_ENCODER" "$TEXT_ENCODER_SHA"
download "$DISTILLED_LORA_URL" "$LORA_DIR/$DISTILLED_LORA" "$DISTILLED_LORA_SHA"
download "$GEMMA_LORA_URL" "$LORA_DIR/$GEMMA_LORA" "$GEMMA_LORA_SHA"
download "$UPSCALER_URL" "$UPSCALER_DIR/$UPSCALER" "$UPSCALER_SHA"

section "INSTALL BENCHMARK COMMAND"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
if [[ ! -e "$BACKUP_DIR/generate_ltx23.py" && ! -e "$BACKUP_DIR/generate_ltx23.py.absent" ]]; then
  if sudo test -e "$GENERATOR_DST"; then sudo cp -a "$GENERATOR_DST" "$BACKUP_DIR/generate_ltx23.py"; else : > "$BACKUP_DIR/generate_ltx23.py.absent"; fi
fi
if [[ ! -e "$BACKUP_DIR/generate-video-ltx23" && ! -e "$BACKUP_DIR/generate-video-ltx23.absent" ]]; then
  if sudo test -e "$CLI_DST"; then sudo cp -a "$CLI_DST" "$BACKUP_DIR/generate-video-ltx23"; else : > "$BACKUP_DIR/generate-video-ltx23.absent"; fi
fi
sudo install -d -m 0755 "$LIBEXEC_DIR"
sudo install -m 0755 "$GENERATOR_SRC" "$GENERATOR_DST"
TMP="$(mktemp)"
cat > "$TMP" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/python3 /usr/local/libexec/ai-server/generate_ltx23.py "$@"
EOF
sudo install -m 0755 "$TMP" "$CLI_DST"
rm -f "$TMP"

section "RESTART COMFYUI"
if [[ "$COMFY_SCOPE" == "system" ]]; then sudo systemctl restart comfyui.service; else systemctl --user restart comfyui.service; fi
for _ in $(seq 1 90); do curl -fsS --max-time 3 "$COMFY_URL/system_stats" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS --max-time 5 "$COMFY_URL/system_stats" >/dev/null || fail "ComfyUI failed to return"

section "LTX-2.3 PREFLIGHT"
"$CLI_DST" --preflight || fail "LTX-2.3 model/node preflight failed"

section "DONE"
say "PASS: LTX-2.3 benchmark backend installed"
say "Hermes /wideo was NOT changed."
say "First benchmark command:"
say "  time /usr/local/bin/generate-video-ltx23 --prompt 'A small glossy red desktop robot stands on an electronics workbench and clearly waves its right hand toward the camera. The camera slowly dollies forward. Realistic workshop lighting. [SOUNDS]: quiet electronics workshop ambience.'"
