#!/usr/bin/env bash
set -euo pipefail

DEST="${1:-/srv/ai-data/tools/tesseract-portable}"
PKGS="$DEST/pkgs"
ROOT="$DEST/root"

mkdir -p "$PKGS" "$ROOT"
cd "$PKGS"

packages=(
  "tesseract-ocr=5.5.0-1build1"
  "libtesseract5=5.5.0-1build1"
  "libleptonica6=1.86.0-1"
  "tesseract-ocr-eng=1:4.1.0-2build1"
  "tesseract-ocr-osd=1:4.1.0-2build1"
  "tesseract-ocr-pol=1:4.1.0-2build1"
)

rm -f ./*.deb
apt-get download "${packages[@]}"

rm -rf "$ROOT"
mkdir -p "$ROOT"
for package in ./*.deb; do
  dpkg-deb -x "$package" "$ROOT"
done

TESS="$ROOT/usr/bin/tesseract"
LIB="$ROOT/usr/lib/x86_64-linux-gnu"
DATA="$ROOT/usr/share/tesseract-ocr/5/tessdata"

LD_LIBRARY_PATH="$LIB:${LD_LIBRARY_PATH:-}" \
TESSDATA_PREFIX="$DATA" \
"$TESS" --version | head -1

LD_LIBRARY_PATH="$LIB:${LD_LIBRARY_PATH:-}" \
TESSDATA_PREFIX="$DATA" \
"$TESS" --list-langs 2>/dev/null

printf 'portable_tesseract=%s\n' "$TESS"
printf 'tessdata=%s\n' "$DATA"
