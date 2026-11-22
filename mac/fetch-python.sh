#!/bin/bash
# Puts a standalone Python (python-build-standalone, by Astral) into a folder, so Cellar.app runs on a Mac
# that has no Python or Command Line Tools.   ./fetch-python.sh <arm64|x86_64> <output folder>
# Downloads once into ~/Library/Caches/Cellar/python and checks the file against the release's SHA256SUMS.
set -euo pipefail
ARCH="${1:?arm64 or x86_64}"
OUT="${2:?output folder}"
TAG="20261110"
PYVER="3.13.18"
case "$ARCH" in
  arm64) TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *) echo "Unknown architecture: $ARCH"; exit 1 ;;
esac
FILE="cpython-$PYVER+$TAG-$TRIPLE-install_only_stripped.tar.gz"
BASE="https://github.com/astral-sh/python-build-standalone/releases/download/$TAG"
CACHE="$HOME/Library/Caches/Cellar/python/$TAG"
mkdir -p "$CACHE"
if [ ! -f "$CACHE/$FILE" ]; then
  echo "Downloading $FILE…"
  curl -fL --progress-bar -o "$CACHE/$FILE.part" "$BASE/$FILE"
  mv "$CACHE/$FILE.part" "$CACHE/$FILE"
fi
[ -f "$CACHE/SHA256SUMS" ] || curl -fsSL -o "$CACHE/SHA256SUMS" "$BASE/SHA256SUMS"
WANT="$(grep " $FILE\$" "$CACHE/SHA256SUMS" | cut -d' ' -f1)"
GOT="$(shasum -a 256 "$CACHE/$FILE" | cut -d' ' -f1)"
if [ -z "$WANT" ] || [ "$WANT" != "$GOT" ]; then
  rm -f "$CACHE/$FILE"
  echo "The Python download did not match its checksum. Try again."; exit 1
fi
rm -rf "$OUT"
mkdir -p "$OUT"
tar -xzf "$CACHE/$FILE" -C "$OUT" --strip-components=1
# Cellar uses only the standard library: drop what it never needs.
PYLIB="$OUT/lib/python${PYVER%.*}"
rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/tkinter" "$PYLIB/turtledemo" "$PYLIB/ensurepip" "$PYLIB/site-packages" \
       "$OUT/lib/tcl"* "$OUT/lib/tk"* "$OUT/lib/itcl"* "$OUT/lib/libtcl"* "$OUT/lib/libtk"* "$OUT/share" "$OUT/include" 2>/dev/null || true
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "Python $PYVER ($ARCH) ready in $OUT ($(du -sh "$OUT" | cut -f1))"
