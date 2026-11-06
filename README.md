# Cellar

Your Android phone, on your Mac. Browse, preview, copy, move and back up files, by cable or Wi-Fi.
Everything runs on your Mac (127.0.0.1). Nothing goes to the internet.

## Get started

1. **On the phone (once):** Settings › About phone › tap **Build number** 7 times, then
   Settings › System › Developer options › turn on **USB debugging**. Plug in and tap **Allow**.
2. **On the Mac, pick one:**
   - **Mac app (recommended):** double-click **Build Mac App.command**. It builds `Cellar.app`
     (a menu bar icon plus a window) and offers to move it to Applications. It needs Apple's free
     Command Line Tools, which the script offers to install. No Apple developer account is needed.
   - **Browser version:** double-click **Start Cellar.command**. It opens in your browser.

   Build it yourself rather than using the ready-made zip from the Releases page. A downloaded
   copy isn't signed by an Apple developer account, so macOS may hold it up to a minute at launch
   or block it. A copy built on your Mac starts in about a second.

   If macOS blocks a `.command` file the first time, right-click it and choose Open. If it's not
   allowed to run, run `chmod +x *.command` in this folder.
3. If the Android tools (adb) aren't installed, Cellar shows a **Download Android tools**
   button. Homebrew isn't required.

## Everything it does

**Files**
- Cut, copy and paste: ⌘X, ⌘C, ⌘V, and ⌥⌘V to move. Copy files in Finder and press ⌘V in Cellar to send them to the phone.
- Right-click menu, also available from the ⋯ button or Shift+F10.
- Drag files onto folders, breadcrumbs or sidebar places to move them. Hold ⌥ to copy instead.
- Rename (F2), duplicate (⌘D), new folder (⌥⌘N), Space to preview, ⌘Z to undo.
- Delete (⌘⌫) moves items to Cellar's Trash on the phone. You can put them back for 30 days.
- “Already exists” dialog: Replace, Keep both or Skip (Merge for folders), with “do this for all”.
- Transfer queue with speed, time left and cancel. You can keep browsing while it runs.
- Search the whole phone (type, then Enter), plus a Recent view.
- Photo timeline in Camera, with fast thumbnails made once and kept on your Mac.
- Open with Mac app: edit a phone file in Preview, Pages and so on. Saving copies it back to the phone.

**Mac integration**
- **Show in Finder:** the phone appears under Locations. Finder's own copy, paste, drag and
  Quick Look work there. Deleting in Finder moves items to Cellar's Trash. This uses WebDAV,
  which Finder supports natively, so no paid Apple entitlement is needed.
- Menu bar icon showing the phone, battery and connection, with quick actions.
- Notifications when long transfers or backups finish.

**Phone**
- Photo backup: copies only new photos and videos, can convert HEIC to JPG, and can run automatically on connect.
- Apps: install .apk files by dropping them, save installed apps to your Mac, uninstall.
- Screen mirroring with sound, recording, a real-keyboard mode and screen-off mode. It uses scrcpy, which Cellar can download for you.
- Wi-Fi: Go wireless, or connect with a QR code or pairing code (Android 11+). Cellar reconnects by itself.
- Screenshots, battery and storage, and switching between multiple phones.
- SD cards and USB drives show up in the sidebar. Each has its own Trash, search and Recent.
- What's taking space: storage by file type and folder, the biggest files, and Save to Mac then move to Trash.
- Duplicates: finds files with identical content, lets you pick the copy to keep, and moves the rest to the Trash.
- Contacts & calendar: exports contacts (.vcf and .csv), call history (.csv) and calendar (.ics) to `~/Downloads/Cellar/Exports/<date>`.
- Text messages: saves them as PDF or CSV. Some phones refuse to share messages; Cellar says so. PDF needs Chrome, Edge or Brave on the Mac, otherwise it saves a web page you can print to PDF.
- Phone camera as a webcam on the Mac (Android 12+, scrcpy 2.2+), from the mirror dialog.
- Phone controls: ring my phone, music and volume keys, Do Not Disturb. Also in the menu bar. Not every phone supports every one.
- Sync folders: two-way sync between a Mac folder and a phone folder, with a preview before the first sync. Files changed on both sides are kept as both versions. Replaced or removed files go to the phone's Trash or `~/Downloads/Cellar/Sync versions`, never deleted outright.

## Where things go
- Saved files: `~/Downloads/Cellar`
- Photo backups: `~/Pictures/Cellar/<phone>` (you can change this)
- Settings and paired phones: `~/.cellar.json`
- Thumbnail cache: `~/Library/Caches/Cellar` (trimmed automatically)

## Notes
- Android 11+ blocks `Android/data` and `Android/obb` for every app.
- The QR pairing code needs internet access to draw. The other connection methods don't.
- Use Wi-Fi connections only on networks you trust.
- `CELLAR_PORT` changes the port. `ADB=/path/to/adb` points to a specific adb.
