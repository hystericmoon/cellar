# Cellar: next session

Updated 2026-11-06. Branch `feature/handoff-build` (same as `main`, latest commit `af753ac`; `main` has the merge commit `d5c095c`).

## State
- **Released:** Cellar 0.1.0 at https://github.com/hystericmoon/cellar/releases/tag/v0.1.0 with `Cellar-0.1.0-arm64.zip` (ad-hoc signed, Apple silicon only). The release notes cover install, the Gatekeeper right-click → Open step, `adb`/`scrcpy` requirements, and a troubleshooting section for the "not responding" launch hang (`xattr -dr com.apple.quarantine /Applications/Cellar.app`).
- **Merged:** PRs hystericmoon/cellar#1, hystericmoon/cellar#2 and hystericmoon/cellar#3 are all merged. `main` matches the feature branch.
- **CI green** at the last run: API 135, Browser 71.
- **Installed app:** only `/Applications/Cellar.app` (the release download). The project-folder build was deleted; rebuild with `Build Mac App.command`. The `/Applications` copy needs right-click → Open or the `xattr` command once, because of the quarantine flag.
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

## Still open
1. **Real Finder drag** into Cellar. Only tested with a synthetic drop. Needs the user at the Mac.
2. **Wireless pairing** failed with "protocol fault" (slow Wi-Fi link, 111–702 ms pings; a WireGuard VPN was on). Workaround: connect by USB and use Cellar's cable-to-Wi-Fi option in the Wi-Fi dialog.
3. **GitHub support ticket** asking to purge old commits `ae162fa`, `5a6acde`, `f6b8181`. When the reply comes, `https://github.com/hystericmoon/cellar/commit/ae162fa` should show "not found".
4. Not tested: installing the release zip on a clean Mac.
5. Impeccable skill update available (v4.8.0). Only on request.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). v0.1.0 is released. Read `NEXT_SESSION.md`, then `HANDOFF.md` and `README.md`. Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them. Ask me what to work on next.
