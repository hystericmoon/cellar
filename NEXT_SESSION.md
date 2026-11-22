# Cellar: next session

Updated 2026-11-22 (second session). Work happens on `main`; release v0.2.2 is published (v0.2.1 failed to build; leave that tag alone). Working tree clean except the untracked `linkedin/` folder (a LinkedIn image; keep it out of commits).

## State
- **Released:** Cellar **0.2.0** at https://github.com/hystericmoon/cellar/releases/tag/v0.2.0: `Cellar.dmg` (universal, ad-hoc signed, not notarized) + `Cellar.dmg.sha256`, built by `.github/workflows/release.yml`. First open needs System Settings › Privacy & Security › Open Anyway (in README, site, release notes, and printed in the DMG window). v0.1.0 (arm64 zip) is older.
- **Site live:** https://hystericmoon.github.io/cellar/ (GitHub Pages from `main` `/docs`; also the repo homepage). Download button links `releases/latest/download/Cellar.dmg`, so future tags update it automatically.
- **CI:** tests green on main (API 136, Browser 81 for `22c6668`). The release workflow is green for v0.2.0.
- **Installed app:** `/Applications/Cellar.app` is a local dev build (version `0.2.2-dev`, with the debug logging above, bundled Python, arm64 only). Older copies are in the Mac Trash. The real v0.2.2 from the release was installed and tested earlier today: camera upright, video thumbnails, clipboard and server drop all worked. Rebuild: `BUNDLE_PYTHON=1 NO_INSTALL=1 mac/build-app.sh`, quit Cellar, move it to /Applications.
- **To release:** `git tag -a v0.2.1 -m ... && git push origin v0.2.1`. Locally: `mac/make-dmg.sh <version>` (needs `pip3 install dmgbuild`).
- Never run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac (they write to `/storage` and delete `~/Downloads/Cellar`). CI runs them.

## Done (all items from the 2026-11-05 list)
- CI confirmed green.
- Second UI audit and its fixes (`e9f9a95`, `854d52f`).
- Duplicate contacts: one Android contact made of several raw contacts (two Google accounts plus WhatsApp). The export now merges by `contact_id` and drops repeated numbers and emails (`af753ac`). The test fixture uses a made-up number.
- Camera backup: 843 items, 21.79 GB, 0 errors, into `~/Pictures/Cellar/Samsung SM-A556E/Camera`.
- Leftover "Cellar test" alarms removed from the Clock app.
- Stale `cellar.py` servers from earlier runs stopped.

## Decided / skipped
- SD card / USB drive: skipped by the user. The release notes say it's untested on hardware.
- New folder + Escape keeps `untitled folder` (matches Finder). Left as is.
- Numbers isn't installed; GridCraft was used for CSV checks.

## Redesign (2026-11-06, on main as b44fd32 and 4de7856; CI green: API 135, Browser 74)
Built from the mockup at https://claude.ai/artifact/XTKLCvXyfrA1j6qbxezCnr, in `ui.html`, `mac/Cellar.swift` and `tests/e2e.js`:
- Six themes (Graphite default, Violet, Midnight, Forest, Ember, Daylight) in Settings, now a page (`#:settings`) instead of a dialog. Match macOS (off by default) switches to Daylight in light mode. Stored in localStorage `dv-theme`, `dv-matchos`, `dv-glass`, `dv-kind`.
- Liquid Glass: the Mac app loads `/?app=1`; its window has a transparent title bar over `NSGlassEffectView` (macOS 26+) or `NSVisualEffectView`, with a 248×40 `DragStrip` over the top of the sidebar for dragging. The page makes the sidebar see-through (`html.in-app.glass`). In any browser, menus, dialogs, toasts and transfers use backdrop blur. Don't name a root class `app`: it clashes with the `.app` grid.
- Home (`#:home`) is the first screen: backup finding, storage, quick actions, latest Camera photos, Recent.
- Sidebar: compact device row (click for details), Home, Favorites (Internal storage, Camera, Pictures, Downloads, Documents; right-click a folder › Add to sidebar), folding Tools and Phone groups, Trash and Settings at the bottom. Recent lives on Home; Duplicates is a tab of Free up space.
- Colour by kind on folders, file icons and sidebar icons; spotlight hover on tiles; hidden folders sort last; labelled toolbar buttons; Phone controls in two columns.
- Checked with the phone: Home, folder and file colours, Camera timeline, Phone controls, glass menus, the Mac window. The server now exits when the app is force-quit (CELLAR_PARENT_PID).
- Tests: loading "/#:x" from another "#:" page doesn't reload, so old toasts stay; reload with goto('/') first.

## Wireless and Show in Finder fixes (2026-11-06)
- Go wireless failed with "No route to host": Cellar lacked macOS Local Network permission, and adb inherits it from the app that starts it. Fixed: `NSLocalNetworkUsageDescription` + `NSBonjourServices` in build-app.sh, and the app browses for `_adb-tls-connect._tcp` at launch so macOS asks. Verified: Go wireless connects through Cellar.
- Show in Finder hung: dead WebDAV mounts (one from a test server on 8775) plus duplicate mounts. Fixed in cellar.py: a lock so auto-mount and the button can't mount twice; mounts whose server is gone are cleaned up at startup and before mounting (kill the mount_webdav helper, then `diskutil unmount force`). The Mac app unmounts its own mount on quit, before stopping the server. Unmounting from inside the server while it shuts down deadlocks: don't. Verified: quit takes about 4 s, leaves no mount, relaunch gets port 8765 back.
- `osascript mount volume` showed a "Connect as" dialog and blocked until it was answered. NetFS with NoUI/Guest/AllowLoopback avoided the dialog but still waited about 90 s inside NetAuthSysAgent. Now Cellar calls `/sbin/mount_webdav -s -S -v <name>` into `~/Library/Application Support/Cellar/Finder/<name>` (/Volumes needs admin rights): 0.7 s, no dialog, and Finder treats it as a volume. The helper process is `webdavfs_agent` on this macOS.
- WebDAV replies now read the request body once before answering (an unread body reset kept-alive connections).
- When started by the Mac app, the server restarts adb so it runs under the current build's Local Network permission. An adb left over from an earlier build can't reach the Wi-Fi. Every ad-hoc rebuild is a new app to macOS's privacy checks.
- Verified on the phone: auto-mount about 7 s after launch, Show in Finder 0.26 s, quit 4 s with no mount left, Go wireless connects.
- The segmented List/Grid control was restyled (rounded fill, no square outline).

## Brand, site and DMG (2026-11-06)
- Brand in `brand/`: the cellar door mark (steps are holes; colour follows the theme), Funnel Display wordmark, `make_brand.py` generates every asset plus `mac/AppIcon.iconset` and `mac/Menubar*Template.png`. Guide: `brand/BRAND.md`.
- App: graphite icon with a white door, menu bar door (filled = connected, outline = no phone), wordmark in the sidebar, favicon recoloured per theme.
- Live 2026-11-06: site https://hystericmoon.github.io/cellar/ and release v0.2.0 (`Cellar.dmg`, built by CI, universal).
- Site: `docs/index.html` (GitHub Pages from `/docs`), door colour picker, install steps with Open Anyway.
- DMG: `mac/make-dmg.sh <version>` builds a universal app and a branded DMG with dmgbuild (create-dmg's Finder scripting didn't save the layout on macOS 26). `.github/workflows/release.yml` does it on a `v*` tag and uploads `Cellar.dmg`. Unsigned: first open needs Open Anyway. Tested 0.2.0 from a Safari-flagged copy: opened fine after Open Anyway.
- A clean Mac without Command Line Tools will be asked to install them (the app runs /usr/bin/python3). Bundling Python would remove this.

## Done 2026-11-22, second session (shipped as v0.2.2; the v0.2.1 tag exists but its release build failed on a script bug)
- **Camera stays upright** (`cellar.py`: `tilt_from_gravity`, `read_tilt`, `_watch_tilt`). scrcpy cannot rotate a running camera, so Cellar reads the phone's accelerometer from `dumpsys sensorservice` (newest samples) and restarts scrcpy with a new `--orientation` when the phone turns (read twice in a row). Back camera: `90 - tilt`; front camera: `270 + tilt` (Android's own rule). The window reopens around the same centre and is brought to the front with System Events (`NSRunningApplication.activate` does nothing from a background process on macOS 14+). When the phone's screen is off the sensor sleeps and the newest sample stops changing: Cellar then sends `KEYCODE_WAKEUP`. Checked live: back and front, all turns.
- **Take a photo** (`take_photo`, `POST /api/photo`, button in Phone controls): opens the Camera app, presses `KEYCODE_CAMERA`, pulls the new file to `~/Downloads/Cellar/Photos`. Needs an unlocked phone (it says so). Checked live on the A55.
- **Video thumbnails** (`video_thumb`): copies the video (<400 MB) once, Quick Look (`qlmanage -t`) draws a frame, cached like photos. Grid shows a play badge. Not made on non-Mac or for bigger files (icon stays).
- **Drop files on the menu bar icon** (`MenuDropView` in `Cellar.swift`, `POST /api/dropfiles`): APFS clone into staging, one push job into the phone's Download folder. **Works** (checked live 2026-11-22: the file reached the phone). Debug logging removed (`b6abea3`). The user confirmed the "Sending…" word shows next to the icon. The earlier failure was most likely an old build.
- **Shared clipboard** (`clipboard_sync`, toggle in Phone controls): scrcpy `--no-video --no-audio --no-window` keeps both clipboards equal. Checked live both ways. It stops when Cellar quits.
- **Bundled Python:** `mac/fetch-python.sh` downloads python-build-standalone (release 20261110, checksum checked, cached in `~/Library/Caches/Cellar/python`); `build-app.sh` puts it in `Resources/python-<arch>` when `UNIVERSAL=1` or `BUNDLE_PYTHON=1`; `Cellar.swift` prefers it. The DMG grows by about 50 MB. The universal DMG from CI is untested on a clean Mac.
- MIT `LICENSE` added (holder "hystericmoon").
- One CI run of `tests` failed 3 browser checks on the Free up space page (biggest file first, saved, trashed); the re-run of the same commit passed. Treat it as a flaky test, but watch it.
- A test photo (`DCIM/Camera/20261122_105905.jpg`) is on the phone and in `~/Downloads/Cellar/Photos`.

## Done 2026-11-22 (first session)
- **Only the file list scrolls:** `.app` has `grid-template-rows:minmax(0,1fr)`, `aside,main{min-height:0}`, `html,body{overflow:hidden}`, and `.sr` has `top:0;left:0` (the hidden `#announce` pushed the page 1px). Checked on Home, Settings, Free up space, Apps, Backup, Recent, Trash, Camera, and in `/?app=1`.
- **Battery:** the page read `/api/info` only when a phone connected. `refreshInfo()` now runs every 30 s (skipped while hidden) and on `visibilitychange`; it redraws only when battery or free space changed, keeps focus, and updates `#hmSub` on Home. The menu bar app already polled every 4 s.
- **Type filter:** funnel button `#kindBtn` next to Search opens a menu (All kinds, Folders, Images, Videos, Audio, Documents = text+pdf, Archives, Apps, Other) with counts; empty kinds are disabled. `S.kind` filters `visible()`, so select all takes only what's shown; hidden selected items are dropped. It clears when you open another folder or view. Empty state offers "Show all kinds".
- **Camera upright:** scrcpy sends the sensor picture sideways (this phone: back 90°, front 270°). `build_mirror_cmd` adds `--orientation=90` (back) / `270` (front). Checked: the back camera recording is now portrait. Not checked: the front camera, and ⌥←/⌥→ to turn it in the window.
- LinkedIn post drafted (text in chat only) and `linkedin/site-tall.png` made from the site. The site says "open source" but the repo has no LICENSE.
- Testing UI changes on this Mac without the test scripts: run a second server with the watcher off, then open it in the browser pane:
  `CELLAR_PORT=8790 CELLAR_NO_BROWSER=1 python3 -I -c "import sys; sys.path.insert(0,'.'); import cellar; cellar.device_watcher=lambda:None; cellar.main()"`
  (the watcher would run on-connect actions such as auto backup and Finder mount). Don't change settings there: it shares `~/.cellar.json`.

## Done 2026-11-22 (third session, not released yet)
- Menu bar drop works; debug logging removed.
- **Compress / Extract here** (`run_archive` in `cellar.py`, job kind `archive`, `archiveOp` in `ui.html`): pull, zip or unzip on the Mac with Python `zipfile`, push back. Refuses password zips and paths that climb out. Checked live on the A55 and in the browser pane.
- **Two panes** (`P2` code in `ui.html`, toolbar `#splitBtn`, ⌘\): a second phone folder. Drag between panes, ⌥ copies, Copy/Move buttons, right-click menu. Open state kept in localStorage `dv-split`. Checked live: copy, drag move, zip.
- Tests added to `tests/api_test.py` (zip/unzip) and `tests/e2e.js` (menu, two panes). **Not run** (they only run in CI); watch the next CI run.
- Gaps found by comparing with rivals, still to do: no-USB-debugging mode (MTP), away-from-Wi-Fi transfer, music playlists, Windows support, restore for contacts/messages, messages and notifications on the Mac. Second pane is phone-only (no Mac folder pane).

## No-USB-debugging mode: test results (2026-11-22, not built)
- Test phone: Samsung A55 on USB in File transfer mode, USB debugging off, with `libmtp` 1.1.23 from Homebrew (user OK'd; remove with `brew uninstall libmtp` if dropped).
- `ptpcamerad` (Mac's Image Capture helper) grabs the phone first: libusb claim fails with -3 (access). `pkill` (SIGTERM) does nothing; `kill -9` works, but launchd restarts it at once, so a session needs a fast kill right before opening, or a kill loop. Killing it is the user's call (said yes for the test). Do not disable it with launchctl.
- After the kill, `mtp-detect` worked. But `mtp-folders` and `mtp-files` did not finish in 120 s: libmtp's full-tree listing is too slow on this phone. A usable client must list one folder at a time (aft-mtp-cli or a custom libmtp/libusb client).
- Design from the advisor: route by device id `mtp:<serial>`; basic mode only (browse, save to Mac, add files, new folder, rename, delete with "deleted for good" confirm); hide all shell features and show a banner on how to turn on USB debugging; match MTP to adb by serial so a phone never shows twice; one long-lived MTP session behind a lock; bundle the binary + LGPL text; fake MTP tool in `tests/fakebin` for CI.

## Proposed, waiting for the user
- **Mirror inside the app.** (The user chose to skip it for now.) A) dock the scrcpy window next to Cellar's window with `--window-x/-y/-width/-height` (small; recommended). B) real in-app video: scrcpy-server stream, WebCodecs, input (several days). The user hasn't chosen.
- **Feature ideas not built yet:** none open. The user was offered the list on 2026-11-22 and everything except in-app mirroring was built.

## Still open
1. **GitHub support ticket** (checked 2026-11-06: not purged yet) asking to purge old commits `ae162fa`, `5a6acde`, `f6b8181`. When the reply comes, `https://github.com/hystericmoon/cellar/commit/ae162fa` should show "not found".
2. **Clean-Mac install** of the DMG: skipped by the user for now. Python is bundled now, so no Command Line Tools prompt is expected; untested on a clean Mac.
3. **Not verified:** Open Anyway with the CI-built DMG itself (the local build was tested; same sources). The menu bar door icon wasn't visible in a screenshot (a menu bar organiser may hide it); the user hasn't confirmed it.
4. **Developer ID + notarization** ($99/yr, user's call) would remove Open Anyway; `make-dmg.sh` notes where signing goes.
5. On the phone: Revoke USB debugging authorizations was used during the pairing test, so the next USB plug-in asks to allow the Mac again.
6. Impeccable skill update available (v4.8.0). Only on request.

## Done 2026-11-06 (this session)
- CI green for ba10e10; real Finder drag test passed (md5 match, Keep both); fresh wireless pairing works (VPN off). Drag-test files were moved to Cellar's Trash on the phone and the Mac Trash.
- Brand, site, DMG and release (see the section above). Site photos: 16 Unsplash images, no people, `docs/img/photos/CREDITS.txt`.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). v0.2.0 is released as a DMG and the site is at hystericmoon.github.io/cellar. Read `NEXT_SESSION.md`, then `HANDOFF.md` and `README.md`. Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them. Ask me what to work on next.
