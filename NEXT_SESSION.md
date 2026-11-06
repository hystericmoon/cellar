# Cellar: next session

Updated 2026-11-06. Branch `feature/handoff-build` (same as `main`, latest commit `af753ac`; `main` has the merge commit `d5c095c`).

## State
- **Released:** Cellar 0.1.0 at https://github.com/hystericmoon/cellar/releases/tag/v0.1.0 with `Cellar-0.1.0-arm64.zip` (ad-hoc signed, Apple silicon only). The release notes cover install, the Gatekeeper right-click → Open step, `adb`/`scrcpy` requirements, and a troubleshooting section for the "not responding" launch hang (`xattr -dr com.apple.quarantine /Applications/Cellar.app`).
- **Merged:** PRs hystericmoon/cellar#1, hystericmoon/cellar#2 and hystericmoon/cellar#3 are all merged. `main` matches the feature branch.
- **CI green** at the last run: API 135, Browser 71.
- **Installed app:** `/Applications/Cellar.app` is a local build (starts in about 1 s). The downloaded release zip was replaced: macOS's security policy held it about a minute at launch or blocked it ("Security policy would not allow process"), even with the quarantine flag removed. The release notes and README now make building with `Build Mac App.command` the main install, and the build script strips the download flag from its own output, so building from a downloaded source zip is fast too. The real fix for the ready-made zip is a paid Apple Developer ID plus notarization.
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
- `/Applications/Cellar.app` is still the pre-redesign build; the new one is `cellar/Cellar.app` (untracked).
- Tests: loading "/#:x" from another "#:" page doesn't reload, so old toasts stay; reload with goto('/') first.

## Wireless and Show in Finder fixes (2026-11-06)
- Go wireless failed with "No route to host": Cellar lacked macOS Local Network permission, and adb inherits it from the app that starts it. Fixed: `NSLocalNetworkUsageDescription` + `NSBonjourServices` in build-app.sh, and the app browses for `_adb-tls-connect._tcp` at launch so macOS asks. Verified: Go wireless connects through Cellar.
- Show in Finder hung: dead WebDAV mounts (one from a test server on 8775) plus duplicate mounts. Fixed in cellar.py: a lock so auto-mount and the button can't mount twice; mounts whose server is gone are cleaned up at startup and before mounting (kill the mount_webdav helper, then `diskutil unmount force`). The Mac app unmounts its own mount on quit, before stopping the server. Unmounting from inside the server while it shuts down deadlocks: don't. Verified: quit takes about 4 s, leaves no mount, relaunch gets port 8765 back.
- `osascript mount volume` showed a "Connect as" dialog and blocked until it was answered. NetFS with NoUI/Guest/AllowLoopback avoided the dialog but still waited about 90 s inside NetAuthSysAgent. Now Cellar calls `/sbin/mount_webdav -s -S -v <name>` into `~/Library/Application Support/Cellar/Finder/<name>` (/Volumes needs admin rights): 0.7 s, no dialog, and Finder treats it as a volume. The helper process is `webdavfs_agent` on this macOS.
- WebDAV replies now read the request body once before answering (an unread body reset kept-alive connections).
- When started by the Mac app, the server restarts adb so it runs under the current build's Local Network permission. An adb left over from an earlier build can't reach the Wi-Fi. Every ad-hoc rebuild is a new app to macOS's privacy checks.
- Verified on the phone: auto-mount about 7 s after launch, Show in Finder 0.26 s, quit 4 s with no mount left, Go wireless connects.
- The segmented List/Grid control was restyled (rounded fill, no square outline).

## Still open
0. **Check CI for ba10e10** (`gh run list --branch main --limit 1`). Last confirmed green: 4de7856 (API 135, Browser 74). `/Applications/Cellar.app` is still the pre-redesign build; the current one is `cellar/Cellar.app` (offer to replace it).
1. **Real Finder drag** into Cellar. Only tested with a synthetic drop. Needs the user at the Mac.
2. **Wireless pairing** failed with "protocol fault" (slow Wi-Fi link, 111–702 ms pings; a WireGuard VPN was on). Workaround: connect by USB and use Cellar's cable-to-Wi-Fi option in the Wi-Fi dialog.
3. **GitHub support ticket** asking to purge old commits `ae162fa`, `5a6acde`, `f6b8181`. When the reply comes, `https://github.com/hystericmoon/cellar/commit/ae162fa` should show "not found".
4. Not tested: installing the release zip on a clean Mac.
5. Impeccable skill update available (v4.8.0). Only on request.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). v0.1.0 is released. Read `NEXT_SESSION.md`, then `HANDOFF.md` and `README.md`. Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them. Ask me what to work on next.
