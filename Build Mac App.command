#!/bin/bash
# Double-click to build Cellar.app (menu bar app + window). Needs Apple's free Command Line Tools.
cd "$(dirname "$0")/mac" && exec ./build-app.sh
