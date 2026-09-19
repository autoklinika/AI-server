#!/usr/bin/env bash
set -euo pipefail

DEST="${1:?usage: $0 DEST}"
ROOT="$(git rev-parse --show-toplevel)"

rm -rf "$DEST"
mkdir -p "$DEST"

git -C "$ROOT" archive f993794a653981d7736484490e96f703c380aeb7 | tar -x -C "$DEST"

write_file() {
    local sha="$1"
    local path="$2"
    mkdir -p "$DEST/$(dirname "$path")"
    git -C "$ROOT" show "$sha:$path" > "$DEST/$path"
}

write_file 2d308a22a2a8a84ef178de0e269521ae36e30c61 src/ai_bridge/adapters/ventilation/analysis_v12_2.py
write_file f3f62ba7d748ea6fa19de01c5267ed19d2318d27 src/ai_bridge/adapters/ventilation/schemas.py
write_file 18436f68ccd3add8b0d5ccf3d1c3435689694186 src/ai_bridge/analysis/operator_view.py
write_file 14256dd6799eef69ad8fb9f54100bb69ed1977c9 src/ai_bridge/analysis/schemas.py
write_file d56ef725cbaa1baf1503add4c036c6d0b98d1536 src/ai_bridge/analysis/service_v12_2.py

echo "AI Bridge baseline reconstructed in: $DEST"
