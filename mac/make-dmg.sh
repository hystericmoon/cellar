#!/bin/bash
# Builds a universal Cellar.app (Apple silicon + Intel) and wraps it in a branded DMG.
#   ./make-dmg.sh 0.2.0      -> ../dist/Cellar-0.2.0.dmg
# Needs Apple's Command Line Tools and dmgbuild (pip3 install dmgbuild). DMGBUILD=/path overrides.
# The app is ad-hoc signed, not notarized: on first open people use
# System Settings › Privacy & Security › Open Anyway. With a Developer ID this is where
# signing and notarization would go.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
VERSION="${1:?usage: ./make-dmg.sh <version>, for example 0.2.0}"
DIST="$ROOT/dist"
DMG="$DIST/Cellar-$VERSION.dmg"

DMGBUILD="${DMGBUILD:-$(command -v dmgbuild || true)}"
[ -n "$DMGBUILD" ] || { echo "dmgbuild is missing: pip3 install dmgbuild"; exit 1; }

UNIVERSAL=1 NO_INSTALL=1 CELLAR_VERSION="$VERSION" ./build-app.sh
lipo -archs "$ROOT/Cellar.app/Contents/MacOS/Cellar"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ditto "$ROOT/Cellar.app" "$STAGE/Cellar.app"

mkdir -p "$DIST"
rm -f "$DMG"
"$DMGBUILD" -s dmg-settings.py \
  -D app="$STAGE/Cellar.app" \
  -D bg="$ROOT/brand/assets/dmg-background.tiff" \
  -D icon="$ROOT/Cellar.app/Contents/Resources/AppIcon.icns" \
  "Cellar $VERSION" "$DMG"

codesign --force --sign - "$DMG"
hdiutil verify "$DMG" >/dev/null
shasum -a 256 "$DMG" | tee "$DMG.sha256"
echo "Built: $DMG ($(du -h "$DMG" | cut -f1))"
