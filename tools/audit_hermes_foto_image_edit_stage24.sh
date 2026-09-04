#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
COMFY_ROOT="/opt/comfyui"
COMFY_APP="${COMFY_ROOT}/ComfyUI"
COMFY_MODELS="${COMFY_ROOT}/data/models"
COMFY_INPUT="${COMFY_ROOT}/data/input"
COMFY_OUTPUT="/srv/ai-data/comfyui-output"
COMFY_URL="http://127.0.0.1:8188"
GENERATOR="/usr/local/bin/generate-image"
TELEGRAM_GENERATOR="/usr/local/bin/generate-image-telegram"
REPORT="/tmp/stage24-foto-image-edit-audit.txt"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }
fail() { say "FAIL: $*"; exit 1; }

section "STAGE-24 /FOTO IMAGE-EDIT READINESS AUDIT"
say "Read-only. No config, model, service, skill, workflow or Telegram state is modified."
say "report: $REPORT"

[ -d "$HERMES_SOURCE" ] || fail "Hermes source missing: $HERMES_SOURCE"
[ -x "$HERMES_PYTHON" ] || fail "Hermes Python missing: $HERMES_PYTHON"
[ -d "$COMFY_APP" ] || fail "ComfyUI app missing: $COMFY_APP"
[ -x "$GENERATOR" ] || fail "generate-image missing: $GENERATOR"
[ -x "$TELEGRAM_GENERATOR" ] || fail "generate-image-telegram missing: $TELEGRAM_GENERATOR"

exec > >(tee "$REPORT") 2>&1

section "SERVICES"
printf 'Hermes:  '; systemctl --user is-active hermes-gateway.service || true
printf 'Gateway: '; systemctl is-active ai-gateway.service || true
printf 'Ollama:  '; systemctl is-active ollama.service || true
printf 'ComfyUI: '; systemctl is-active comfyui.service || true

section "CURRENT /FOTO SKILL"
SKILL_FILE="${HERMES_HOME}/skills/foto/SKILL.md"
if [ -r "$SKILL_FILE" ]; then
    sed -n '1,220p' "$SKILL_FILE"
else
    say "WARN: $SKILL_FILE missing"
fi

section "LOCAL IMAGE GENERATOR INTERFACES"
say "--- generate-image --help ---"
"$GENERATOR" --help 2>&1 || true
say "--- generate-image-telegram --help ---"
"$TELEGRAM_GENERATOR" --help 2>&1 || true

section "LOCAL IMAGE WRAPPER SOURCES"
for f in "$GENERATOR" "$TELEGRAM_GENERATOR"; do
    say "--- $f ---"
    if [ -r "$f" ]; then
        sed -n '1,320p' "$f"
    else
        say "WARN: not readable"
    fi
done

section "INSTALLED FLUX.2 MODEL FILES"
for f in \
    "${COMFY_MODELS}/diffusion_models/flux-2-klein-4b-fp8.safetensors" \
    "${COMFY_MODELS}/text_encoders/qwen_3_4b.safetensors" \
    "${COMFY_MODELS}/vae/flux2-vae.safetensors"; do
    if [ -f "$f" ]; then
        stat -c 'PASS: %n size=%s' "$f"
    else
        say "MISSING: $f"
    fi
done

section "COMFYUI API + EDIT-RELEVANT NODES"
"$HERMES_PYTHON" - "$COMFY_URL" <<'PY'
import json, sys, urllib.request
base = sys.argv[1].rstrip('/')
with urllib.request.urlopen(base + '/system_stats', timeout=5) as r:
    stats = json.load(r)
print('PASS: /system_stats reachable')
print('system_stats keys:', sorted(stats.keys()))
with urllib.request.urlopen(base + '/object_info', timeout=15) as r:
    obj = json.load(r)
needles = [
    'LoadImage', 'SaveImage', 'UNETLoader', 'CLIPLoader', 'VAELoader',
    'RandomNoise', 'KSamplerSelect', 'SamplerCustomAdvanced', 'VAEDecode',
    'Flux2Scheduler', 'ReferenceLatent', 'FluxGuidance', 'BasicGuider',
]
for name in needles:
    print(f'{name}:', 'YES' if name in obj else 'NO')
print('object_info node count:', len(obj))
PY

section "INSTALLED COMFYUI EDIT WORKFLOW CANDIDATES"
find "$COMFY_ROOT" -type f \( -iname '*flux*2*klein*edit*.json' -o -iname '*image*edit*flux*.json' \) -print 2>/dev/null | sort | head -n 80 || true

section "COMFYUI INPUT/OUTPUT LAYOUT"
ls -ld "$COMFY_INPUT" "$COMFY_OUTPUT" 2>/dev/null || true
say "Recent input files:"
find "$COMFY_INPUT" -maxdepth 2 -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' 2>/dev/null | sort -r | head -n 20 || true
say "Recent output files:"
find "$COMFY_OUTPUT" -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' 2>/dev/null | sort -r | head -n 10 || true

section "EXACT INSTALLED HERMES TELEGRAM MEDIA PATHS"
"$HERMES_PYTHON" - "$HERMES_SOURCE" <<'PY'
from pathlib import Path
import re, sys
root = Path(sys.argv[1])
patterns = [
    re.compile(r'photo', re.I),
    re.compile(r'attachment', re.I),
    re.compile(r'reply_to_message', re.I),
    re.compile(r'file_path', re.I),
    re.compile(r'cache.*media|media.*cache', re.I),
]
preferred = []
for rel in [
    'plugins/platforms/telegram/adapter.py',
    'gateway/platforms/telegram.py',
    'gateway/run.py',
    'gateway/run_inbound.py',
    'gateway/platforms/base.py',
    'agent/image_routing.py',
]:
    p = root / rel
    if p.is_file():
        preferred.append(p)
# Exact installed release may use different layout; include telegram-named Python files.
for p in root.rglob('*.py'):
    low = str(p).lower()
    if 'telegram' in low and p not in preferred:
        preferred.append(p)

seen = set()
for p in preferred:
    if p in seen:
        continue
    seen.add(p)
    try:
        lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
    except Exception:
        continue
    hits = []
    for i, line in enumerate(lines):
        if any(rx.search(line) for rx in patterns):
            hits.append(i)
    if not hits:
        continue
    print(f'\n--- FILE: {p.relative_to(root)} ---')
    emitted = set()
    for i in hits[:80]:
        start = max(0, i - 5)
        end = min(len(lines), i + 7)
        key = (start, end)
        if any(start <= old_i < end for old_i in emitted):
            continue
        emitted.add(i)
        print(f'\n[lines {start+1}-{end}]')
        for n in range(start, end):
            print(f'{n+1:04d}: {lines[n]}')
PY

section "HERMES CACHE IMAGE CANDIDATES"
find "$HERMES_HOME" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) \
    -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' 2>/dev/null | sort -r | head -n 40 || true

section "SUMMARY"
"$HERMES_PYTHON" - "$COMFY_MODELS" "$GENERATOR" "$TELEGRAM_GENERATOR" <<'PY'
from pathlib import Path
import sys
models = Path(sys.argv[1])
required = [
    models/'diffusion_models'/'flux-2-klein-4b-fp8.safetensors',
    models/'text_encoders'/'qwen_3_4b.safetensors',
    models/'vae'/'flux2-vae.safetensors',
]
print('required Flux.2 distilled edit model files:', 'PASS' if all(p.is_file() for p in required) else 'FAIL')
print('generate-image exists:', Path(sys.argv[2]).is_file())
print('generate-image-telegram exists:', Path(sys.argv[3]).is_file())
print('NEXT_IMPLEMENTATION_TARGET: Telegram inbound image path -> local ComfyUI Flux.2 Klein 4B distilled edit workflow -> existing Telegram media delivery')
PY

say
say "PASS: Stage-24 read-only audit completed"
say "Full report: $REPORT"
