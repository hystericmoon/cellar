# Cellar: handoff for the next build

Read this first in a fresh session. It replaces the conversation history.

## What Cellar is
A local app for an Android phone and a Mac. The Mac runs `cellar.py`, a Python stdlib server on
127.0.0.1:8765 that drives the phone through `adb`. The interface is `ui.html` (vanilla HTML/CSS/JS,
no build step, no React). `mac/Cellar.swift` plus `mac/build-app.sh` build a menu bar app on the
user's Mac (ad-hoc signed; the user has no paid Apple developer account and won't use the App Store).
`README.md` lists every user-facing feature.

The owner is a senior product designer. They want it to feel seamless next to Finder, and they work
visually: decisions go on a page with options drawn as UI and the recommendation marked.

## Code map
- `cellar.py`
  - phone ops (`list_dir`, `device_info`, …)
  - wireless (pairing, QR, auto-reconnect)
  - config (`load_cfg`/`update_cfg` → `~/.cellar.json`)
  - **job queue** (`new_job`, `RUNNERS`, lanes `transfer`/`phone`, `run_proc` with cancel and progress)
  - trash (`.CellarTrash` on the phone, with an `.index` of JSON lines)
  - search and recent
  - thumbnails (`sips` on macOS)
  - backup
  - apps
  - tools download (adb, scrcpy)
  - scrcpy mirroring
  - device watcher (on-connect actions)
  - **WebDAV** (`DavMixin`: Finder mounts the phone)
  - HTTP `Handler` (`handle_route` → core routes, then `api_ext` → extended routes)

  All `/api/*` requests need the `X-Token` header (or `t=`). `/dav` is unauthenticated but checks Host and Origin.
- `ui.html`
  - CSS tokens at the top: `--bg --panel --text --muted --line --hover --accent …`, plus a dark block
  - one `<script>`:
    - helpers: `api`, `postJSON`, `postJob`, `toast`
    - device card
    - navigation: `go`, `showView`, `showSearch`, hash routes `#:recent` etc.
    - `render`, selection
    - context menu: `openMenu`, `entryMenu`
    - dialogs: `confirmDialog`, `resolveConflicts`
    - transfers panel: `trackJob`, `pollJobs`
    - undo: `undoToast`
    - file ops: `phoneOp`, `trashEntries`, …
    - drag and drop
    - views: `renderBackup`, `renderApps`
    - mirror, Finder, settings
    - upload: `stageFiles` → push job
    - clipboard and keyboard

## Tests (run after every change)
`tests/run_all.sh` sets up a simulated phone (`tests/setup_fake_phone.py`, with `tests/fakebin/adb`
standing in for adb) and runs both suites from clean state:
- `tests/api_test.py`: 35 server checks
- `tests/e2e.js`: 28 Playwright browser checks (Chromium is preinstalled; `require('playwright')` works)

Baseline: **all 63 pass**. Add checks for every new feature, and extend `fakebin` (`pm`, `content`,
`sm`, …) when a feature needs new phone commands. Never run the test setup or reset scripts on a real Mac.

## The work: what the owner chose
**Style B, “shadcn/ui look”**: zinc neutrals (`#09090b` text, `#71717a` muted, `#e4e4e7` borders,
`#fafafa`/`#f4f4f5` surfaces), crisp 1px borders, a near-black primary button (`#18181b`), 6–8px
radius, Geist font (with a system fallback), and dark mode on zinc-950. Port the look as CSS tokens;
**don't add React or Tailwind**.
Accessibility requirement: shadcn's pale selection fill is under 3:1 against white, so selected rows
also need a visible marker, such as a checkmark plus a left border or outline (WCAG 1.4.11).
Keep focus rings clearly visible.

**Features, in this order:**
1. **SD card and USB drives**: detect volumes (`sm list-volumes` / `/storage/XXXX-XXXX`) and show
   each as a sidebar place. Make HOME-only assumptions per volume: Trash and search currently assume
   `HOME_DIR`.
2. **What's taking space**: storage by folder and file type, biggest files first, with Save to Mac then Trash.
3. **Find duplicate photos and files**: group by size, then hash (`md5sum` / `toybox md5sum` on the
   phone). Let the user pick which copy to keep, and move the others to the Cellar Trash.
4. **Export contacts, call history and calendar**: `adb shell content query --uri …`, saved as .vcf,
   .csv and .ics into `~/Downloads/Cellar/Exports/<date>/`.
5. **Save text messages as PDF or CSV**: `content://sms` (and mms). Some phones refuse this, so detect
   it and explain. For PDF, build HTML and convert it on the Mac (for example `cupsfilter` or a print
   from the WebKit window); CSV must always work.
6. **Phone camera on the Mac**: scrcpy `--video-source=camera` (Android 12+), offered as an option in the mirror dialog.
7. **Ring my phone, media keys, Do Not Disturb**: menu bar and UI extras through `input keyevent`,
   `cmd notification set_dnd`, and an alarm or ringtone intent. Mark anything that doesn't work on a
   given phone.
8. **Two-way folder sync** (hardest, so do it last): pairs of Mac folder ↔ phone folder, synced on
   connect and on demand. Keep a manifest of the last-synced state. A file changed on both sides is
   a conflict: keep both and show it. Never delete silently; replaced or removed files go to a
   versions folder or the Trash. Show a preview of the planned changes before the first sync.

## How to work
- Do the restyle first, so every new screen is built in the new style.
- After each feature: run `tests/run_all.sh`, then add tests for that feature.
- Follow the copy rules already in the UI: plain verbs, errors that say how to fix the problem, no jargon.
- Commit locally after each green step (the folder is a git repo). Rebuild `cellar.zip` at the end
  (exclude `.git`, `tests/shots`, `*.out`).
- Things a fake phone can't prove: real SMS permissions, `sm list-volumes` output, scrcpy camera, and
  the Swift build. Report these as untested.
