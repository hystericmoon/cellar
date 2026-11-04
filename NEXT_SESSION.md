# Cellar: next session

Written 2026-11-05 at the end of the verification and UI-audit session. Branch: `feature/handoff-build` (PR hystericmoon/cellar#2, base `initial-app`). Latest commit when this was written: `ccbe782`.

## State
- Swift app builds. `Cellar.app` in this folder is a local build (not committed) with every fix below.
- CI (`.github/workflows/tests.yml`) runs `tests/run_all.sh` on Linux. At `c501caf` it passed: API 134, Browser 69. The UI fixes in `ccbe782` add two browser checks (expect 71) and are not yet confirmed green when this was written. Check the PR's Checks tab first.
- Never run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac (they write to `/storage` and delete `~/Downloads/Cellar`). CI runs them.

## Verified on a real phone (Samsung SM-A556E, Android 17) and this Mac
Swift build and Phone Controls menu items; DND (all 4 modes); media keys; Ring (audible); contacts, calendar and call exports with imports into Contacts.app and Calendar.app; Text messages CSV and PDF (Chrome); provider-refusal message; no-browser PDF fallback; camera front and back; two-way folder sync (preview, edits, conflicts, deletions, auto-sync on connect); CSVs in GridCraft.

## Fixed this session (all pushed)
- `27479f3` bundle `fonts/` into `Cellar.app`.
- `3b964bc` Ring targets one Clock app (phones with two showed a chooser and set nothing). Test in `b9573c1`.
- `1ca376d` CSV: bare phone numbers grouped in fours so spreadsheets keep them as text; cells starting `=` or `@` get a leading apostrophe. Tested in GridCraft: tab, `="…"` and nbsp tricks do not work.
- `c501caf` CI workflow.
- `ccbe782` UI audit fixes: backup path overlap, toolbar hides file-only buttons on page views, loading text, sync form starts empty and hides the redundant button/empty state, Apps table (wider version column, titles, red Uninstall), mirror dialog (title follows tab, spacing, stable height), preview scrollbar, shorter folder tiles in grid, thumbnail shimmer, window minimum width 860.

## Still open
1. **Confirm CI is green** at `ccbe782` (expect API 134, Browser 71).
2. **SD card / USB drive** (volumes, labels 179 vs 8, per-drive Trash/search/Recent, Finder): untested. Needs a spare card or stick in the phone. A card in the Mac does not count. Do not test on a full card with real data.
3. **Re-export contacts**: `~/Downloads/Cellar/Exports/2026-11-05/contacts.csv` already has the number fix. Re-export the calendar if needed.
4. **Numbers**: not installed. GridCraft was the substitute.
5. **Duplicate contacts** (e.g. Aan Putut twice): looks like one contact stored under two accounts. Unconfirmed. Possible separate change.
6. **New folder** creates `untitled folder` on the phone immediately and Escape keeps it. This matches Finder, so it was left as is. Say if you want Escape to undo it.
7. **Audited 2026-11-05 (second session)**: space, duplicates, photo backup run (screenshots only), Sync preview/conflict/deletions, Wi-Fi dialog, drag and drop (synthetic drop), 860px window. Fixed in e9f9a95 and 854d52f. Not done: a real Finder drag, backup of Camera (20 GB).
   Old list: Duplicates and What's taking space result screens (the scans take 20+ seconds on this phone), the Photo backup run, the conflict/preview screens of Sync with real pairs, drag and drop, the Wi-Fi pairing dialog, narrow-window drawer (window minimum is now 860 so the sidebar no longer disappears).
8. Impeccable skill update available (v4.8.0). Only on request.
9. Housekeeping: delete any leftover "Cellar test" alarms in the Clock app; `~/Downloads/Cellar/Exports` and the camera recording hold real data.

## Prompt to paste after /clear

> Context: Cellar is a local Android file manager for the Mac (`cellar.py` Python stdlib server on 127.0.0.1:8765 driving the phone through adb; `ui.html`; `mac/Cellar.swift` menu bar app). Read `NEXT_SESSION.md`, then `HANDOFF.md` and `README.md`. Branch `feature/handoff-build` (PR hystericmoon/cellar#2). Do not run `tests/setup_fake_phone.py`, `tests/reset.py` or `tests/run_all.sh` on this Mac; CI runs them.
>
> 1. Check the PR's CI result at the latest commit (`gh run list --branch feature/handoff-build`). If anything failed, read the log, fix it, commit and push.
> 2. Do the "Still open" items from `NEXT_SESSION.md` that don't need hardware I haven't plugged in. Start with item 7 (audit the screens not yet audited, with the phone connected) and fix what you find.
> 3. For item 2 (SD card or USB drive), ask me whether a spare card or stick is in the phone before running anything.
> 4. Finish with a short report: what passed, what you fixed, what is still untested. Commit fixes to the same branch and push.
