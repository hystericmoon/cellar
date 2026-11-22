# Cellar: next session

Updated 2026-11-22. Work happens on `main`. Release **v0.2.3** is published (the v0.2.1 tag failed to build; leave it). Everything is pushed. The untracked `linkedin/` folder (a LinkedIn image) stays out of commits.

## State
- **Release:** https://github.com/hystericmoon/cellar/releases/tag/v0.2.3. `Cellar.dmg` (universal, bundled Python, ad-hoc signed, not notarized, 36 MB) plus `Cellar.dmg.sha256`, built by `.github/workflows/release.yml`. First open needs System Settings › Privacy & Security › Open Anyway.
- **Site:** https://hystericmoon.github.io/cellar/ (GitHub Pages from `main` `/docs`). The download button links `releases/latest/download/Cellar.dmg`, so new tags update it. The site shows no version number.
- **CI:** tests green on main (API 148, Browser 84 at `7f2118d`). The zip, unzip, two-pane and menu tests were added later and have not run in CI yet: watch the next run.
- **Installed app:** `/Applications/Cellar.app` is v0.2.3 from the release. Dev rebuild: `BUNDLE_PYTHON=1 NO_INSTALL=1 mac/build-app.sh`, quit Cellar, move it to /Applications.
- **To release:** `git tag -a vX.Y.Z -m ... && git push origin vX.Y.Z`, then check the `release` workflow and the attached DMG. Local build: `mac/make-dmg.sh <version>` (needs `pip3 install dmgbuild`). Use v0.2.4 for small fixes, v0.3.0 for the next big feature.
- **Never run** `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac (they write to `/storage` and delete `~/Downloads/Cellar`). CI runs them.
- **Test a UI change locally** without those scripts: run a second server with the watcher off, then open it in the browser pane. Do not change settings there (it shares `~/.cellar.json`).
  `CELLAR_PORT=8790 CELLAR_NO_BROWSER=1 python3 -I -c "import sys; sys.path.insert(0,'.'); import cellar; cellar.device_watcher=lambda:None; cellar.main()"`
- Two phones may be on USB (Samsung A55, Redmi M2101K6G). The test server picks the first adb device: switch device in the UI.

## Next work (the user said: another time)
Suggested v0.3.0: messages and notifications on the Mac, then restore.
1. Restore for contacts and messages (export exists, import does not).
2. Messages and notifications on the Mac.
3. Away-from-Wi-Fi transfer.
4. Windows support.
5. A Mac folder pane in the two-pane view (the second pane is phone-only).
6. Mirror inside the app: A) dock the scrcpy window next to Cellar's (small); B) real in-app video (several days).

Dropped: music playlists (user), SD card / USB drive hardware test (user; release notes say untested), no-USB-debugging mode (see below).

## Still open
1. **GitHub support ticket** to purge old commits `ae162fa`, `5a6acde`, `f6b8181` (not purged on 2026-11-06). Done when `github.com/hystericmoon/cellar/commit/ae162fa` shows "not found".
2. **Not verified:** the Open Anyway flow with the CI-built DMG; the menu bar drop in the release build (checked only with a local build); install on a clean Mac (Python is bundled, so no Command Line Tools prompt is expected).
3. **Flaky test:** the `space` step ("biggest file is first", "file saved to the Mac first", "then moved to the phone Trash") failed in two CI runs and passed on re-run. Cause unknown: the first row was not `report.pdf`. `tests/e2e.js` now prints the first five names on failure. Next failure: read the CI log for "saw:" and fix the cause.
4. **Developer ID + notarization** ($99/yr, user's call) would remove Open Anyway. `make-dmg.sh` notes where signing goes.
5. Impeccable skill update available (v4.8.0). Only on request.

## How the Mac app works (facts that cost time to find)
- **Window:** loads `/?app=1`. Transparent title bar over `NSGlassEffectView` (macOS 26+) or `NSVisualEffectView`; a 248×40 `DragStrip` sits over the sidebar. The page makes the sidebar see-through with `html.in-app.glass`. Do not name a root class `app`: it clashes with the `.app` grid.
- **Server life:** the server exits when the app is force-quit (`CELLAR_PARENT_PID`). On start it restarts adb so adb runs under the current build's Local Network permission. Every ad-hoc rebuild is a new app to macOS privacy checks.
- **Local Network:** `NSLocalNetworkUsageDescription` and `NSBonjourServices` are in `build-app.sh`; the app browses `_adb-tls-connect._tcp` at launch so macOS asks. Without it, Go wireless fails with "No route to host".
- **Show in Finder:** Cellar runs `/sbin/mount_webdav -s -S -v <name>` into `~/Library/Application Support/Cellar/Finder/<name>` (0.7 s, no dialog; `/Volumes` needs admin rights). `osascript mount volume` and NetFS both blocked. A lock stops double mounts; dead mounts are cleaned at startup and before mounting. The app unmounts on quit, before it stops the server. Never unmount from inside the server while it shuts down: it deadlocks. WebDAV replies read the request body once before answering.
- **Camera upright:** scrcpy cannot rotate a running camera. `cellar.py` (`tilt_from_gravity`, `read_tilt`, `_watch_tilt`) reads the accelerometer from `dumpsys sensorservice` and restarts scrcpy with a new `--orientation` (back: `90 - tilt`; front: `270 + tilt`). When the screen is off the sensor sleeps: Cellar sends `KEYCODE_WAKEUP`. The window is raised with System Events.
- **Take a photo:** `take_photo`, `POST /api/photo`. Opens Camera, presses `KEYCODE_CAMERA`, pulls the file to `~/Downloads/Cellar/Photos`. Needs an unlocked phone.
- **Video thumbnails:** `video_thumb` copies videos under 400 MB once and draws a frame with `qlmanage -t`.
- **Menu bar drop:** `MenuDropView` in `Cellar.swift`, `POST /api/dropfiles`. APFS clone into staging, then one push job to the phone's Download folder.
- **Shared clipboard:** `clipboard_sync` runs scrcpy `--no-video --no-audio --no-window`. Stops when Cellar quits.
- **Compress / Extract here:** `run_archive` (job kind `archive`), `archiveOp` in `ui.html`. Zips and unzips on the Mac with `zipfile`. Refuses password zips and paths that climb out.
- **Two panes:** `P2` code in `ui.html`, `#splitBtn`, ⌘\. State in localStorage `dv-split`.
- **Bundled Python:** `mac/fetch-python.sh` downloads python-build-standalone (release 20261110, checksum checked, cached in `~/Library/Caches/Cellar/python`). `build-app.sh` copies it to `Resources/python-<arch>` when `UNIVERSAL=1` or `BUNDLE_PYTHON=1`. `Cellar.swift` prefers it.

## UI facts
- Six themes (Graphite default, Violet, Midnight, Forest, Ember, Daylight) in Settings (`#:settings`, a page). Match macOS switches to Daylight in light mode. localStorage keys: `dv-theme`, `dv-matchos`, `dv-glass`, `dv-kind`.
- Home (`#:home`) is the first screen. Sidebar: device row, Home, Favorites, Tools and Phone groups, Trash and Settings at the bottom. Recent lives on Home; Duplicates is a tab of Free up space.
- Only the file list scrolls: `.app` has `grid-template-rows:minmax(0,1fr)`, `aside,main{min-height:0}`, `html,body{overflow:hidden}`, `.sr{top:0;left:0}`.
- `refreshInfo()` polls `/api/info` every 30 s (skipped while hidden) and on `visibilitychange`.
- Type filter: `#kindBtn` next to Search; `S.kind` filters `visible()`; it clears when you open another folder or view.
- Tests: loading `/#:x` from another `#:` page does not reload, so old toasts stay. Call `goto('/')` first.
- New folder + Escape keeps `untitled folder` (matches Finder). Left as is.

## Brand, site, DMG
- Brand in `brand/` (guide: `brand/BRAND.md`). `make_brand.py` generates every asset plus `mac/AppIcon.iconset` and `mac/Menubar*Template.png`. Menu bar door: filled = connected, outline = no phone.
- Site: `docs/index.html`, with a door colour picker and install steps. Photos: `docs/img/photos` (credits in `CREDITS.txt`).
- DMG: `make-dmg.sh` uses dmgbuild (create-dmg's Finder scripting did not save the layout on macOS 26). Unsigned.
- MIT `LICENSE` (holder "hystericmoon").

## No-USB-debugging mode: tried and dropped (2026-11-22)
Tested on the A55 with `libmtp` and `aft-mtp-cli`. Mac's `ptpcamerad` grabs the phone first (libusb claim fails with -3). Killing it works once, then launchd restarts it. The phone never opened an MTP session; listing hung for minutes. Not tried: also stopping `icdd`. Not worth it. If someone retries: route by device id `mtp:<serial>`, basic mode only, one long-lived MTP session behind a lock, bundle the binary with the LGPL text, add a fake MTP tool to `tests/fakebin`. Only a phone companion app or a file-server app would work well.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). v0.2.3 is released as a DMG and the site is at hystericmoon.github.io/cellar. Read `NEXT_SESSION.md` only; read `HANDOFF.md` or `README.md` only if the task needs them. Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them. Ask me what to work on next.
