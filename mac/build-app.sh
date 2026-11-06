#!/bin/bash
# Builds Cellar.app on your Mac. Free: needs only Apple's Command Line Tools (xcode-select --install).
# No Apple developer account: the app is signed "ad hoc" for this Mac, and because you build it here
# it isn't quarantined, so Gatekeeper opens it without warnings.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
APP="$ROOT/Cellar.app"

if ! command -v swiftc >/dev/null 2>&1; then
  echo "Apple's Command Line Tools are needed (free, one time). Starting the installer…"
  xcode-select --install || true
  echo "Run this script again when the installer finishes."
  exit 1
fi

# UNIVERSAL=1 builds for both Apple silicon and Intel (used for the downloadable DMG).
# CELLAR_VERSION sets the version shown in Finder (default: today's date).
# NO_INSTALL=1 skips the "move to Applications" question.
if [ "${UNIVERSAL:-0}" = 1 ]; then ARCHS="arm64 x86_64"; else ARCHS="$(uname -m)"; fi
echo "Building Cellar.app for $ARCHS…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

BINS=()
for ARCH in $ARCHS; do
  swiftc -O -target "$ARCH-apple-macos12.0" \
    -framework Cocoa -framework WebKit -framework ServiceManagement \
    -o "$APP/Contents/MacOS/Cellar-$ARCH" Cellar.swift
  BINS+=("$APP/Contents/MacOS/Cellar-$ARCH")
done
lipo -create "${BINS[@]}" -output "$APP/Contents/MacOS/Cellar"
rm -f "${BINS[@]}"

cp "$ROOT/cellar.py" "$ROOT/ui.html" "$APP/Contents/Resources/"
cp -R "$ROOT/fonts" "$APP/Contents/Resources/fonts"
cp MenubarTemplate.png MenubarTemplate@2x.png MenubarOffTemplate.png MenubarOffTemplate@2x.png "$APP/Contents/Resources/"
# If this folder came from a downloaded zip, the copied files carry macOS's download flag, and an
# app holding flagged files can stall at launch. This app was just built here, so drop the flag.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
if command -v iconutil >/dev/null 2>&1; then
  iconutil -c icns AppIcon.iconset -o "$APP/Contents/Resources/AppIcon.icns"
fi

VERSION="${CELLAR_VERSION:-$(date +%Y.%m.%d)}"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Cellar</string>
  <key>CFBundleDisplayName</key><string>Cellar</string>
  <key>CFBundleIdentifier</key><string>local.cellar.app</string>
  <key>CFBundleExecutable</key><string>Cellar</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>Cellar asks Finder to show your phone under Locations.</string>
  <key>NSLocalNetworkUsageDescription</key><string>Cellar connects to your Android phone over Wi-Fi, so you can use it without a cable.</string>
  <key>NSBonjourServices</key><array><string>_adb-tls-connect._tcp</string><string>_adb-tls-pairing._tcp</string><string>_adb._tcp</string></array>
</dict></plist>
PLIST

codesign --force --deep --sign - "$APP"
echo
echo "Built: $APP"
[ "${NO_INSTALL:-0}" = 1 ] && exit 0
read -r -p "Move it to your Applications folder? [Y/n] " answer
if [[ "${answer:-Y}" =~ ^[Yy]$ ]]; then
  rm -rf "/Applications/Cellar.app"
  mv "$APP" /Applications/
  APP="/Applications/Cellar.app"
  echo "Moved to /Applications."
fi
open "$APP"
echo "Cellar is running. Look for the phone icon in the menu bar."
