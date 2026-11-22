# Cellar: handoff

Read this first in a fresh session, then `NEXT_SESSION.md` (current state and open work) and `README.md` (every user-facing feature).

## What Cellar is
A local app for an Android phone and a Mac. The Mac runs `cellar.py`, a Python stdlib server on 127.0.0.1:8765 that drives the phone through `adb`. The interface is `ui.html` (vanilla HTML/CSS/JS, no build step, no React, no Tailwind). `mac/Cellar.swift` plus `mac/build-app.sh` build a menu bar app (ad-hoc signed; the user has no paid Apple developer account and won't use the App Store). Releases are a DMG built by CI.

The owner is a senior product designer. They want it to feel seamless next to Finder, and they work visually: decisions go on a page with options drawn as UI and the recommendation marked.

## Code map
- `cellar.py`
  - phone ops (`list_dir`, `device_info`, …)
  - wireless (pairing, QR, auto-reconnect)
  - config (`load_cfg`/`update_cfg` → `~/.cellar.json`)
  - **job queue** (`new_job`, `RUNNERS`, lanes `transfer`/`phone`, `run_proc` with cancel and progress)
  - trash (`.CellarTrash` on the phone, with an `.index` of JSON lines)
  - search and recent, thumbnails (`sips`, Quick Look for video), backup, apps
  - archives (`run_archive`), exports (contacts, calls, calendar, messages), duplicates, space report, folder sync
  - tools download (adb, scrcpy), scrcpy mirroring, camera, clipboard sync
  - device watcher (on-connect actions)
  - **WebDAV** (`DavMixin`: Finder mounts the phone)
  - HTTP `Handler` (`handle_route` → core routes, then `api_ext` → extended routes)

  All `/api/*` requests need the `X-Token` header (or `t=`). `/dav` is unauthenticated but checks Host and Origin.
- `ui.html`
  - CSS tokens at the top (`--bg --panel --text --muted --line --hover --accent …`); six themes override them
  - one `<script>`:
    - helpers: `api`, `postJSON`, `postJob`, `toast`
    - navigation: `go`, `showView`, hash routes `#:home`, `#:settings`, `#:recent` …
    - `render`, selection, context menu (`openMenu`, `entryMenu`), dialogs (`confirmDialog`, `resolveConflicts`)
    - transfers panel (`trackJob`, `pollJobs`), undo (`undoToast`)
    - file ops (`phoneOp`, `trashEntries`, `archiveOp`), drag and drop, two panes (`P2`)
    - views: Home, Backup, Apps, Free up space, Settings
    - mirror, Finder, upload (`stageFiles` → push job), clipboard and keyboard
- `mac/Cellar.swift`: window, menu bar, drop on the icon, Local Network permission, server start and stop.
- `tests/`: `api_test.py` (server checks), `e2e.js` (Playwright browser checks), `fakebin/` (fake adb and phone tools), `setup_fake_phone.py`, `reset.py`, `run_all.sh`.
- `docs/`: the GitHub Pages site. `brand/`: logo, assets, `BRAND.md`.

## Tests
`tests/run_all.sh` sets up a simulated phone and runs both suites from clean state. **CI runs it, not this Mac**: the scripts write to `/storage` and delete `~/Downloads/Cellar`. Never run `setup_fake_phone.py`, `reset.py` or `run_all.sh` on the owner's Mac. Last known CI result: API 148, Browser 84.

Add checks for every new feature. Extend `fakebin` (`pm`, `content`, `sm`, …) when a feature needs new phone commands. Things a fake phone cannot prove: real SMS permissions, `sm list-volumes` output, scrcpy camera, the Swift build. Report these as untested.

## How to work
- Follow the copy rules in the UI: plain verbs, errors that say how to fix the problem, no jargon.
- Accessibility: a selected row needs a visible marker (checkmark plus outline), not only a pale fill (WCAG 1.4.11). Keep focus rings clearly visible.
- Commit after each green step. Keep `linkedin/` out of commits.
- Update `NEXT_SESSION.md` before any `/clear` or model switch.
