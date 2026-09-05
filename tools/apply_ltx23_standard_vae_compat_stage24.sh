#!/usr/bin/env bash
set -euo pipefail

SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/local_video/generate_ltx23.py"
DST="/usr/local/libexec/ai-server/generate_ltx23.py"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

[[ -r "$SRC" ]] || { echo "FAIL: missing $SRC" >&2; exit 1; }

python3 - "$SRC" "$TMP" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding="utf-8")

old_nodes = 'UPSCALE_NODES = {"LatentUpscaleModelLoader", "LTXVLatentUpsampler", "LTXVTiledVAEDecode"}'
new_nodes = 'UPSCALE_NODES = {"LatentUpscaleModelLoader", "LTXVLatentUpsampler"}'

old_decode = '"26": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["1", 2], "latents": ["25", 0], "horizontal_tiles": 2, "vertical_tiles": 2, "overlap": 6, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},'
new_decode = '"26": {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": ["1", 2]}},'

for label, old in (("upscale node set", old_nodes), ("upscale decode node", old_decode)):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"FAIL: expected exactly one {label} match, got {count}")

text = text.replace(old_nodes, new_nodes).replace(old_decode, new_decode)
compile(text, str(src), "exec")
dst.write_text(text, encoding="utf-8")
print("PASS: generated LTX-2.3 standard-VAEDecode compatibility backend")
PY

sudo install -m 0755 "$TMP" "$DST"

echo
echo "===== UPSCALE PREFLIGHT ====="
/usr/local/bin/generate-video-ltx23 --upscale-2x --preflight
