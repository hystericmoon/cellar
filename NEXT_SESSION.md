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

## Redesign (2026-11-06, not committed yet)
Built from the mockup at https://claude.ai/artifact/XTKLCvXyfrA1j6qbxezCnr, in `ui.html`, `mac/Cellar.swift` and `tests/e2e.js`:
- Six themes (Graphite default, Violet, Midnight, Forest, Ember, Daylight) in Settings, now a page (`#:settings`) instead of a dialog. Match macOS (off by default) switches to Daylight in light mode. Stored in localStorage `dv-theme`, `dv-matchos`, `dv-glass`, `dv-kind`.
- Liquid Glass: the Mac app loads `/?app=1`; its window has a transparent title bar over `NSGlassEffectView` (macOS 26+) or `NSVisualEffectView`, with a 248×40 `DragStrip` over the top of the sidebar for dragging. The page makes the sidebar see-through (`html.in-app.glass`). In any browser, menus, dialogs, toasts and transfers use backdrop blur. Don't name a root class `app`: it clashes with the `.app` grid.
- Home (`#:home`) is the first screen: backup finding, storage, quick actions, latest Camera photos, Recent.
- Sidebar: compact device row (click for details), Home, Favorites (Internal storage, Camera, Pictures, Downloads, Documents; right-click a folder › Add to sidebar), folding Tools and Phone groups, Trash and Settings at the bottom. Recent lives on Home; Duplicates is a tab of Free up space.
- Colour by kind on folders, file icons and sidebar icons; spotlight hover on tiles; hidden folders sort last; labelled toolbar buttons; Phone controls in two columns.
- Checked: page parses, Settings and theme switching in the browser, the Mac window layout with glass. Not yet checked with the phone connected (Home, folders, Camera grid), and CI has not run the updated tests.

## Still open
1. **Real Finder drag** into Cellar. Only tested with a synthetic drop. Needs the user at the Mac.
2. **Wireless pairing** failed with "protocol fault" (slow Wi-Fi link, 111–702 ms pings; a WireGuard VPN was on). Workaround: connect by USB and use Cellar's cable-to-Wi-Fi option in the Wi-Fi dialog.
3. **GitHub support ticket** asking to purge old commits `ae162fa`, `5a6acde`, `f6b8181`. When the reply comes, `https://github.com/hystericmoon/cellar/commit/ae162fa` should show "not found".
4. Not tested: installing the release zip on a clean Mac.
5. Impeccable skill update available (v4.8.0). Only on request.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). v0.1.0 is released. Read `NEXT_SESSION.md`, then `HANDOFF.md` and `README.md`. Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them. Ask me what to work on next.
