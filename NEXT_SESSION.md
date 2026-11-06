# Cellar: next session

Updated 2026-11-06 (evening). Work happens on `main` (latest pushed: brand, site, DMG, Unsplash photos). Working tree clean.

## State
- **Released:** Cellar **0.2.0** at https://github.com/hystericmoon/cellar/releases/tag/v0.2.0: `Cellar.dmg` (universal, ad-hoc signed, not notarized) + `Cellar.dmg.sha256`, built by `.github/workflows/release.yml`. First open needs System Settings › Privacy & Security › Open Anyway (in README, site, release notes, and printed in the DMG window). v0.1.0 (arm64 zip) is older.
- **Site live:** https://hystericmoon.github.io/cellar/ (GitHub Pages from `main` `/docs`; also the repo homepage). Download button links `releases/latest/download/Cellar.dmg`, so future tags update it automatically.
- **CI:** tests green on main (API 135, Browser 74 at the last full run). The release workflow is green for v0.2.0.
- **Installed app:** `/Applications/Cellar.app` is 0.2.0 from a Safari-flagged copy of the DMG (tested Open Anyway: opened fine). The previous build is in the Mac Trash.
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

## Still open
1. **GitHub support ticket** (checked 2026-11-06: not purged yet) asking to purge old commits `ae162fa`, `5a6acde`, `f6b8181`. When the reply comes, `https://github.com/hystericmoon/cellar/commit/ae162fa` should show "not found".
2. **Clean-Mac install** of the DMG: skipped by the user for now. Known gap: a Mac without Command Line Tools gets asked to install them on first launch (the app runs /usr/bin/python3). Bundling a standalone Python (~40 MB) would remove this.
3. **Not verified:** Open Anyway with the CI-built DMG itself (the local build was tested; same sources). The menu bar door icon wasn't visible in a screenshot (a menu bar organiser may hide it); the user hasn't confirmed it.
4. **Developer ID + notarization** ($99/yr, user's call) would remove Open Anyway; `make-dmg.sh` notes where signing goes.
5. On the phone: Revoke USB debugging authorizations was used during the pairing test, so the next USB plug-in asks to allow the Mac again.
6. Impeccable skill update available (v4.8.0). Only on request.

## Done 2026-11-06 (this session)
- CI green for ba10e10; real Finder drag test passed (md5 match, Keep both); fresh wireless pairing works (VPN off). Drag-test files were moved to Cellar's Trash on the phone and the Mac Trash.
- Brand, site, DMG and release (see the section above). Site photos: 16 Unsplash images, no people, `docs/img/photos/CREDITS.txt`.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). v0.2.0 is released as a DMG and the site is at hystericmoon.github.io/cellar. Read `NEXT_SESSION.md`, then `HANDOFF.md` and `README.md`. Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them. Ask me what to work on next.
