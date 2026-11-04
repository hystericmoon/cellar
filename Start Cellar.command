#!/bin/bash
# Double-click to start Cellar. Close this window (or press Ctrl+C) to quit.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed. macOS will now offer to install the Command Line Tools."
  xcode-select --install; exit 1
fi
if ! command -v adb >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/adb ] && [ ! -x /usr/local/bin/adb ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing Android platform tools (one time)…"; brew install --cask android-platform-tools
  else
    echo "Tip: install adb with  brew install --cask android-platform-tools  (see brew.sh)"
  fi
fi
exec python3 cellar.py
