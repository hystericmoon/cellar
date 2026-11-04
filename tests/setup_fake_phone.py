"""Builds the simulated phone used by the tests (Linux test container only; never run on a real Mac).

Creates /storage/emulated/0 with sample folders, photos and files, plus fake installed apps in /data/app.
Safe to re-run. tests/fakebin/adb maps adb commands onto this folder.
"""
import os
import struct
import zlib

R = "/storage/emulated/0"


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    c = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + c(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + c(b"IDAT", zlib.compress(raw)) + c(b"IEND", b"")


for d in ["DCIM/Camera", "DCIM/Screenshots", "Download", "Documents", "Pictures", "Music", "Movies/Clips", "My Folder"]:
    os.makedirs(os.path.join(R, d), exist_ok=True)
cols = [(220, 120, 80), (70, 140, 200), (90, 170, 120), (200, 180, 70), (150, 100, 190), (60, 60, 70)]
for i, c in enumerate(cols):
    open(f"{R}/DCIM/Camera/PXL_2026110{i}_1234{i}.png", "wb").write(png(400, 300, c))
open(f"{R}/DCIM/Camera/IMG_2041.heic", "wb").write(png(400, 300, cols[0]))
open(f"{R}/DCIM/Screenshots/Screenshot_2026.png", "wb").write(png(270, 580, (230, 230, 240)))
open("/tmp/shot.png", "wb").write(png(270, 580, (40, 44, 52)))
open(f"{R}/My Folder/notes & ideas.txt", "w").write("Shopping list\n- milk\n")
open(f"{R}/Download/report.pdf", "wb").write(os.urandom(3_000_000))
open(f"{R}/Download/app-release.apk", "wb").write(os.urandom(500_000))
open(f"{R}/Download/Invoice-Oct.pdf", "w").write("inv")
open(f"{R}/.hidden_file", "w").write("")
for pkg, files in {"com.whatsapp-1": {"base.apk": 300_000}, "org.telegram.messenger-2": {"base.apk": 200_000, "split_config.arm64.apk": 50_000}}.items():
    os.makedirs(f"/data/app/{pkg}", exist_ok=True)
    for n, size in files.items():
        open(f"/data/app/{pkg}/{n}", "wb").write(os.urandom(size))
print("Fake phone ready at", R)
