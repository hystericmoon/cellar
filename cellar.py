#!/usr/bin/env python3
"""
Cellar: browse an Android phone from your Mac, in your browser.

Requires: python3 (ships with Xcode Command Line Tools) and adb
          (brew install --cask android-platform-tools).
Run:      python3 cellar.py
Nothing leaves your machine; the server listens on 127.0.0.1 only.
"""
import datetime
import json
import mimetypes
import os
import posixpath
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME_DIR = "/storage/emulated/0"
SAVE_DIR = os.path.expanduser("~/Downloads/Cellar")
TOKEN = os.environ.get("CELLAR_TOKEN") or secrets.token_urlsafe(24)  # the Mac app passes its own
CHUNK = 256 * 1024

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("video/mp4", ".m4v")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/ogg", ".opus")


def find_adb():
    candidates = [
        os.environ.get("ADB"),
        shutil.which("adb"),
        "/opt/homebrew/bin/adb",
        "/usr/local/bin/adb",
        os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
        os.path.expanduser("~/Library/Application Support/Cellar/tools/platform-tools/adb"),
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


ADB = find_adb()


class AdbError(Exception):
    pass


def adb(serial, *args, timeout=30, check=True, binary=False):
    if not ADB:
        raise AdbError("adb is not installed")
    cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        msg = (p.stderr or p.stdout).decode("utf-8", "replace").strip()
        raise AdbError(msg or "adb command failed")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def clean_path(path):
    if not path or not path.startswith("/"):
        raise AdbError("Path must be absolute")
    return posixpath.normpath(path)


# ---------------------------------------------------------------- phone ops

_hw_ids = {}


def hw_id(serial):
    """The phone's own serial number, so one phone seen over USB and Wi-Fi counts once."""
    if serial not in _hw_ids:
        out = adb(serial, "shell", "getprop ro.serialno", timeout=5, check=False).strip()
        _hw_ids[serial] = out or serial
    return _hw_ids[serial]


def list_devices():
    if not ADB:
        return {"adb": False, "devices": []}
    out = adb(None, "devices", "-l", timeout=10, check=False)
    raw = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        d = {"serial": serial, "state": parts[1], "model": "", "transport": "other"}
        for p in parts[2:]:
            if p.startswith("model:"):
                d["model"] = p[6:].replace("_", " ")
            if p.startswith("usb:"):
                d["transport"] = "usb"
        if d["transport"] != "usb" and (":" in serial or "_adb-tls-connect" in serial):
            d["transport"] = "wifi"
        raw.append(d)
    # Merge duplicates: prefer USB (faster) and flag that Wi-Fi is ready as a fallback.
    groups, order = {}, []
    for d in raw:
        key = hw_id(d["serial"]) if d["state"] == "device" else d["serial"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    devices = []
    for key in order:
        g = sorted(groups[key], key=lambda d: {"usb": 0, "wifi": 1}.get(d["transport"], 2))
        best = dict(g[0])
        best["wifi_ready"] = any(x["transport"] == "wifi" for x in g)
        best["wifi_serial"] = next((x["serial"] for x in g if x["transport"] == "wifi"), None)
        devices.append(best)
    maybe_reconnect({d["serial"] for d in raw})
    return {"adb": True, "devices": devices}


# ---------------------------------------------------------------- wireless

KNOWN_FILE = os.path.expanduser("~/.cellar.json")
_reconnect = {"last": 0.0, "busy": False}
QR = {"state": "idle"}


def load_known():
    return [a for a in load_cfg().get("wifi", []) if isinstance(a, str)]


def save_known(addrs):
    update_cfg(lambda d: d.__setitem__("wifi", addrs[:8]))


def remember(addr):
    save_known([addr] + [a for a in load_known() if a != addr])


def forget(addr):
    ip = addr.rpartition(":")[0]
    save_known([a for a in load_known() if a != addr and a.rpartition(":")[0] != ip])


def valid_addr(addr):
    addr = (addr or "").strip()
    host, _, port = addr.rpartition(":")
    if not re.fullmatch(r"[0-9A-Za-z.\-]+", host or "") or not port.isdigit():
        raise AdbError("Use the format 192.168.1.20:5555")
    return addr


def adb_connect(addr, timeout=8):
    try:
        out = adb(None, "connect", addr, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False
    return "connected to" in out


def mdns_services():
    """Phones on the network with Wireless debugging on (Android 11+), found via Bonjour."""
    try:
        out = adb(None, "mdns", "services", timeout=6, check=False)
    except subprocess.TimeoutExpired:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "_adb-tls-" in parts[1]:
            found.append({"name": parts[0], "addr": parts[-1],
                          "type": "pairing" if "pairing" in parts[1] else "connect"})
    return found


def connect_by_ip(ip, wait=15):
    """After pairing, the phone advertises a separate connect port. Find it and connect."""
    deadline = time.time() + wait
    while time.time() < deadline:
        for s in mdns_services():
            if s["type"] == "connect" and s["addr"].rpartition(":")[0] == ip:
                if adb_connect(s["addr"]):
                    remember(s["addr"])
                    return s["addr"]
        time.sleep(1.5)
    return None


def maybe_reconnect(connected):
    """Quietly reconnect phones used over Wi-Fi before (runs at most every 8 s, in the background)."""
    if _reconnect["busy"] or time.time() - _reconnect["last"] < 8:
        return
    known = [a for a in load_known() if a not in connected]
    if not known:
        return
    _reconnect.update(busy=True, last=time.time())

    def work():
        try:
            ips = {a.rpartition(":")[0] for a in known}
            for s in mdns_services():  # port changes each time Wireless debugging is toggled
                if s["type"] == "connect" and s["addr"].rpartition(":")[0] in ips and s["addr"] not in connected:
                    if adb_connect(s["addr"], timeout=4):
                        remember(s["addr"])
                        ips.discard(s["addr"].rpartition(":")[0])
            for a in known:
                if a.rpartition(":")[0] in ips:
                    adb_connect(a, timeout=3)
        finally:
            _reconnect.update(busy=False, last=time.time())

    threading.Thread(target=work, daemon=True).start()


def wifi_enable(serial):
    """Cable → Wi-Fi in one step (works on every Android version, lasts until the phone restarts)."""
    out = adb(serial, "shell", "ip -o -f inet addr show 2>/dev/null", check=False)
    candidates = re.findall(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)", out, re.M)
    ip = next((a for i, a in candidates if i.startswith("wlan")), None) or next(
        (a for i, a in candidates if i != "lo" and not i.startswith(("rmnet", "ccmni", "dummy"))), None)
    if not ip:
        raise AdbError("The phone isn't on Wi-Fi. Join the same network as your Mac and try again.")
    adb(serial, "tcpip", "5555", timeout=15)
    addr = f"{ip}:5555"
    for _ in range(10):
        time.sleep(1)
        if adb_connect(addr, timeout=4):
            remember(addr)
            return addr
    raise AdbError(f"Wireless is on, but your Mac can't reach {ip}. Are both on the same Wi-Fi?")


def wifi_pair(addr, code):
    addr = valid_addr(addr)
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        raise AdbError("The pairing code has 6 digits")
    out = adb(None, "pair", addr, code, timeout=25, check=False)
    if "Successfully paired" not in out:
        raise AdbError("Pairing failed. Check the code and the IP address and port, then try again.")
    return connect_by_ip(addr.rpartition(":")[0])


def qr_start():
    name = "cellar-" + secrets.token_hex(3)
    password = secrets.token_hex(5)
    QR.clear()
    QR.update(state="waiting", name=name)
    threading.Thread(target=_qr_worker, args=(name, password), daemon=True).start()
    return {"payload": f"WIFI:T:ADB;S:{name};P:{password};;"}


def _qr_worker(name, password):
    deadline = time.time() + 240
    while time.time() < deadline and QR.get("name") == name:
        for s in mdns_services():
            if s["type"] == "pairing" and s["name"].startswith(name):
                QR["state"] = "pairing"
                out = adb(None, "pair", s["addr"], password, timeout=25, check=False)
                if "Successfully paired" not in out:
                    QR.update(state="error", message="Pairing failed. Try scanning again.")
                    return
                QR["state"] = "connecting"
                addr = connect_by_ip(s["addr"].rpartition(":")[0])
                QR.update(state="connected" if addr else "paired", address=addr)
                return
        time.sleep(1.5)
    if QR.get("name") == name and QR.get("state") == "waiting":
        QR.update(state="error", message="Timed out. Close this and try again.")


def device_info(serial):
    script = (
        "getprop ro.product.manufacturer; getprop ro.product.model; "
        "getprop ro.build.version.release; "
        "dumpsys battery 2>/dev/null | grep -m1 ' level:' || echo; "
        f"df -k {HOME_DIR} 2>/dev/null | tail -n 1"
    )
    lines = adb(serial, "shell", script, check=False).splitlines() + [""] * 5
    info = {
        "manufacturer": lines[0].strip().title(),
        "model": lines[1].strip(),
        "android": lines[2].strip(),
        "battery": None,
        "storage": None,
    }
    try:
        info["battery"] = int(lines[3].split(":")[1])
    except (IndexError, ValueError):
        pass
    cols = lines[4].split()
    try:
        info["storage"] = {"total": int(cols[1]) * 1024, "used": int(cols[2]) * 1024,
                           "free": int(cols[3]) * 1024}
    except (IndexError, ValueError):
        pass
    return info


def list_dir(serial, path):
    path = clean_path(path)
    q = shlex.quote(path)
    # One stat call for the whole folder (fast even for big DCIM folders).
    # -L follows symlinks so linked folders show up as folders.
    script = (
        f"[ -d {q} ] || {{ echo __NODIR__; exit 0; }}; cd {q} || exit 0; "
        "stat -L -c '%F|%s|%Y|%n' ./* ./.[!.]* ./..?* 2>/dev/null; true"
    )
    out = adb(serial, "shell", script, timeout=60)
    if out.strip() == "__NODIR__":
        raise AdbError("That folder doesn't exist")
    entries = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        ftype, size, mtime, name = parts
        name = name[2:] if name.startswith("./") else name
        if not name or name in ("*", ".[!.]*", "..?*"):
            continue
        is_dir = ftype.strip() == "directory"
        try:
            entries.append({"name": name, "dir": is_dir,
                            "size": 0 if is_dir else int(size), "mtime": int(mtime)})
        except ValueError:
            continue
    return {"path": path, "entries": entries}


def file_size(serial, path):
    out = adb(serial, "shell", f"stat -L -c %s {shlex.quote(path)}", check=False).strip()
    try:
        return int(out)
    except ValueError:
        raise AdbError("File not found or not readable")


def unique_dest(folder, name):
    os.makedirs(folder, exist_ok=True)
    base, ext = os.path.splitext(name)
    dest = os.path.join(folder, name)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return dest


def pull_to_mac(serial, path, into=""):
    path = clean_path(path)
    folder = SAVE_DIR
    into = re.sub(r'[/:\\]', "-", into or "").strip(" .")
    if into:
        folder = os.path.join(SAVE_DIR, into)
    dest = unique_dest(folder, posixpath.basename(path) or "phone")
    adb(serial, "pull", "-a", path, dest, timeout=6 * 3600)
    return dest


def push_from_mac(serial, local, remote_dir, name):
    """name may be a relative path like "Trip/Day 1/photo.jpg" when a folder is dropped."""
    remote_dir = clean_path(remote_dir)
    parts = [p.strip() for p in name.replace("\\", "/").split("/") if p.strip() not in ("", ".")]
    if not parts or ".." in parts:
        raise AdbError("Invalid file name")
    target = posixpath.join(remote_dir, *parts)
    if len(parts) > 1:
        adb(serial, "shell", "mkdir -p " + shlex.quote(posixpath.dirname(target)))
    adb(serial, "push", local, target, timeout=6 * 3600)


# ---------------------------------------------------------------- config & paths

IS_MAC = sys.platform == "darwin"
SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/Cellar")
CACHE_DIR = os.path.expanduser("~/Library/Caches/Cellar")
STAGE_ROOT = os.path.join(CACHE_DIR, "staging")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbs")
TRASH_DIR = HOME_DIR + "/.CellarTrash"
TRASH_DAYS = 30
_cfg_lock = threading.Lock()
q = shlex.quote


class Cancelled(Exception):
    pass


def load_cfg():
    # Settings from before the rename (DroidView) carry over the first time.
    if not os.path.exists(KNOWN_FILE) and os.path.exists(os.path.expanduser("~/.droidview.json")):
        try:
            shutil.copy(os.path.expanduser("~/.droidview.json"), KNOWN_FILE)
        except OSError:
            pass
    try:
        with open(KNOWN_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def update_cfg(fn):
    with _cfg_lock:
        d = load_cfg()
        fn(d)
        tmp = KNOWN_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(d, f, indent=1)
            os.replace(tmp, KNOWN_FILE)
        except OSError:
            pass
        return d


def sh(serial, script, timeout=60, check=False):
    return adb(serial, "shell", script, timeout=timeout, check=check)


def clean_name(name):
    name = (name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\0" in name:
        raise AdbError("Names can't be empty or contain “/”.")
    if len(name.encode()) > 255:
        raise AdbError("That name is too long.")
    return name


def split_ext(name, is_dir=False):
    if is_dir or name.startswith(".") and name.count(".") == 1:
        return name, ""
    base, ext = os.path.splitext(name)
    return (base, ext) if base else (name, "")


def keep_both_name(name, taken, is_dir=False):
    """Finder style: “IMG_2041 2.jpg”, “IMG_2041 3.jpg” …"""
    base, ext = split_ext(name, is_dir)
    m = re.match(r"^(.*) (\d+)$", base)
    if m:
        base, n = m.group(1), int(m.group(2)) + 1
    else:
        n = 2
    while f"{base} {n}{ext}" in taken:
        n += 1
    return f"{base} {n}{ext}"


def stat_names(serial, folder, names):
    """{name: {dir, size, mtime}} for the names that exist in a phone folder."""
    if not names:
        return {}
    script = f"cd {q(folder)} 2>/dev/null && stat -L -c '%F|%s|%Y|%n' -- " + " ".join(q(n) for n in names) + " 2>/dev/null; true"
    found = {}
    for line in sh(serial, script).splitlines():
        p = line.split("|", 3)
        if len(p) == 4 and p[3] in names:
            try:
                found[p[3]] = {"dir": p[0] == "directory", "size": int(p[1]), "mtime": int(p[2])}
            except ValueError:
                pass
    return found


def phone_names(serial, folder):
    return {e["name"] for e in list_dir(serial, folder)["entries"]}


def batch_sizes(serial, paths):
    """Bytes for each phone path (folders via du) in one round trip."""
    if not paths:
        return []
    parts = []
    for p in paths:
        qp = q(p)
        parts.append(f"if [ -d {qp} ]; then echo d$(du -sk {qp} 2>/dev/null | cut -f1); "
                     f"else echo f$(stat -L -c %s {qp} 2>/dev/null); fi")
    out = sh(serial, "; ".join(parts), timeout=120).splitlines()
    sizes = []
    for i in range(len(paths)):
        line = out[i] if i < len(out) else ""
        try:
            n = int(line[1:] or 0)
            sizes.append(n * 1024 if line.startswith("d") else n)
        except ValueError:
            sizes.append(0)
    return sizes


def remote_bytes(serial, path):
    return batch_sizes(serial, [path])[0]


def local_size(path):
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def adb_msg(out):
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    msg = lines[-1] if lines else "adb failed"
    msg = re.sub(r"^adb: (error: )?", "", msg)
    if "Permission denied" in msg:
        return "Android doesn't allow access to that item."
    if "No space left" in msg:
        return "Not enough free space."
    return msg[:200]


def notify(title, message):
    if not IS_MAC or not load_cfg().get("settings", {}).get("notifications", True):
        return
    esc_ = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen(["osascript", "-e", f'display notification "{esc_(message)}" with title "{esc_(title)}"'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- jobs (transfer queue)

import queue  # noqa: E402

JOBS = {}
_job_lock = threading.Lock()
LANES = {"transfer": queue.Queue(), "phone": queue.Queue()}


def new_job(kind, serial, title, spec, lane="transfer"):
    j = {"id": secrets.token_hex(5), "kind": kind, "serial": serial, "title": title, "state": "queued",
         "total": 0, "done": 0, "items_total": 0, "items_done": 0, "current": "", "errors": [],
         "created": time.time(), "started": None, "finished": None, "result": {}, "speed": 0,
         "_spec": spec, "_cancel": False, "_proc": None, "_last": (time.time(), 0)}
    with _job_lock:
        JOBS[j["id"]] = j
        finished = sorted((x for x in JOBS.values() if x["finished"]), key=lambda x: x["finished"])
        for old in finished[:-40]:
            JOBS.pop(old["id"], None)
    LANES[lane].put(j["id"])
    return j


def public_job(j):
    return {k: v for k, v in j.items() if not k.startswith("_")}


def set_progress(j, done):
    now = time.time()
    t0, d0 = j["_last"]
    if now - t0 >= 0.8:
        inst = max(0, done - d0) / (now - t0)
        j["speed"] = inst if not j["speed"] else j["speed"] * 0.6 + inst * 0.4
        j["_last"] = (now, done)
    j["done"] = max(j["done"], min(done, j["total"] or done))


def check_cancel(j):
    if j["_cancel"]:
        raise Cancelled()


def run_proc(j, cmd, on_tick=None, tick=0.6, timeout=6 * 3600):
    out_f = tempfile.TemporaryFile()
    p = subprocess.Popen(cmd, stdout=out_f, stderr=subprocess.STDOUT)
    j["_proc"] = p
    start = time.time()
    try:
        while p.poll() is None:
            if j["_cancel"]:
                p.kill()
                p.wait()
                raise Cancelled()
            if time.time() - start > timeout:
                p.kill()
                raise AdbError("Timed out")
            if on_tick:
                try:
                    on_tick()
                except Exception:
                    pass
            time.sleep(tick)
        out_f.seek(0)
        return p.returncode, out_f.read().decode("utf-8", "replace")
    finally:
        j["_proc"] = None
        out_f.close()


def lane_worker(lane):
    while True:
        jid = LANES[lane].get()
        j = JOBS.get(jid)
        if not j or j["state"] != "queued":
            continue
        j["state"] = "running"
        j["started"] = time.time()
        try:
            RUNNERS[j["kind"]](j)
            ok = j["items_done"] - len(j["errors"])
            j["state"] = "error" if j["errors"] and ok <= 0 else "done"
        except Cancelled:
            j["state"] = "cancelled"
        except Exception as e:  # keep the worker alive whatever happens
            j["errors"].append(["", str(e) or e.__class__.__name__])
            j["state"] = "error"
        j["finished"] = time.time()
        j["current"] = ""
        if j["state"] == "done" and j["total"]:
            j["done"] = j["total"]
        if j["finished"] - j["started"] > 8 and j["state"] in ("done", "error"):
            fails = len(j["errors"])
            notify("Cellar", j["title"] + (" finished" if not fails else f" finished, {fails} failed"))


for _lane in LANES:
    threading.Thread(target=lane_worker, args=(_lane,), daemon=True).start()


def run_pull(j):
    """Phone → Mac. items: [{path, as, policy}] where policy is new | replace | merge."""
    sp, serial = j["_spec"], j["serial"]
    dest = sp["dest"]
    os.makedirs(dest, exist_ok=True)
    items = sp["items"]
    j["items_total"] = len(items)
    sizes = [it["size"] for it in items] if all("size" in it for it in items) else batch_sizes(serial, [it["path"] for it in items])
    j["total"] = sum(sizes)
    base, saved = 0, []
    for it, size in zip(items, sizes):
        check_cancel(j)
        src = it["path"]
        name = it.get("as") or posixpath.basename(src)
        target = os.path.join(dest, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        j["current"] = name
        existed = os.path.exists(target)
        policy = it.get("policy", "new")
        if existed and policy == "replace" and not os.path.isdir(target):
            os.remove(target)
            existed = False
        if existed and policy == "merge" and os.path.isdir(target) and name == posixpath.basename(src):
            cmd = [ADB, "-s", serial, "pull", "-a", src, os.path.dirname(target)]
        else:
            if existed:  # never overwrite silently
                target = os.path.join(os.path.dirname(target), keep_both_name(os.path.basename(target), set(os.listdir(os.path.dirname(target)))))
                existed = False
            cmd = [ADB, "-s", serial, "pull", "-a", src, target]
        pre = local_size(target) if existed else 0
        try:
            rc, out = run_proc(j, cmd, lambda: set_progress(j, base + max(0, local_size(target) - pre)))
        except Cancelled:
            if not existed:
                shutil.rmtree(target, ignore_errors=True) if os.path.isdir(target) else (os.path.exists(target) and os.remove(target))
            raise
        if rc != 0:
            j["errors"].append([name, adb_msg(out)])
        else:
            final = target
            if sp.get("heic") and IS_MAC and target.lower().endswith((".heic", ".heif")):
                jpg = os.path.splitext(target)[0] + ".jpg"
                st = os.stat(target)
                r = subprocess.run(["sips", "-s", "format", "jpeg", target, "--out", jpg], capture_output=True)
                if r.returncode == 0:
                    os.utime(jpg, (st.st_atime, st.st_mtime))
                    os.remove(target)
                    final = jpg
            saved.append(final)
            if sp.get("manifest"):
                backup_mark(sp["manifest"], it["key"], size)
        base += size
        j["items_done"] += 1
        set_progress(j, base)
    j["result"] = {"dest": dest, "saved": saved}


def run_push(j):
    """Mac → phone, from a staging folder filled by the browser."""
    sp, serial = j["_spec"], j["serial"]
    stage = os.path.join(STAGE_ROOT, sp["stage"])
    remote_dir = clean_path(sp["dir"])
    roots = sp["roots"]
    j["items_total"] = len(roots)
    sizes = [local_size(os.path.join(stage, r["name"])) for r in roots]
    j["total"] = sum(sizes)
    base, created = 0, []
    try:
        sh(serial, f"mkdir -p {q(remote_dir)}")
        for r, size in zip(roots, sizes):
            check_cancel(j)
            local = os.path.join(stage, r["name"])
            name = clean_name(r.get("as") or r["name"])
            target = posixpath.join(remote_dir, name)
            j["current"] = name
            policy = r.get("policy", "new")
            existing = stat_names(serial, remote_dir, [name]).get(name)
            if existing and policy == "new":
                name = keep_both_name(name, phone_names(serial, remote_dir), os.path.isdir(local))
                target, existing = posixpath.join(remote_dir, name), None
            merge = existing and existing["dir"] and os.path.isdir(local) and name == r["name"]
            if existing and not merge and policy == "replace":
                sh(serial, f"rm -rf {q(target)}")
                existing = None
            cmd = [ADB, "-s", serial, "push", local, remote_dir if merge else target]
            pre = remote_bytes(serial, target) if existing else 0
            try:
                rc, out = run_proc(j, cmd, lambda: set_progress(j, base + max(0, remote_bytes(serial, target) - pre)), tick=1.0)
            except Cancelled:
                if not existing:
                    sh(serial, f"rm -rf {q(target)}")
                raise
            if rc != 0:
                j["errors"].append([name, adb_msg(out)])
            else:
                created.append(target)
            base += size
            j["items_done"] += 1
            set_progress(j, base)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    j["result"] = {"created": created, "dir": remote_dir}


def run_phoneop(j):
    """Copy or move inside the phone. Instant for moves; copies report progress by size."""
    sp, serial = j["_spec"], j["serial"]
    op, dest = sp["op"], clean_path(sp["dest"])
    items = sp["items"]
    j["items_total"] = len(items)
    sizes = batch_sizes(serial, [it["path"] for it in items]) if op == "copy" else [0] * len(items)
    j["total"] = sum(sizes)
    base, created, moves = 0, [], []
    for it, size in zip(items, sizes):
        check_cancel(j)
        src = clean_path(it["path"])
        name = clean_name(it.get("as") or posixpath.basename(src))
        target = posixpath.join(dest, name)
        j["current"] = name
        if dest == src or dest.startswith(src + "/"):
            j["errors"].append([name, "A folder can't go inside itself."])
            j["items_done"] += 1
            continue
        if op == "move" and target == src:
            j["items_done"] += 1
            continue
        policy = it.get("policy", "new")
        existing = stat_names(serial, dest, [name]).get(name)
        if existing and policy == "new":
            name = keep_both_name(name, phone_names(serial, dest), existing["dir"])
            target, existing = posixpath.join(dest, name), None
        src_is_dir = sh(serial, f"[ -d {q(src)} ] && echo d").strip() == "d"
        if existing and policy == "merge" and existing["dir"] and src_is_dir:
            if op == "copy":
                script = f"cp -rp {q(src)}/. {q(target)}/"
            else:
                script = f"cp -rp {q(src)}/. {q(target)}/ && rm -rf {q(src)}"
        else:
            pre = ""
            if existing:  # replace
                pre = f"rm -rf {q(target)} && "
            script = pre + (f"cp -rp {q(src)} {q(target)}" if op == "copy" else f"mv {q(src)} {q(target)}")
        rc, out = run_proc(j, [ADB, "-s", serial, "shell", script + " 2>&1; echo __rc=$?"],
                           (lambda: set_progress(j, base + remote_bytes(serial, target))) if op == "copy" and size > 50e6 else None, tick=1.0)
        m = re.search(r"__rc=(\d+)", out)
        if not m or m.group(1) != "0":
            j["errors"].append([name, adb_msg(out.split("__rc=")[0] or out)])
        else:
            created.append(target)
            if op == "move":
                moves.append({"from": src, "to": target})
        base += size
        j["items_done"] += 1
        set_progress(j, base)
    j["result"] = {"created": created, "moves": moves, "op": op, "dest": dest}


def run_install(j):
    sp, serial = j["_spec"], j["serial"]
    stage = os.path.join(STAGE_ROOT, sp["stage"])
    try:
        apks = [os.path.join(stage, n) for n in sorted(os.listdir(stage)) if n.lower().endswith(".apk")]
        j["items_total"] = len(apks)
        for apk in apks:
            check_cancel(j)
            j["current"] = os.path.basename(apk)
            rc, out = run_proc(j, [ADB, "-s", serial, "install", "-r", apk])
            if rc != 0 or "Success" not in out:
                msg = re.search(r"Failure \[([^\]]+)\]", out)
                j["errors"].append([os.path.basename(apk), msg.group(1) if msg else adb_msg(out)])
            j["items_done"] += 1
    finally:
        shutil.rmtree(stage, ignore_errors=True)


RUNNERS = {"pull": run_pull, "push": run_push, "phoneop": run_phoneop, "install": run_install}


def stage_path(stage_id, rel):
    if not re.fullmatch(r"[0-9a-f]{8,32}", stage_id or ""):
        raise AdbError("Bad upload id")
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise AdbError("Invalid file name")
    path = os.path.join(STAGE_ROOT, stage_id, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


# ---------------------------------------------------------------- rename, new folder, trash

_trash_lock = threading.Lock()


def phone_rename(serial, path, new_name):
    path = clean_path(path)
    new_name = clean_name(new_name)
    parent = posixpath.dirname(path)
    target = posixpath.join(parent, new_name)
    if target == path:
        return {"from": path, "to": path}
    if new_name in stat_names(serial, parent, [new_name]) and new_name.lower() != posixpath.basename(path).lower():
        raise AdbError(f"There's already an item named “{new_name}” here. Choose a different name.")
    out = sh(serial, f"mv {q(path)} {q(target)} 2>&1; echo __rc=$?")
    if "__rc=0" not in out:
        raise AdbError(adb_msg(out.split("__rc=")[0]))
    return {"from": path, "to": target}


def phone_mkdir(serial, folder, name=""):
    folder = clean_path(folder)
    taken = phone_names(serial, folder)
    name = clean_name(name) if name else "untitled folder"
    if name in taken:
        name = keep_both_name(name, taken, True)
    target = posixpath.join(folder, name)
    out = sh(serial, f"mkdir -p {q(target)} 2>&1; echo __rc=$?")
    if "__rc=0" not in out:
        raise AdbError(adb_msg(out.split("__rc=")[0]))
    return {"path": target, "name": name}


_UUID = re.compile(r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}|[0-9A-Fa-f-]{8,36}")


def parse_volumes(sm_out, ls_out=""):
    """SD cards and USB drives from `sm list-volumes public` (fallback: names under /storage)."""
    vols = {}
    for line in sm_out.splitlines():
        m = re.match(r"public:(\d+),\d+\s+(\w+)\s+(\S+)", line.strip())
        if m and m.group(2) == "mounted" and _UUID.fullmatch(m.group(3)):
            # Disk major 179 is an SD card reader; 8 is a USB (SCSI) disk.
            vols[m.group(3)] = "SD card" if m.group(1) == "179" else "USB drive"
    if not vols:
        for name in ls_out.split():
            if _UUID.fullmatch(name) and "-" in name:
                vols[name] = "SD card or USB drive"
    return vols


def list_volumes(serial):
    out = sh(serial, "sm list-volumes public 2>/dev/null; echo __LS__; ls /storage 2>/dev/null; echo __DF__; "
                     "for d in /storage/*-*; do [ -d \"$d\" ] && echo \"$d $(df -k \"$d\" 2>/dev/null | tail -n 1)\"; done; true")
    sm_out, _, rest = out.partition("__LS__")
    ls_out, _, df_out = rest.partition("__DF__")
    vols = parse_volumes(sm_out, ls_out)
    sizes = {}
    for line in df_out.splitlines():
        c = line.split()   # "<path> <filesystem> <total> <used> <free> …" in 1K blocks
        try:
            sizes[c[0]] = {"total": int(c[2]) * 1024, "used": int(c[3]) * 1024, "free": int(c[4]) * 1024}
        except (IndexError, ValueError):
            pass
    res = []
    for uuid, kind in sorted(vols.items()):
        path = f"/storage/{uuid}"
        res.append({"id": uuid, "path": path, "name": kind, "storage": sizes.get(path)})
    if len(res) > 1:  # "SD card", "SD card 2"
        seen = {}
        for v in res:
            seen[v["name"]] = seen.get(v["name"], 0) + 1
            if seen[v["name"]] > 1:
                v["name"] += f" {seen[v['name']]}"
    return res


def storage_roots(serial):
    return [HOME_DIR] + [v["path"] for v in list_volumes(serial)]


def root_of(path, roots):
    for r in roots:
        if path == r or path.startswith(r + "/"):
            return r
    return HOME_DIR


def trash_dir(root):
    return root + "/.CellarTrash"


def trash_read(serial, root=HOME_DIR):
    out = sh(serial, f"cat {q(trash_dir(root) + '/.index')} 2>/dev/null")
    entries = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
            if isinstance(e, dict) and "id" in e:
                entries.append(e)
        except ValueError:
            pass
    return entries


def trash_write(serial, entries, root=HOME_DIR):
    fd, tmp = tempfile.mkstemp()
    with os.fdopen(fd, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    try:
        adb(serial, "push", tmp, trash_dir(root) + "/.index", timeout=30)
    finally:
        os.unlink(tmp)


def phone_trash(serial, paths):
    """Each drive keeps its own Trash, so moving to it never copies data between drives."""
    with _trash_lock:
        paths = [clean_path(p) for p in paths]
        roots = storage_roots(serial)
        for p in paths:
            if p in roots or any(p.startswith(trash_dir(r)) for r in roots):
                raise AdbError("That item can't be moved to the Trash.")
        by_root = {}
        for p in paths:
            by_root.setdefault(root_of(p, roots), []).append(p)
        all_moved = []
        for root, group in by_root.items():
            entries = trash_read(serial, root)
            td = trash_dir(root)
            sh(serial, f"mkdir -p {q(td)} && touch {q(td + '/.nomedia')}")
            moved, script = [], []
            for p in group:
                tid = f"{int(time.time() * 1000)}{secrets.token_hex(2)}"
                name = posixpath.basename(p)
                script.append(f"mv {q(p)} {q(td + '/' + tid + '__' + name)} && echo ok:{tid}")
                moved.append({"id": tid, "name": name, "orig": p, "time": int(time.time())})
            out = sh(serial, "; ".join(script) + "; true", timeout=300)
            ok_ids = set(re.findall(r"ok:(\w+)", out))
            moved = [m for m in moved if m["id"] in ok_ids]
            trash_write(serial, entries + moved, root)
            all_moved += moved
        return {"items": all_moved, "failed": len(paths) - len(all_moved)}


def phone_untrash(serial, ids):
    with _trash_lock:
        restored = []
        for root in storage_roots(serial):
            entries = trash_read(serial, root)
            if not any(e["id"] in ids for e in entries):
                continue
            td = trash_dir(root)
            keep = []
            for e in entries:
                if e["id"] not in ids:
                    keep.append(e)
                    continue
                parent = posixpath.dirname(e["orig"])
                sh(serial, f"mkdir -p {q(parent)}")
                name = e["name"]
                if name in stat_names(serial, parent, [name]):
                    name = keep_both_name(name, phone_names(serial, parent))
                target = posixpath.join(parent, name)
                out = sh(serial, f"mv {q(td + '/' + e['id'] + '__' + e['name'])} {q(target)} 2>&1; echo __rc=$?")
                if "__rc=0" in out:
                    restored.append(target)
                else:
                    keep.append(e)
            trash_write(serial, keep, root)
        return {"restored": restored}


def phone_trash_list(serial):
    out = []
    for root in storage_roots(serial):
        entries = {e["id"]: e for e in trash_read(serial, root)}
        if not entries:
            continue
        try:
            listing = list_dir(serial, trash_dir(root))["entries"]
        except AdbError:
            listing = []
        for item in listing:
            tid, _, name = item["name"].partition("__")
            e = entries.get(tid)
            if not e:
                continue
            out.append({"id": tid, "name": e["name"], "orig": e["orig"], "time": e["time"], "dir": item["dir"], "size": item["size"]})
    return sorted(out, key=lambda x: -x["time"])


def phone_trash_empty(serial, ids=None, older_than=None):
    with _trash_lock:
        removed = 0
        for root in storage_roots(serial):
            entries = trash_read(serial, root)
            drop = [e for e in entries if (ids is None or e["id"] in ids) and (older_than is None or e["time"] < older_than)]
            if not drop:
                continue
            td = trash_dir(root)
            sh(serial, "; ".join(f"rm -rf {q(td + '/' + e['id'] + '__' + e['name'])}" for e in drop) + "; true", timeout=600)
            dropped = {e["id"] for e in drop}
            trash_write(serial, [e for e in entries if e["id"] not in dropped], root)
            removed += len(drop)
        return {"removed": removed}


# ---------------------------------------------------------------- search & recent

def find_stat(serial, script, limit):
    entries = []
    for line in sh(serial, script, timeout=90).splitlines():
        p = line.split("|", 3)
        if len(p) != 4:
            continue
        try:
            path = p[3]
            entries.append({"name": posixpath.basename(path), "path": path, "dir": p[0] == "directory",
                            "size": 0 if p[0] == "directory" else int(p[1]), "mtime": int(p[2])})
        except ValueError:
            pass
        if len(entries) >= limit:
            break
    return entries


def phone_search(serial, text, root=HOME_DIR):
    text = (text or "").strip()
    if len(text) < 2:
        raise AdbError("Type at least 2 characters to search the whole phone.")
    pattern = "*" + re.sub(r"([\\*?\[\]])", r"\\\1", text) + "*"
    root = clean_path(root)
    vol = root_of(root, storage_roots(serial))
    script = (f"find {q(root)} \\( -path {q(vol + '/Android/data')} -o -path {q(vol + '/Android/obb')} "
              f"-o -name '.*' \\) -prune -o -iname {q(pattern)} -exec stat -L -c '%F|%s|%Y|%n' {{}} + 2>/dev/null | head -n 500")
    return {"entries": find_stat(serial, script, 500), "query": text}


def phone_recent(serial, days=14):
    entries = []
    for root in storage_roots(serial):
        script = (f"find {q(root)} \\( -path {q(root + '/Android')} -o -name '.*' \\) -prune -o "
                  f"-type f -mtime -{int(days)} -exec stat -L -c '%F|%s|%Y|%n' {{}} + 2>/dev/null")
        entries += find_stat(serial, script, 5000)
    entries.sort(key=lambda e: -e["mtime"])
    return {"entries": entries[:300]}


# ---------------------------------------------------------------- scans (storage breakdown, duplicates)
# A scan walks the phone in the background. The page starts one, then polls it for progress and the result.

SCANS = {}
_scan_lock = threading.Lock()

TYPE_EXT = {
    "Photos": "jpg jpeg png gif webp heic heif bmp dng raw cr2 nef arw",
    "Videos": "mp4 mov mkv webm avi 3gp m4v mpg mpeg",
    "Audio": "mp3 m4a aac wav flac ogg opus amr mid midi",
    "Documents": "pdf doc docx xls xlsx ppt pptx odt ods odp txt rtf md csv epub vcf ics",
    "Apps": "apk xapk apks aab",
    "Archives": "zip rar 7z tar gz tgz bz2 xz",
}
_EXT_KIND = {e: k for k, v in TYPE_EXT.items() for e in v.split()}
TYPE_ORDER = list(TYPE_EXT) + ["Other"]


def type_of(name):
    return _EXT_KIND.get(os.path.splitext(name)[1].lstrip(".").lower(), "Other")


def start_scan(kind, serial, root, **opts):
    root = clean_path(root or HOME_DIR)
    with _scan_lock:
        for old in [k for k, v in SCANS.items() if v["state"] != "running" and time.time() - v["created"] > 3600]:
            SCANS.pop(old, None)
        sc = {"id": secrets.token_hex(5), "kind": kind, "serial": serial, "root": root, "opts": opts, "state": "running",
              "progress": "Starting…", "result": None, "error": None, "created": time.time(), "_cancel": False}
        SCANS[sc["id"]] = sc

    def work():
        try:
            sc["result"] = SCAN_RUNNERS[kind](sc)
            sc["state"] = "cancelled" if sc["_cancel"] else "done"
        except Cancelled:
            sc["state"] = "cancelled"
        except Exception as e:
            sc["error"], sc["state"] = str(e) or e.__class__.__name__, "error"
    threading.Thread(target=work, daemon=True).start()
    return public_scan(sc)


def public_scan(sc):
    return {k: v for k, v in sc.items() if not k.startswith("_") and k != "serial"}


def scan_check(sc):
    if sc["_cancel"]:
        raise Cancelled()


def scan_find_files(sc, fmt="%s|%Y|%n", extra=""):
    """Every readable file under the scan root (Trash and the protected Android folders left out)."""
    root = sc["root"]
    vol = root_of(root, storage_roots(sc["serial"]))
    script = (f"find {q(root)} \\( -path {q(vol + '/Android/data')} -o -path {q(vol + '/Android/obb')} "
              f"-o -path {q(trash_dir(vol))} \\) -prune -o -type f {extra} -exec stat -L -c {q(fmt)} {{}} + 2>/dev/null")
    out = sh(sc["serial"], script, timeout=900)
    rows = []
    for line in out.splitlines():
        parts = line.split("|", fmt.count("|"))
        if len(parts) == fmt.count("|") + 1 and parts[0].isdigit():
            rows.append(parts)
    return rows


def scan_space(sc):
    """Storage by folder and by file type, plus the biggest files."""
    serial, root = sc["serial"], sc["root"]
    sc["progress"] = "Looking through your files…"
    rows = scan_find_files(sc)
    scan_check(sc)
    sc["progress"] = f"Adding up {len(rows):,} files…"
    types, folders, loose = {}, {}, {"bytes": 0, "count": 0}
    total = 0
    for size, mtime, path in rows:
        size = int(size)
        total += size
        t = types.setdefault(type_of(path), {"bytes": 0, "count": 0})
        t["bytes"] += size
        t["count"] += 1
        rel = path[len(root):].lstrip("/").split("/")
        if len(rel) == 1:
            loose["bytes"] += size
            loose["count"] += 1
            continue
        top = folders.setdefault(rel[0], {"bytes": 0, "count": 0, "kids": {}})
        top["bytes"] += size
        top["count"] += 1
        if len(rel) > 2:
            kid = top["kids"].setdefault(rel[1], {"bytes": 0, "count": 0})
            kid["bytes"] += size
            kid["count"] += 1
    big = sorted(rows, key=lambda r: -int(r[0]))[:100]
    trash_kb = sh(serial, f"du -sk {q(trash_dir(root))} 2>/dev/null | cut -f1").strip()
    return {
        "root": root, "total": total, "files": len(rows), "at": int(time.time()),
        "trash": int(trash_kb) * 1024 if trash_kb.isdigit() else 0,
        "types": [{"type": k, **types[k]} for k in TYPE_ORDER if k in types],
        "folders": [{"name": k, "path": posixpath.join(root, k), **{x: v[x] for x in ("bytes", "count")},
                     "kids": [{"name": n, "path": posixpath.join(root, k, n), **kv}
                              for n, kv in sorted(v["kids"].items(), key=lambda i: -i[1]["bytes"])[:5]]}
                    for k, v in sorted(folders.items(), key=lambda i: -i[1]["bytes"])[:30]],
        "loose": loose,
        "biggest": [{"name": posixpath.basename(p), "path": p, "size": int(sz), "mtime": int(mt), "dir": False, "type": type_of(p)} for sz, mt, p in big],
    }


def _visible_path(p, root):
    return not any(part.startswith(".") for part in p[len(root):].split("/") if part)


def scan_dupes(sc):
    """Same size first (cheap), then a checksum on the phone for files that share a size."""
    serial, root = sc["serial"], sc["root"]
    sc["progress"] = "Looking through your files…"
    rows = [r for r in scan_find_files(sc) if int(r[0]) > 0 and _visible_path(r[2], root)]
    scan_check(sc)
    by_size = {}
    for size, mtime, path in rows:
        by_size.setdefault(int(size), []).append((int(mtime), path))
    cands = {k: v for k, v in by_size.items() if len(v) > 1}
    files = [(k, m, p) for k, v in cands.items() for m, p in v]
    total_bytes = sum(k for k, _, _ in files) or 1
    tool = sh(serial, "command -v md5sum >/dev/null 2>&1 && echo md5sum || echo 'toybox md5sum'").strip() or "md5sum"
    hashes, done_bytes = {}, 0
    batch = []

    def flush():
        nonlocal done_bytes
        if not batch:
            return
        out = sh(serial, f"{tool} " + " ".join(q(p) for _, _, p in batch) + " 2>/dev/null", timeout=1800)
        for line in out.splitlines():
            if len(line) > 34 and re.fullmatch(r"[0-9a-f]{32}", line[:32]):
                hashes[line[34:]] = line[:32]
        done_bytes += sum(k for k, _, _ in batch)
        sc["progress"] = f"Comparing {len(files):,} files that share a size… {int(done_bytes / total_bytes * 100)}%"
        batch.clear()
    for f in sorted(files, key=lambda f: f[2]):
        scan_check(sc)
        batch.append(f)
        if len(batch) >= 40 or sum(k for k, _, _ in batch) > 400_000_000:
            flush()
    flush()
    groups = {}
    for size, mtime, path in files:
        h = hashes.get(path)
        if h:
            groups.setdefault((size, h), []).append({"path": path, "name": posixpath.basename(path), "mtime": mtime, "size": size, "dir": False})
    out = []
    for (size, h), fl in groups.items():
        if len(fl) > 1:
            fl.sort(key=lambda f: (f["mtime"], len(f["path"])))   # oldest first: the likely original
            out.append({"hash": h, "size": size, "type": type_of(fl[0]["name"]), "files": fl, "wasted": size * (len(fl) - 1)})
    out.sort(key=lambda g: -g["wasted"])
    return {"root": root, "at": int(time.time()), "scanned": len(rows), "groups": out[:300], "wasted": sum(g["wasted"] for g in out),
            "unchecked": len(files) - len(hashes) if files else 0}


SCAN_RUNNERS = {"space": scan_space, "dupes": scan_dupes}


# ---------------------------------------------------------------- exports: contacts, call history, calendar (and texts)

def content_query(serial, uri, keys, where=None, sort=None, what="that data"):
    """Runs `content query` on the phone and returns rows as dicts. Explains refusals in plain words."""
    cmd = f"content query --uri {q(uri)} --projection {q(':'.join(keys))}"
    if where:
        cmd += f" --where {q(where)}"
    if sort:
        cmd += f" --sort {q(sort)}"
    out = sh(serial, cmd + " 2>&1", timeout=300)
    if re.search(r"Permission Denial|SecurityException|Error while accessing provider|Unknown URI|inaccessible", out) and not re.search(r"(?m)^Row: ", out):
        raise AdbError(f"This phone won't let Cellar read {what}. Some phones block it for apps and computers. "
                       "On the phone, check Settings › Apps for a permission to allow, or use the phone's own backup app instead.")
    return parse_rows(out, keys)


def parse_rows(out, keys):
    """Parses `Row: N key=value, key=value` text. Values can hold commas and line breaks, so keys are located in order."""
    rows, chunks = [], re.split(r"(?m)^Row: \d+ ", out)[1:]
    for chunk in chunks:
        chunk = chunk.rstrip("\n")
        row, pos = {}, 0
        marks = []
        for i, k in enumerate(keys):
            token = f"{k}=" if i == 0 else f", {k}="
            at = chunk.find(token, pos)
            marks.append(at)
            if at >= 0:
                pos = at + len(token)
        for i, k in enumerate(keys):
            if marks[i] < 0:
                row[k] = ""
                continue
            start = marks[i] + (len(k) + 1 if i == 0 else len(k) + 3)
            nxt = [m for m in marks[i + 1:] if m >= 0]
            val = chunk[start:nxt[0] if nxt else len(chunk)]
            row[k] = "" if val == "NULL" else val
        rows.append(row)
    return rows


def vcard_escape(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def csv_text(header, rows):
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return "﻿" + buf.getvalue()   # BOM so Numbers and Excel read accents correctly


PHONE_TYPES = {"1": "HOME", "2": "CELL", "3": "WORK", "4": "FAX_WORK", "5": "FAX_HOME", "6": "PAGER"}
MAIL_TYPES = {"1": "HOME", "2": "WORK", "3": "OTHER", "4": "CELL"}
CALL_TYPES = {"1": "Incoming", "2": "Outgoing", "3": "Missed", "4": "Voicemail", "5": "Rejected", "6": "Blocked"}


def export_contacts(serial):
    keys = ["raw_contact_id", "display_name", "mimetype", "data1", "data2", "data3"]
    rows = content_query(serial, "content://com.android.contacts/data", keys, what="your contacts")
    people = {}
    for r in rows:
        p = people.setdefault(r["raw_contact_id"], {"name": r["display_name"], "first": "", "last": "", "tel": [], "mail": [], "org": "", "note": "", "adr": []})
        mt = r["mimetype"].rsplit("/", 1)[-1]
        if mt == "name":
            p["first"], p["last"] = r["data2"], r["data3"]
        elif mt == "phone_v2" and r["data1"]:
            p["tel"].append((PHONE_TYPES.get(r["data2"], "VOICE"), r["data1"]))
        elif mt == "email_v2" and r["data1"]:
            p["mail"].append((MAIL_TYPES.get(r["data2"], "OTHER"), r["data1"]))
        elif mt == "organization":
            p["org"] = r["data1"]
        elif mt == "note":
            p["note"] = r["data1"]
        elif mt == "postal-address_v2" and r["data1"]:
            p["adr"].append(r["data1"])
    ppl = [p for p in people.values() if p["name"] or p["tel"] or p["mail"]]
    ppl.sort(key=lambda p: (p["name"] or "").lower())
    v = []
    for p in ppl:
        v += ["BEGIN:VCARD", "VERSION:3.0", f"FN:{vcard_escape(p['name'] or (p['tel'] or [('', '')])[0][1])}",
              f"N:{vcard_escape(p['last'])};{vcard_escape(p['first'])};;;"]
        v += [f"TEL;TYPE={t}:{n}" for t, n in p["tel"]] + [f"EMAIL;TYPE={t}:{e}" for t, e in p["mail"]]
        v += [f"ADR;TYPE=HOME:;;{vcard_escape(a)};;;;" for a in p["adr"]]
        if p["org"]:
            v.append(f"ORG:{vcard_escape(p['org'])}")
        if p["note"]:
            v.append(f"NOTE:{vcard_escape(p['note'])}")
        v.append("END:VCARD")
    csv_rows = [[p["name"], p["first"], p["last"], "; ".join(n for _, n in p["tel"]), "; ".join(e for _, e in p["mail"]), p["org"], p["note"]] for p in ppl]
    return {"contacts.vcf": "\r\n".join(v) + "\r\n" if v else "",
            "contacts.csv": csv_text(["Name", "First name", "Last name", "Phones", "Emails", "Company", "Notes"], csv_rows)}, len(ppl)


def export_calls(serial):
    keys = ["number", "name", "type", "date", "duration"]
    rows = content_query(serial, "content://call_log/calls", keys, sort="date DESC", what="your call history")
    out = []
    for r in rows:
        try:
            when = datetime.datetime.fromtimestamp(int(r["date"]) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = ""
        out.append([when, r["name"], r["number"], CALL_TYPES.get(r["type"], r["type"]), r["duration"]])
    return {"call-history.csv": csv_text(["Date", "Name", "Number", "Type", "Duration (seconds)"], out)}, len(out)


def ics_escape(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def export_calendar(serial):
    keys = ["title", "description", "dtstart", "dtend", "eventLocation", "allDay", "rrule", "duration", "eventTimezone", "deleted"]
    rows = content_query(serial, "content://com.android.calendar/events", keys, what="your calendar")
    utc = lambda ms: datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cellar//Phone export//EN", "CALSCALE:GREGORIAN"]
    n = 0
    for i, r in enumerate(rows):
        if r["deleted"] == "1" or not r["dtstart"].isdigit():
            continue
        n += 1
        ev = ["BEGIN:VEVENT", f"UID:cellar-{i}-{r['dtstart']}@cellar.local", f"DTSTAMP:{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}"]
        if r["allDay"] == "1":
            d0 = utc(r["dtstart"]).date()
            d1 = utc(r["dtend"]).date() if r["dtend"].isdigit() else d0 + datetime.timedelta(days=1)
            ev += [f"DTSTART;VALUE=DATE:{d0:%Y%m%d}", f"DTEND;VALUE=DATE:{d1:%Y%m%d}"]
        else:
            ev.append(f"DTSTART:{utc(r['dtstart']):%Y%m%dT%H%M%SZ}")
            if r["rrule"] and r["duration"]:
                ev.append(f"DURATION:{r['duration']}")
            elif r["dtend"].isdigit():
                ev.append(f"DTEND:{utc(r['dtend']):%Y%m%dT%H%M%SZ}")
        if r["rrule"]:
            ev.append("RRULE:" + r["rrule"])
        ev.append("SUMMARY:" + ics_escape(r["title"] or "(No title)"))
        if r["description"]:
            ev.append("DESCRIPTION:" + ics_escape(r["description"]))
        if r["eventLocation"]:
            ev.append("LOCATION:" + ics_escape(r["eventLocation"]))
        ev.append("END:VEVENT")
        lines += ev
    lines.append("END:VCALENDAR")
    return {"calendar.ics": "\r\n".join(lines) + "\r\n"}, n


EXPORTERS = {"contacts": ("Contacts", export_contacts), "calls": ("Call history", export_calls), "calendar": ("Calendar", export_calendar)}


def export_dir():
    return os.path.join(SAVE_DIR, "Exports", datetime.date.today().isoformat())


def run_exports(serial, what):
    folder = export_dir()
    results = {}
    for key in what:
        if key not in EXPORTERS:
            continue
        label, fn = EXPORTERS[key]
        try:
            files, count = fn(serial)
            os.makedirs(folder, exist_ok=True)
            saved = []
            for name, text in files.items():
                base, ext = os.path.splitext(name)
                final = name if not os.path.exists(os.path.join(folder, name)) else keep_both_name(name, set(os.listdir(folder)))
                with open(os.path.join(folder, final), "w", encoding="utf-8", newline="") as f:
                    f.write(text)
                saved.append(final)
            results[key] = {"label": label, "count": count, "files": saved}
        except AdbError as e:
            results[key] = {"label": label, "error": str(e)}
    return {"folder": folder, "results": results}


# ---------------------------------------------------------------- text messages → CSV or PDF

_msg_cache = {}
SMS_BOX = {"1": "in", "2": "out", "3": "draft", "4": "out", "5": "out", "6": "out"}


def sms_check(serial):
    """Can the computer read texts at all? Some phones refuse. Returns {ok, reason}."""
    try:
        content_query(serial, "content://sms", ["_id"], where="_id=-1", what="your text messages")
        return {"ok": True}
    except AdbError as e:
        return {"ok": False, "reason": str(e).replace("This phone won't let Cellar read your text messages.",
                "This phone doesn't let Cellar read text messages.") + " Your phone's own messaging app may offer a backup or export instead."}


def norm_number(n):
    d = re.sub(r"\D", "", n or "")
    return d[-9:] if len(d) >= 7 else (n or "").strip().lower()


def contact_names(serial):
    try:
        rows = content_query(serial, "content://com.android.contacts/data", ["display_name", "mimetype", "data1"], what="your contacts")
    except AdbError:
        return {}
    return {norm_number(r["data1"]): r["display_name"] for r in rows if r["mimetype"].endswith("phone_v2") and r["data1"]}


def fetch_messages(serial, fresh=False):
    c = _msg_cache.get(serial)
    if c and not fresh and time.time() - c["at"] < 300:
        return c
    rows = content_query(serial, "content://sms", ["_id", "address", "date", "type", "body", "thread_id"], sort="date ASC", what="your text messages")
    names = contact_names(serial)
    msgs = [{"when": int(r["date"] or 0), "number": r["address"], "dir": SMS_BOX.get(r["type"], "in"), "body": r["body"], "kind": "SMS"}
            for r in rows if r["date"].isdigit()]
    note = ""
    try:  # picture messages: keep their text parts; the pictures themselves are not exported
        mms = content_query(serial, "content://mms", ["_id", "date", "msg_box"], what="picture messages")
        if mms:
            parts = {}
            for p in content_query(serial, "content://mms/part", ["mid", "text"], where="ct='text/plain'", what="picture messages"):
                parts.setdefault(p["mid"], []).append(p["text"])
            addrs = {}
            for a in content_query(serial, "content://mms/addr", ["msg_id", "address", "type"], what="picture messages"):
                addrs.setdefault(a["msg_id"], {})[a["type"]] = a["address"]
            for m in mms:
                box = SMS_BOX.get(m["msg_box"], "in")
                a = addrs.get(m["_id"], {})
                number = a.get("137" if box == "in" else "151") or next(iter(a.values()), "")
                text = "\n".join(parts.get(m["_id"], [])) or "(picture or other attachment)"
                if m["date"].isdigit():
                    msgs.append({"when": int(m["date"]) * 1000, "number": number, "dir": box, "body": text, "kind": "MMS"})
            note = "Pictures and attachments in picture messages aren't included, only their text."
    except AdbError:
        note = "Picture messages couldn't be read, so only text messages are included."
    msgs.sort(key=lambda m: m["when"])
    for m in msgs:
        m["key"] = norm_number(m["number"])
        m["name"] = names.get(m["key"], "")
    _msg_cache[serial] = c = {"at": time.time(), "msgs": msgs, "note": note}
    return c


def sms_threads(serial):
    c = fetch_messages(serial, fresh=True)
    th = {}
    for m in c["msgs"]:
        t = th.setdefault(m["key"], {"key": m["key"], "name": m["name"], "number": m["number"], "count": 0, "last": 0})
        t["count"] += 1
        t["last"] = max(t["last"], m["when"])
    return {"threads": sorted(th.values(), key=lambda t: -t["last"]), "total": len(c["msgs"]), "note": c["note"]}


def fmt_when(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def sms_html(msgs, title):
    from html import escape
    by = {}
    for m in msgs:
        by.setdefault(m["key"], []).append(m)
    out = ["<!doctype html><meta charset=utf-8><title>%s</title><style>" % escape(title),
           "body{font:13px/1.45 -apple-system,Helvetica,Arial,sans-serif;color:#18181b;margin:0 auto;max-width:640px;padding:24px}",
           "h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:26px 0 8px;padding-bottom:4px;border-bottom:1px solid #d4d4d8;break-after:avoid}",
           ".sub{color:#52525b;margin:0 0 12px}.day{text-align:center;color:#52525b;font-size:11px;margin:12px 0 4px;break-after:avoid}",
           ".m{max-width:75%;margin:4px 0;padding:7px 11px;border-radius:14px;white-space:pre-wrap;word-break:break-word;break-inside:avoid;border:1px solid #d4d4d8}",
           ".in{background:#f4f4f5;margin-right:auto}.out{background:#e4e4e7;margin-left:auto;text-align:left}",
           ".t{display:block;color:#52525b;font-size:10.5px;margin-top:2px}</style>",
           "<h1>%s</h1><p class=sub>%d messages · exported %s</p>" % (escape(title), len(msgs), datetime.date.today().isoformat())]
    for key, ms in sorted(by.items(), key=lambda kv: -kv[1][-1]["when"]):
        who = ms[0]["name"] or ms[0]["number"] or "Unknown"
        out.append("<h2>%s%s</h2>" % (escape(who), (" · " + escape(ms[0]["number"])) if ms[0]["name"] and ms[0]["number"] else ""))
        day = ""
        for m in ms:
            d = datetime.datetime.fromtimestamp(m["when"] / 1000).strftime("%A %d %B %Y")
            if d != day:
                out.append("<div class=day>%s</div>" % d)
                day = d
            out.append("<div class='m %s'>%s<span class=t>%s%s</span></div>" % (
                "out" if m["dir"] == "out" else "in", escape(m["body"]), datetime.datetime.fromtimestamp(m["when"] / 1000).strftime("%H:%M"),
                " · draft" if m["dir"] == "draft" else ""))
    return "\n".join(out)


def find_pdf_browser():
    cands = [os.environ.get("CELLAR_CHROME", ""), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Chromium.app/Contents/MacOS/Chromium", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
             "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", "/opt/pw-browsers/chromium"]
    cands += [shutil.which(n) or "" for n in ("google-chrome", "chromium", "chromium-browser")]
    return next((c for c in cands if c and os.access(c, os.X_OK)), None)


def html_to_pdf(html_path, pdf_path):
    """Chrome-family browser first (best result), then macOS cupsfilter. Returns True when a PDF was written."""
    browser = find_pdf_browser()
    if browser:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.append("--no-sandbox")
        try:
            r = subprocess.run(cmd + ["file://" + urllib.parse.quote(html_path)], capture_output=True, timeout=120)
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    if IS_MAC and shutil.which("cupsfilter"):
        try:
            r = subprocess.run(["cupsfilter", "-m", "application/pdf", html_path], capture_output=True, timeout=120)
            if r.returncode == 0 and r.stdout.startswith(b"%PDF"):
                with open(pdf_path, "wb") as f:
                    f.write(r.stdout)
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False


def sms_export(serial, fmt, keys):
    c = fetch_messages(serial)
    msgs = [m for m in c["msgs"] if keys is None or m["key"] in keys]
    if not msgs:
        raise AdbError("There are no messages to export.")
    folder = os.path.join(export_dir(), "Messages")
    os.makedirs(folder, exist_ok=True)
    pick = lambda name: name if not os.path.exists(os.path.join(folder, name)) else keep_both_name(name, set(os.listdir(folder)))
    files, note = [], c["note"]
    if fmt in ("csv", "both"):
        name = pick("messages.csv")
        rows = [[fmt_when(m["when"]), m["name"] or m["number"], {"in": "Received", "out": "Sent", "draft": "Draft"}.get(m["dir"], m["dir"]), m["name"], m["number"], m["body"], m["kind"]] for m in msgs]
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as f:
            f.write(csv_text(["Date", "Conversation", "Direction", "Name", "Number", "Message", "Type"], rows))
        files.append(name)
    if fmt in ("pdf", "both"):
        html_name = pick("messages.html")
        html_path = os.path.join(folder, html_name)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(sms_html(msgs, "Text messages"))
        pdf_name = pick("messages.pdf")
        if html_to_pdf(html_path, os.path.join(folder, pdf_name)):
            os.remove(html_path)
            files.append(pdf_name)
        else:
            files.append(html_name)
            note = ("Cellar couldn't make a PDF here (it needs Google Chrome, Edge or Brave installed). Open the saved web page, then choose "
                    "File › Print › Save as PDF. " + note).strip()
    return {"folder": folder, "files": files, "count": len(msgs), "note": note}


# ---------------------------------------------------------------- extras: ring my phone, media keys, Do Not Disturb

MEDIA_KEYS = {"playpause": 85, "next": 87, "previous": 88, "stop": 86, "volup": 24, "voldown": 25, "mute": 164}
DND_MODES = {"off": "0", "priority": "1", "none": "2", "alarms": "3"}   # `cmd notification set_dnd` word -> zen_mode value
DND_WORD = {"off": "off", "priority": "priority", "none": "none", "alarms": "alarms"}
RING_LABEL = "Cellar: finding your phone"


def dnd_state(serial):
    out = sh(serial, "settings get global zen_mode 2>/dev/null").strip()
    return next((k for k, v in DND_MODES.items() if v == out), None)


def extras_info(serial):
    clock = sh(serial, "cmd package resolve-activity --brief -a android.intent.action.SET_ALARM 2>&1")
    can_ring = bool(clock.strip()) and "No activity found" not in clock and "Exception" not in clock and "Error" not in clock
    return {"dnd": dnd_state(serial), "can_ring": can_ring, "media_keys": list(MEDIA_KEYS)}


def media_key(serial, key):
    if key not in MEDIA_KEYS:
        raise AdbError("Unknown key")
    sh(serial, f"input keyevent {MEDIA_KEYS[key]}", check=True)
    return {"ok": True}


def set_dnd(serial, mode):
    if mode not in DND_MODES:
        raise AdbError("Unknown Do Not Disturb setting")
    out = sh(serial, f"cmd notification set_dnd {DND_WORD[mode]} 2>&1")
    now = dnd_state(serial)
    if now != mode:
        raise AdbError("This phone didn't change Do Not Disturb. Some phones only allow it from Settings › Sound › Do Not Disturb."
                       + (" (" + adb_msg(out)[:120] + ")" if out.strip() else ""))
    return {"dnd": now}


def ring_phone(serial):
    """Sets a one-time alarm for the next minute at full alarm volume. Alarms ring even when the phone is on silent."""
    if not extras_info(serial)["can_ring"]:
        raise AdbError("This phone has no Clock app that Cellar can use to ring it. Use Google’s Find My Device instead.")
    hhmm = sh(serial, "date +%H:%M").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm)
    if not m:
        raise AdbError("Couldn't read the time on the phone.")
    total = (int(m.group(1)) * 60 + int(m.group(2)) + 1) % 1440
    hour, minute = divmod(total, 60)
    sh(serial, "cmd media_session volume --stream 4 --set 15 2>/dev/null || cmd media_session volume --stream 4 --set 7 2>/dev/null; true")
    # Phones with two Clock apps (e.g. Samsung + Google) would show a chooser, and SKIP_UI then sets nothing.
    # So aim at one Clock app by package name.
    pkgs = re.findall(r"^\s+([a-z][\w.]+)/\S+", sh(serial, "pm query-activities --brief -a android.intent.action.SET_ALARM 2>&1"), re.M)
    target = f"-p {pkgs[0]} " if pkgs else ""
    out = sh(serial, f"am start {target}-a android.intent.action.SET_ALARM "
                     f"--ei android.intent.extra.alarm.HOUR {hour} --ei android.intent.extra.alarm.MINUTES {minute} "
                     f"--es android.intent.extra.alarm.MESSAGE {q(RING_LABEL)} --ez android.intent.extra.alarm.SKIP_UI true "
                     "--ez android.intent.extra.alarm.VIBRATE true 2>&1")
    if re.search(r"Error|Exception|not started", out):
        raise AdbError("The phone's Clock app refused. " + adb_msg(out)[:140])
    return {"at": f"{hour:02d}:{minute:02d}"}


# ---------------------------------------------------------------- two-way folder sync
# A pair is one Mac folder and one phone folder. A manifest remembers each file's size and modified time on both
# sides as of the last sync, so Cellar can tell "changed on the Mac", "changed on the phone" and "changed on both".
#   - Changed on one side: copied to the other side.
#   - Changed on both sides: a conflict. The newer file keeps the name; the older one is kept next to it as
#     "name (conflict DATE).ext" on both sides, and the conflict is listed until dismissed.
#   - Deleted on one side: removed from the other side.
#   - Nothing is ever deleted outright. Replaced or removed files on the Mac go to Downloads/Cellar/Sync versions;
#     on the phone they go to the Cellar Trash.

SYNC_DIR = os.path.join(SUPPORT_DIR, "sync")
SYNC_VERSIONS = os.path.join(SAVE_DIR, "Sync versions")
_sync_lock = threading.Lock()
SYNC_LIST_CAP = 300


def sync_pairs_all():
    return load_cfg().get("sync_pairs", [])


def sync_pair(pid):
    for p in sync_pairs_all():
        if p.get("id") == pid:
            return p
    raise AdbError("That folder pair doesn't exist any more.")


def sync_update_pair(pid, fn):
    def go(d):
        for p in d.get("sync_pairs", []):
            if p.get("id") == pid:
                fn(p)
    update_cfg(go)


def sync_is_busy(pid):
    return any(j["kind"] == "sync" and j["_spec"].get("pair") == pid and j["state"] in ("queued", "running") for j in list(JOBS.values()))


def sync_public(p):
    d = {k: p.get(k) for k in ("id", "name", "mac", "phone", "auto", "confirmed", "last", "conflicts", "last_error")}
    d["busy"] = sync_is_busy(p["id"])
    return d


def sync_create(serial, mac, phone, name="", auto=False):
    mac = os.path.abspath(os.path.expanduser(mac or ""))
    home = os.path.expanduser("~")
    if not os.path.isdir(mac):
        raise AdbError("That folder on your Mac doesn't exist. Choose a folder that's already there.")
    if mac in ("/", home) or mac.count("/") < 2 or mac.startswith(SYNC_VERSIONS):
        raise AdbError("Choose a more specific folder than that. Syncing a whole home folder or disk isn't allowed.")
    phone = clean_path(phone or "")
    roots = storage_roots(serial)
    if phone in roots or not any(phone.startswith(r + "/") for r in roots):
        raise AdbError("Choose a folder on the phone, not the whole storage.")
    if sh(serial, f"[ -d {q(phone)} ] && echo yes").strip() != "yes":
        raise AdbError("That folder doesn't exist on the phone.")
    hw = hw_id(serial)
    for p in sync_pairs_all():
        if p.get("hw") == hw and p["mac"] == mac and p["phone"] == phone:
            raise AdbError("These two folders are already paired.")
    pair = {"id": secrets.token_hex(4), "hw": hw, "mac": mac, "phone": phone, "name": (name or "").strip() or os.path.basename(mac),
            "auto": bool(auto), "confirmed": False, "last": None, "conflicts": [], "last_error": None}
    update_cfg(lambda d: d.setdefault("sync_pairs", []).append(pair))
    return pair


def sync_manifest_path(pid):
    return os.path.join(SYNC_DIR, pid + ".json")


def sync_manifest_load(pid):
    try:
        with open(sync_manifest_path(pid)) as f:
            d = json.load(f)
        return d.get("files", {})
    except (OSError, ValueError):
        return {}


def sync_manifest_save(pid, files):
    os.makedirs(SYNC_DIR, exist_ok=True)
    tmp = sync_manifest_path(pid) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"files": files, "at": int(time.time())}, f)
    os.replace(tmp, sync_manifest_path(pid))


def _hidden(rel):
    return any(part.startswith(".") for part in rel.split("/"))


def sync_scan_mac(folder):
    out = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for n in files:
            if n.startswith("."):
                continue
            path = os.path.join(root, n)
            try:
                if os.path.islink(path) or not os.path.isfile(path):
                    continue
                st = os.stat(path)
            except OSError:
                continue
            out[os.path.relpath(path, folder).replace(os.sep, "/")] = (st.st_size, int(st.st_mtime))
    return out


def sync_scan_phone(serial, folder):
    script = f"find {q(folder)} -type f -exec stat -L -c '%s|%Y|%n' {{}} + 2>/dev/null"
    out = {}
    for line in sh(serial, script, timeout=600).splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[2].startswith(folder + "/"):
            rel = parts[2][len(folder) + 1:]
            if not _hidden(rel):
                out[rel] = (int(parts[0]), int(parts[1]))
    return out


def phone_md5(serial, paths):
    tool = sh(serial, "command -v md5sum >/dev/null 2>&1 && echo md5sum || echo 'toybox md5sum'").strip() or "md5sum"
    res = {}
    for i in range(0, len(paths), 40):
        out = sh(serial, f"{tool} " + " ".join(q(p) for p in paths[i:i + 40]) + " 2>/dev/null", timeout=1800)
        for line in out.splitlines():
            if len(line) > 34 and re.fullmatch(r"[0-9a-f]{32}", line[:32]):
                res[line[34:]] = line[:32]
    return res


def mac_md5(path):
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_plan(serial, pair):
    """Works out what a sync would do, without changing anything."""
    mac, phone = sync_scan_mac(pair["mac"]), sync_scan_phone(serial, pair["phone"])
    man = sync_manifest_load(pair["id"])
    items, same, skipped, maybe = [], [], [], []
    lower = {}
    for rel in phone:
        lower.setdefault(rel.lower(), []).append(rel)
    clash = {r for v in lower.values() if len(v) > 1 for r in v}

    def item(op, rel, size=0, **kw):
        items.append({"op": op, "rel": rel, "size": size, **kw})
    for rel in sorted(set(mac) | set(phone) | set(man)):
        if rel in clash:
            skipped.append({"rel": rel, "why": "Another file on the phone differs only by capital letters, which the Mac can't tell apart."})
            continue
        m, p, b = mac.get(rel), phone.get(rel), man.get(rel)
        if m and p:
            cm = not b or m != (b["ms"], b["mm"])
            cp = not b or p != (b["ps"], b["pm"])
            if not cm and not cp:
                same.append(rel)
            elif cm and not cp:
                item("push", rel, m[0], update=True)
            elif cp and not cm:
                item("pull", rel, p[0], update=True)
            elif m[0] == p[0]:
                maybe.append(rel)    # same size on both sides: compare contents before calling it a conflict
            else:
                item("conflict", rel, max(m[0], p[0]), winner="mac" if m[1] >= p[1] else "phone", mac_mtime=m[1], phone_mtime=p[1])
        elif m:
            if b and m == (b["ms"], b["mm"]):
                item("rm_mac", rel, m[0])
            else:
                item("push", rel, m[0], update=False)
        elif p:
            if b and p == (b["ps"], b["pm"]):
                item("rm_phone", rel, p[0])
            else:
                item("pull", rel, p[0], update=False)
    if maybe:
        ph = phone_md5(serial, [posixpath.join(pair["phone"], r) for r in maybe])
        for rel in maybe:
            if ph.get(posixpath.join(pair["phone"], rel)) == mac_md5(os.path.join(pair["mac"], rel)):
                same.append(rel)
            else:
                m, p = mac[rel], phone[rel]
                item("conflict", rel, max(m[0], p[0]), winner="mac" if m[1] >= p[1] else "phone", mac_mtime=m[1], phone_mtime=p[1])
    counts = {}
    for it in items:
        counts[it["op"]] = counts.get(it["op"], 0) + 1
    removals = counts.get("rm_mac", 0) + counts.get("rm_phone", 0)
    risky = removals > max(10, len(man) // 2)
    return {"items": items, "same": same, "skipped": skipped, "counts": counts, "risky": risky,
            "bytes": sum(i["size"] for i in items if i["op"] in ("push", "pull", "conflict")), "_mac": mac, "_phone": phone}


def sync_preview(serial, pid):
    pair = sync_pair(pid)
    plan = sync_plan(serial, pair)
    return {"pair": sync_public(pair), "counts": plan["counts"], "in_sync": len(plan["same"]), "skipped": plan["skipped"][:50],
            "risky": plan["risky"], "bytes": plan["bytes"], "total": len(plan["items"]),
            "items": plan["items"][:SYNC_LIST_CAP], "more": max(0, len(plan["items"]) - SYNC_LIST_CAP)}


def conflict_name(rel, stamp, taken):
    d, n = posixpath.split(rel)
    base, ext = os.path.splitext(n)
    cand, i = f"{base} (conflict {stamp}){ext}", 2
    while posixpath.join(d, cand) in taken:
        cand, i = f"{base} (conflict {stamp} {i}){ext}", i + 1
    taken.add(posixpath.join(d, cand))
    return posixpath.join(d, cand)


def sync_version_dest(pair, rel, stamp):
    safe = re.sub(r"[/:\\]", "-", pair["name"]).strip(" .") or "folder"
    return os.path.join(SYNC_VERSIONS, safe, stamp, *rel.split("/"))


def run_sync(j):
    sp, serial = j["_spec"], j["serial"]
    pair = sync_pair(sp["pair"])
    stamp = time.strftime("%Y-%m-%d %H%M%S")
    cstamp = time.strftime("%Y-%m-%d %H%M")
    mac_root, ph_root = pair["mac"], pair["phone"]
    plan = sync_plan(serial, pair)
    items = plan["items"]
    j["items_total"], j["total"] = len(items), plan["bytes"]
    mp = lambda rel: os.path.join(mac_root, *rel.split("/"))
    pp = lambda rel: posixpath.join(ph_root, rel)
    taken = set(plan["_mac"]) | set(plan["_phone"])
    done_ok, failed, stats = set(), set(), {"push": 0, "pull": 0, "conflict": 0, "rm_mac": 0, "rm_phone": 0}
    conflicts, moved = [], 0

    def fail(rel, msg):
        j["errors"].append([rel, msg])
        failed.add(rel)

    def push(rel, dst_rel=None, src_rel=None):
        dst = pp(dst_rel or rel)
        sh(serial, f"mkdir -p {q(posixpath.dirname(dst))}")
        rc, out = run_proc(j, [ADB, "-s", serial, "push", mp(src_rel or rel), dst])
        if rc != 0:
            raise AdbError(adb_msg(out))

    def pull(rel, dst_rel=None, src_rel=None):
        dst = mp(dst_rel or rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        rc, out = run_proc(j, [ADB, "-s", serial, "pull", "-a", pp(src_rel or rel), dst])
        if rc != 0:
            raise AdbError(adb_msg(out))

    def to_versions(rel):
        dest = sync_version_dest(pair, rel, stamp)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(mp(rel), dest)

    base = 0
    # Phone files that are about to be replaced or removed go to the phone's Trash first, in one batch.
    trash_first = [pp(i["rel"]) for i in items if (i["op"] == "push" and i.get("update")) or i["op"] == "rm_phone" or (i["op"] == "conflict" and i["winner"] == "mac")]
    if trash_first:
        phone_trash(serial, trash_first)
    for it in items:
        check_cancel(j)
        rel, op = it["rel"], it["op"]
        j["current"] = rel
        try:
            if op == "push":
                push(rel)
            elif op == "pull":
                if it.get("update"):
                    to_versions(rel)
                pull(rel)
            elif op == "rm_mac":
                to_versions(rel)
            elif op == "rm_phone":
                pass   # already in the phone's Trash
            elif op == "conflict":
                cname = conflict_name(rel, cstamp, taken)
                if it["winner"] == "mac":   # keep the phone's older file as the conflict copy on both sides
                    # the phone original is already in the Trash, so restore it from there under the conflict name
                    entry = next((e for e in reversed(trash_read(serial, root_of(ph_root, storage_roots(serial)))) if e["orig"] == pp(rel)), None)
                    if not entry:
                        raise AdbError("Couldn't keep the phone's version.")
                    td = trash_dir(root_of(ph_root, storage_roots(serial)))
                    tmp = os.path.join(tempfile.mkdtemp(), posixpath.basename(cname))
                    rc, out = run_proc(j, [ADB, "-s", serial, "pull", "-a", td + "/" + entry["id"] + "__" + entry["name"], tmp])
                    if rc != 0:
                        raise AdbError(adb_msg(out))
                    os.makedirs(os.path.dirname(mp(cname)), exist_ok=True)
                    shutil.move(tmp, mp(cname))
                    push(rel)
                    push(cname)
                else:                      # keep the Mac's older file as the conflict copy on both sides
                    os.makedirs(os.path.dirname(mp(cname)), exist_ok=True)
                    shutil.copy2(mp(rel), mp(cname))
                    push(cname)
                    pull(rel)
                conflicts.append({"rel": rel, "kept": cname, "newer": it["winner"], "at": int(time.time())})
                done_ok.add(cname)
            done_ok.add(rel)
            stats[op] += 1
        except Cancelled:
            raise
        except (AdbError, OSError) as e:
            fail(rel, str(e))
        base += it["size"] if op in ("push", "pull", "conflict") else 0
        j["items_done"] += 1
        set_progress(j, base)
    # Record what both sides look like now, only for files that are really in step.
    mac_now, ph_now = sync_scan_mac(mac_root), sync_scan_phone(serial, ph_root)
    man = sync_manifest_load(pair["id"])
    for rel in list(man):
        if rel not in mac_now and rel not in ph_now:
            del man[rel]
    for rel in set(plan["same"]) | done_ok:
        if rel in failed:
            continue
        m, p = mac_now.get(rel), ph_now.get(rel)
        if m and p:
            man[rel] = {"ms": m[0], "mm": m[1], "ps": p[0], "pm": p[1]}
        elif rel in man:
            del man[rel]
    sync_manifest_save(pair["id"], man)
    summary = {"pushed": stats["push"], "pulled": stats["pull"], "conflicts": stats["conflict"], "removed_mac": stats["rm_mac"],
               "removed_phone": stats["rm_phone"], "failed": len(failed), "at": int(time.time())}

    def save(p):
        p["last"] = summary
        p["last_error"] = None if not failed else f"{len(failed)} file{'s' if len(failed) != 1 else ''} couldn't be synced."
        p["conflicts"] = (p.get("conflicts") or []) + conflicts
    sync_update_pair(pair["id"], save)
    j["result"] = summary


def sync_start(serial, pid, confirm=False, auto=False):
    pair = sync_pair(pid)
    if pair.get("hw") != hw_id(serial):
        raise AdbError("This folder pair belongs to a different phone.")
    if not pair.get("confirmed") and not confirm:
        raise AdbError("Look over the planned changes first, then choose Sync.")
    with _sync_lock:
        if sync_is_busy(pid):
            raise AdbError("This pair is already syncing.")
        sync_update_pair(pid, lambda p: p.update(confirmed=True))
        return new_job("sync", serial, f"Sync “{pair['name']}”", {"pair": pid})


def _run_sync_wrapper(j):
    try:
        run_sync(j)
    except Cancelled:
        raise
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        sync_update_pair(j["_spec"]["pair"], lambda p: p.update(last_error=msg))
        raise


RUNNERS["sync"] = _run_sync_wrapper


def sync_auto(serial):
    """On connect: sync every confirmed pair that has automatic sync on, unless the plan would remove a lot."""
    hw = hw_id(serial)
    for p in sync_pairs_all():
        if p.get("hw") != hw or not p.get("auto") or not p.get("confirmed"):
            continue
        try:
            plan = sync_plan(serial, p)
            if plan["risky"]:
                notify("Cellar", f"Sync paused for “{p['name']}”: it would remove many files. Open Cellar to review.")
                continue
            if plan["items"]:
                sync_start(serial, p["id"])
        except Exception:
            pass


# ---------------------------------------------------------------- thumbnails

_thumb_sem = threading.Semaphore(3)


def thumb_file(serial, path, mtime, size, px):
    import hashlib
    px = max(64, min(int(px or 360), 2400))
    key = hashlib.sha1(f"{hw_id(serial)}|{path}|{size}|{mtime}|{px}".encode()).hexdigest()
    folder = os.path.join(THUMB_DIR, key[:2])
    jpg, raw = os.path.join(folder, key + ".jpg"), os.path.join(folder, key + ".raw")
    if os.path.exists(jpg):
        return jpg, "image/jpeg"
    if os.path.exists(raw):
        return raw, mimetypes.guess_type(path)[0] or "application/octet-stream"
    os.makedirs(folder, exist_ok=True)
    with _thumb_sem:
        fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(path)[1])
        with os.fdopen(fd, "wb") as f:
            r = subprocess.run([ADB, "-s", serial, "exec-out", f"cat {q(path)}"], stdout=f, stderr=subprocess.DEVNULL, timeout=120)
        if r.returncode != 0 or os.path.getsize(tmp) == 0:
            os.unlink(tmp)
            raise AdbError("Couldn't read that image")
        if IS_MAC:
            r = subprocess.run(["sips", "-Z", str(px), "-s", "format", "jpeg", "-s", "formatOptions", "75", tmp, "--out", jpg],
                               capture_output=True)
            os.unlink(tmp)
            if r.returncode == 0:
                return jpg, "image/jpeg"
            raise AdbError("Couldn't make a preview")
        os.replace(tmp, raw)  # no converter here: serve and cache the original
        return raw, mimetypes.guess_type(path)[0] or "application/octet-stream"


def prune_cache(limit=600 * 1024 * 1024):
    files = []
    for root, _, names in os.walk(THUMB_DIR):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
                files.append((st.st_atime, st.st_size, p))
            except OSError:
                pass
    total = sum(f[1] for f in files)
    for _, sz, p in sorted(files):
        if total <= limit:
            break
        try:
            os.remove(p)
            total -= sz
        except OSError:
            pass


# ---------------------------------------------------------------- camera backup

BACKUP_CANDIDATES = [
    ("Camera", ["DCIM/Camera"]),
    ("Screenshots", ["Pictures/Screenshots", "DCIM/Screenshots"]),
    ("Screen recordings", ["Movies/Screen recordings", "DCIM/Screen recordings"]),
    ("WhatsApp images", ["Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images", "WhatsApp/Media/WhatsApp Images"]),
    ("Downloads", ["Download"]),
]
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".dng", ".mp4", ".mov", ".3gp", ".mkv", ".webm"}


def manifest_path(hw):
    return os.path.join(SUPPORT_DIR, "backup-" + re.sub(r"[^\w.-]", "_", hw) + ".json")


_manifest_lock = threading.Lock()


def backup_mark(hw, key, size):
    with _manifest_lock:
        p = manifest_path(hw)
        try:
            with open(p) as f:
                m = json.load(f)
        except (OSError, ValueError):
            m = {}
        m.setdefault("done", {})[key] = size
        m["last"] = int(time.time())
        os.makedirs(SUPPORT_DIR, exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(m, f)
        os.replace(p + ".tmp", p)


def backup_settings(serial):
    hw = hw_id(serial)
    conf = load_cfg().get("backup", {}).get(hw, {})
    info = device_info(serial)
    model = (f"{info['manufacturer']} {info['model']}".strip() or "Phone").replace("/", "-")
    return hw, {"sources": conf.get("sources", ["Camera"]),
                "dest": conf.get("dest", os.path.expanduser(f"~/Pictures/Cellar/{model}")),
                "heic": conf.get("heic", False), "auto": conf.get("auto", False)}


def backup_save_settings(serial, data):
    hw = hw_id(serial)
    allowed = {c[0] for c in BACKUP_CANDIDATES}
    conf = {"sources": [s for s in data.get("sources", []) if s in allowed],
            "dest": os.path.expanduser(str(data.get("dest") or "~/Pictures/Cellar")),
            "heic": bool(data.get("heic")), "auto": bool(data.get("auto"))}
    update_cfg(lambda d: d.setdefault("backup", {}).__setitem__(hw, conf))
    return conf


def backup_scan(serial):
    hw, conf = backup_settings(serial)
    try:
        with open(manifest_path(hw)) as f:
            man = json.load(f)
    except (OSError, ValueError):
        man = {}
    done = man.get("done", {})
    sources = []
    exist_out = sh(serial, "; ".join(f"[ -d {q(HOME_DIR + '/' + r)} ] && echo {q(r)}" for _, rels in BACKUP_CANDIDATES for r in rels) + "; true")
    present = set(exist_out.splitlines())
    for label, rels in BACKUP_CANDIDATES:
        rel = next((r for r in rels if r in present), None)
        sources.append({"label": label, "path": rel, "on": label in conf["sources"]})
    items = []
    for src in sources:
        if not src["on"] or not src["path"]:
            continue
        root = HOME_DIR + "/" + src["path"]
        script = f"find {q(root)} -name '.*' -prune -o -type f -exec stat -c '%s|%Y|%n' {{}} + 2>/dev/null"
        for line in sh(serial, script, timeout=120).splitlines():
            p = line.split("|", 2)
            if len(p) != 3:
                continue
            path = p[2]
            if os.path.splitext(path)[1].lower() not in MEDIA_EXT and src["label"] != "Downloads":
                continue
            rel = src["label"] + path[len(root):]
            size = int(p[0])
            if done.get(rel) == size:
                continue
            local = os.path.join(conf["dest"], rel)
            if os.path.exists(local) and os.path.getsize(local) == size:
                continue
            if conf["heic"] and local.lower().endswith((".heic", ".heif")) and os.path.exists(os.path.splitext(local)[0] + ".jpg"):
                continue
            items.append({"path": path, "as": rel, "key": rel, "size": size, "mtime": int(p[1])})
    videos = sum(1 for i in items if os.path.splitext(i["path"])[1].lower() in (".mp4", ".mov", ".3gp", ".mkv", ".webm"))
    return {"settings": conf, "sources": sources, "count": len(items), "videos": videos, "photos": len(items) - videos,
            "bytes": sum(i["size"] for i in items), "last": man.get("last"), "_items": items, "hw": hw}


def backup_start(serial):
    scan = backup_scan(serial)
    if not scan["count"]:
        return None
    title = f"Back up {scan['count']} item{'s' if scan['count'] != 1 else ''}"
    return new_job("pull", serial, title, {"dest": scan["settings"]["dest"], "items": scan["_items"],
                                            "heic": scan["settings"]["heic"], "manifest": scan["hw"]})


# ---------------------------------------------------------------- apps

def friendly_app_name(pkg):
    skip = {"com", "org", "net", "android", "app", "apps", "mobile", "client", "messenger", "lite", "prod", "release", "free", "www"}
    parts = [p for p in pkg.split(".") if p.lower() not in skip and not p.isdigit()]
    name = parts[-1] if parts else pkg.split(".")[-1]
    if len(parts) >= 2 and parts[0].lower() in ("google", "samsung", "sec", "microsoft", "facebook"):
        name = parts[-1]
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).replace("_", " ")
    return name[:1].upper() + name[1:]


def list_apps(serial):
    out = sh(serial, "pm list packages -3 -f --show-versioncode 2>/dev/null || pm list packages -3 -f", timeout=60)
    apps = []
    for line in out.splitlines():
        if not line.startswith("package:"):
            continue
        rest = line[8:].strip()
        vc = ""
        m = re.search(r"\s+versionCode:(\d+)$", rest)
        if m:
            vc, rest = m.group(1), rest[:m.start()]
        apk, _, pkg = rest.rpartition("=")
        if pkg:
            apps.append({"pkg": pkg, "apk": apk, "version": vc, "name": friendly_app_name(pkg)})
    sizes = batch_sizes(serial, [a["apk"] for a in apps]) if apps else []
    for a, s in zip(apps, sizes):
        a["size"] = s
    return {"apps": sorted(apps, key=lambda a: a["name"].lower())}


def app_backup(serial, pkg):
    if not re.fullmatch(r"[\w.]+", pkg or ""):
        raise AdbError("Invalid app id")
    paths = [l[8:].strip() for l in sh(serial, f"pm path {q(pkg)}").splitlines() if l.startswith("package:")]
    if not paths:
        raise AdbError("That app isn't installed.")
    dest = os.path.join(SAVE_DIR, "Apps")
    if len(paths) == 1:
        items = [{"path": paths[0], "as": pkg + ".apk"}]
    else:
        items = [{"path": p, "as": f"{pkg}/{posixpath.basename(p)}"} for p in paths]
    return new_job("pull", serial, f"Save {friendly_app_name(pkg)} app", {"dest": dest, "items": items})


# ---------------------------------------------------------------- tools: adb + scrcpy downloads, mirroring

TOOLS_DIR = os.path.join(SUPPORT_DIR, "tools")


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    r = subprocess.run(["curl", "-fsSL", "--retry", "2", "-o", dest, url], capture_output=True, timeout=600)
    if r.returncode != 0:
        raise AdbError("Download failed. Check your internet connection and try again.")


def install_adb():
    global ADB
    import zipfile
    plat = "darwin" if IS_MAC else ("windows" if os.name == "nt" else "linux")
    tmp = os.path.join(TOOLS_DIR, "platform-tools.zip")
    download(f"https://dl.google.com/android/repository/platform-tools-latest-{plat}.zip", tmp)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(TOOLS_DIR)
    os.unlink(tmp)
    for n in ("adb", "fastboot"):
        p = os.path.join(TOOLS_DIR, "platform-tools", n)
        if os.path.exists(p):
            os.chmod(p, 0o755)
    ADB = find_adb()
    if ADB:
        subprocess.run([ADB, "start-server"], capture_output=True)
    return {"adb": ADB}


def find_scrcpy():
    cands = [shutil.which("scrcpy"), "/opt/homebrew/bin/scrcpy", "/usr/local/bin/scrcpy"]
    for root, _, files in os.walk(os.path.join(TOOLS_DIR, "scrcpy")) if os.path.isdir(os.path.join(TOOLS_DIR, "scrcpy")) else []:
        if "scrcpy" in files:
            cands.append(os.path.join(root, "scrcpy"))
    return next((c for c in cands if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def install_scrcpy():
    import platform
    import tarfile
    arch = "aarch64" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    fd, meta = tempfile.mkstemp()
    os.close(fd)
    download("https://api.github.com/repos/Genymobile/scrcpy/releases/latest", meta)
    with open(meta) as f:
        rel = json.load(f)
    os.unlink(meta)
    osname = "macos" if IS_MAC else "linux"
    asset = next((a for a in rel.get("assets", []) if osname in a["name"] and arch in a["name"] and a["name"].endswith(".tar.gz")), None)
    if not asset:
        raise AdbError("No ready-made scrcpy for this Mac. Install it with:  brew install scrcpy")
    tmp = os.path.join(TOOLS_DIR, asset["name"])
    download(asset["browser_download_url"], tmp)
    shutil.rmtree(os.path.join(TOOLS_DIR, "scrcpy"), ignore_errors=True)
    with tarfile.open(tmp) as t:
        t.extractall(os.path.join(TOOLS_DIR, "scrcpy"))
    os.unlink(tmp)
    if IS_MAC:
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", os.path.join(TOOLS_DIR, "scrcpy")], capture_output=True)
    exe = find_scrcpy()
    if not exe:
        raise AdbError("scrcpy downloaded but couldn't be started.")
    return {"scrcpy": exe}


MIRRORS = {}


_scrcpy_ver = {}


def scrcpy_version(exe):
    if exe not in _scrcpy_ver:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"scrcpy\s+(\d+)\.(\d+)", out)
            _scrcpy_ver[exe] = (int(m.group(1)), int(m.group(2))) if m else None
        except (OSError, subprocess.TimeoutExpired):
            _scrcpy_ver[exe] = None
    return _scrcpy_ver[exe]


def android_major(release):
    m = re.match(r"\d+", release or "")
    return int(m.group(0)) if m else 0


def build_mirror_cmd(exe, serial, opts, info, version):
    """The scrcpy command line for a screen or camera window. Raises AdbError with the fix when camera mode can't work."""
    name = f"{info['manufacturer']} {info['model']}".strip() or "Phone"
    camera = opts.get("source") == "camera"
    cmd = [exe, "-s", serial]
    if camera:
        if android_major(info.get("android")) < 12:
            raise AdbError(f"Phone camera needs Android 12 or newer. This phone has Android {info.get('android') or 'unknown'}.")
        if version is not None and version < (2, 2):
            raise AdbError("Your copy of scrcpy is too old for the camera (it needs 2.2 or newer). Update it with “brew upgrade scrcpy”, then try again.")
        facing = opts.get("facing") if opts.get("facing") in ("front", "back", "external") else "back"
        cmd += ["--video-source=camera", f"--camera-facing={facing}", "--no-control", "--window-title", f"{name} camera ({facing})"]
        if opts.get("mic"):
            cmd.append("--audio-source=mic")
        else:
            cmd.append("--no-audio")
    else:
        cmd += ["--window-title", name]
        if opts.get("screen_off"):
            cmd.append("--turn-screen-off")
        if opts.get("stay_awake", True):
            cmd.append("--stay-awake")
        if opts.get("no_audio"):
            cmd.append("--no-audio")
        if opts.get("keyboard") == "uhid":
            cmd.append("--keyboard=uhid")
    if opts.get("record"):
        os.makedirs(SAVE_DIR, exist_ok=True)
        label = "Camera recording" if camera else "Screen recording"
        cmd.append("--record=" + os.path.join(SAVE_DIR, time.strftime(label + " %Y-%m-%d %H.%M.%S.mp4")))
    return cmd


def start_mirror(serial, opts):
    exe = find_scrcpy()
    if not exe:
        raise AdbError("need_scrcpy")
    old = MIRRORS.get(serial)
    if old and old.poll() is None:
        return {"running": True}
    env = dict(os.environ, ADB=ADB or "adb")
    cmd = build_mirror_cmd(exe, serial, opts, device_info(serial), scrcpy_version(exe))
    MIRRORS[serial] = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"running": True}


# ---------------------------------------------------------------- device watcher (auto backup, trash cleanup, Finder)

_seen_hw = set()


def device_watcher():
    while True:
        time.sleep(4)
        if not ADB:
            continue
        try:
            devs = [d for d in list_devices()["devices"] if d["state"] == "device"]
        except Exception:
            continue
        now_hw = {}
        for d in devs:
            try:
                now_hw[hw_id(d["serial"])] = d["serial"]
            except Exception:
                pass
        for hw, serial in now_hw.items():
            if hw in _seen_hw:
                continue
            _seen_hw.add(hw)
            threading.Thread(target=on_connect, args=(serial,), daemon=True).start()
        _seen_hw.intersection_update(now_hw)


def on_connect(serial):
    try:
        phone_trash_empty(serial, older_than=time.time() - TRASH_DAYS * 86400)
    except Exception:
        pass
    settings = load_cfg().get("settings", {})
    try:
        if settings.get("finder_auto"):
            finder_mount(serial)
    except Exception:
        pass
    try:
        sync_auto(serial)
    except Exception:
        pass
    try:
        _, conf = backup_settings(serial)
        if conf["auto"]:
            j = backup_start(serial)
            if j:
                n = len(j["_spec"]["items"])
                notify("Cellar", f"Backing up {n} new photo{'s' if n != 1 else ''} and video{'s' if n != 1 else ''} from your phone")
    except Exception:
        pass


def open_on_mac(serial, path):
    """Open a phone file in its Mac app; changes you save are copied back to the phone."""
    import hashlib
    folder = os.path.join(CACHE_DIR, "open", hashlib.sha1(f"{serial}|{path}".encode()).hexdigest()[:12])
    os.makedirs(folder, exist_ok=True)
    name = posixpath.basename(path)
    local = os.path.join(folder, name)
    adb(serial, "pull", "-a", path, local, timeout=3600)
    if IS_MAC:
        subprocess.Popen(["open", local])
    start_mtime = os.path.getmtime(local)

    def watch():
        last, deadline = start_mtime, time.time() + 6 * 3600
        while time.time() < deadline:
            time.sleep(2)
            try:
                cur = os.path.getmtime(local)
            except OSError:
                continue
            if cur == last:
                continue
            time.sleep(1.5)  # let the app finish writing
            try:
                adb(serial, "push", local, path, timeout=3600)
                last = os.path.getmtime(local)
                notify("Cellar", f"Saved your changes to “{name}” on the phone")
            except Exception:
                notify("Cellar", f"Couldn't save “{name}” back to the phone. Is it still connected?")
                last = cur

    threading.Thread(target=watch, daemon=True).start()
    return {"local": local, "watching": True}


# ---------------------------------------------------------------- Finder integration (WebDAV)
#
# Finder can connect to WebDAV servers natively (Go › Connect to Server) and lists them under
# Locations. That gives real Finder copy/paste, drag both ways and Quick Look without any paid
# Apple developer entitlement. Deleting from Finder moves items to Cellar's Trash.

from email.utils import formatdate  # noqa: E402
from xml.sax.saxutils import escape as xml_escape  # noqa: E402

SERVER_PORT = [8765]
DAV_JUNK = re.compile(r"(^|/)(\._[^/]*|\.DS_Store|\.metadata_never_index[^/]*|\.Spotlight-V100|\.Trashes|\.fseventsd|\.TemporaryItems|\.localized|\.hidden|\.ql_[^/]*|Icon\r)$")
_dav_cache = {}
_dav_cache_lock = threading.Lock()


def dav_volume_name(serial):
    info = device_info(serial)
    name = f"{info['manufacturer']} {info['model']}".strip() or "Android phone"
    return re.sub(r"[^A-Za-z0-9 ._-]", "", name).strip() or "Android phone"


_dav_vol_cache = {}   # serial -> (time, {display name: path})
_dav_vol_names = {}   # drive path -> display name, for building links


def dav_roots(serial):
    """SD cards and USB drives appear as folders at the top of the phone's share, named like the sidebar."""
    hit = _dav_vol_cache.get(serial)
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    try:
        vols = list_volumes(serial)
    except Exception:
        vols = []
    try:
        taken = {e["name"] for e in dav_cached_list(serial, HOME_DIR)}
    except Exception:
        taken = set()
    m = {}
    for v in vols:
        name = v["name"] if v["name"] not in taken else f"{v['name']} ({v['id']})"
        m[name] = v["path"]
        _dav_vol_names[v["path"]] = name
    _dav_vol_cache[serial] = (time.time(), m)
    return m


def dav_serial_for(vol):
    for d in list_devices()["devices"]:
        if d["state"] == "device" and dav_volume_name(d["serial"]) == vol:
            return d["serial"]
    return None


def dav_cached_list(serial, path):
    key = (serial, path)
    with _dav_cache_lock:
        hit = _dav_cache.get(key)
        if hit and time.time() - hit[0] < 3:
            return hit[1]
    entries = list_dir(serial, path)["entries"]
    with _dav_cache_lock:
        _dav_cache[key] = (time.time(), entries)
    return entries


def dav_invalidate(serial, *paths):
    with _dav_cache_lock:
        for p in paths:
            for k in (p, posixpath.dirname(p)):
                _dav_cache.pop((serial, k), None)


def finder_mount(serial):
    vol = dav_volume_name(serial)
    url = f"http://127.0.0.1:{SERVER_PORT[0]}/dav/{urllib.parse.quote(vol)}/"
    if not IS_MAC:
        return {"url": url, "mounted": False, "note": "Finder is only on macOS"}
    if finder_mountpoint(vol):
        subprocess.Popen(["open", finder_mountpoint(vol)])
        return {"url": url, "mounted": True}
    r = subprocess.run(["osascript", "-e", f'mount volume "{url}"'], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AdbError("Finder couldn't connect: " + (r.stderr.strip() or "unknown error"))
    mp = finder_mountpoint(vol)
    if mp:
        subprocess.Popen(["open", mp])
    return {"url": url, "mounted": bool(mp)}


def finder_mountpoint(vol):
    if not IS_MAC:
        return None
    out = subprocess.run(["mount"], capture_output=True, text=True).stdout
    needle = f"127.0.0.1:{SERVER_PORT[0]}/dav/{urllib.parse.quote(vol)}"
    for line in out.splitlines():
        if needle in line or f"127.0.0.1:{SERVER_PORT[0]}/dav/{vol}" in line:
            m = re.search(r" on (.+?) \(", line)
            if m:
                return m.group(1)
    return None


def finder_unmount(serial):
    mp = finder_mountpoint(dav_volume_name(serial))
    if mp:
        subprocess.run(["diskutil", "unmount", mp], capture_output=True, timeout=30)
    return {"mounted": False}


class DavMixin:
    """WebDAV class 1 + fake class 2 locking (Finder mounts read-only without LOCK)."""

    def dav_allowed(self):
        if not self.host_ok():
            return False
        # Browsers always label their requests; Finder and other WebDAV apps don't.
        site = self.headers.get("Sec-Fetch-Site")
        if self.headers.get("Origin") or (site and site not in ("none", "same-origin")):
            return False
        return True

    def dav_resolve(self):
        raw = urllib.parse.urlparse(self.path).path
        parts = [urllib.parse.unquote(p) for p in raw.split("/")[2:]]  # after /dav
        if not parts or not parts[0]:
            return None, None, None, raw
        vol, rest = parts[0], [p for p in parts[1:] if p]
        if ".." in rest:
            return None, None, None, raw
        serial = dav_serial_for(vol)
        base = HOME_DIR
        if serial and rest and rest[0] in dav_roots(serial):
            base, rest = dav_roots(serial)[rest[0]], rest[1:]
        remote = posixpath.join(base, *rest) if rest else base
        return serial, vol, remote, raw

    def dav_href(self, vol, remote, is_dir):
        base = next((r for r in _dav_vol_names if remote == r or remote.startswith(r + "/")), HOME_DIR)
        rel = remote[len(base):].lstrip("/")
        parts = ([_dav_vol_names[base]] if base != HOME_DIR else []) + [p for p in rel.split("/") if p]
        href = "/dav/" + urllib.parse.quote(vol) + "/" + "/".join(urllib.parse.quote(p) for p in parts)
        if is_dir and not href.endswith("/"):
            href += "/"
        return href

    def dav_send(self, code, body=b"", ctype="text/xml; charset=utf-8", extra=None):
        self.send_response(code)
        if body or code not in (204, 304):
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def dav_body_to(self, f):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                line = self.rfile.readline()
                size = int(line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    return
                left = size
                while left:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        raise AdbError("Upload interrupted")
                    f.write(chunk)
                    left -= len(chunk)
                self.rfile.readline()
        left = int(self.headers.get("Content-Length", "0") or 0)
        while left > 0:
            chunk = self.rfile.read(min(CHUNK, left))
            if not chunk:
                raise AdbError("Upload interrupted")
            f.write(chunk)
            left -= len(chunk)

    def dav_drain(self):
        with open(os.devnull, "wb") as f:
            self.dav_body_to(f)

    def dav_prop(self, vol, remote, e, quota=None):
        is_dir = e["dir"]
        props = [f"<D:displayname>{xml_escape(posixpath.basename(remote) or vol)}</D:displayname>",
                 "<D:resourcetype><D:collection/></D:resourcetype>" if is_dir else "<D:resourcetype/>",
                 f"<D:getlastmodified>{formatdate(e['mtime'], usegmt=True)}</D:getlastmodified>",
                 f"<D:creationdate>{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(e['mtime']))}</D:creationdate>",
                 f"<D:getetag>\"{e['size']:x}-{e['mtime']:x}\"</D:getetag>",
                 "<D:supportedlock><D:lockentry><D:lockscope><D:exclusive/></D:lockscope><D:locktype><D:write/></D:locktype></D:lockentry></D:supportedlock>"]
        if not is_dir:
            props.append(f"<D:getcontentlength>{e['size']}</D:getcontentlength>")
            props.append(f"<D:getcontenttype>{xml_escape(mimetypes.guess_type(remote)[0] or 'application/octet-stream')}</D:getcontenttype>")
        if quota:
            props.append(f"<D:quota-available-bytes>{quota['free']}</D:quota-available-bytes><D:quota-used-bytes>{quota['used']}</D:quota-used-bytes>")
        return (f"<D:response><D:href>{xml_escape(self.dav_href(vol, remote, is_dir))}</D:href><D:propstat><D:prop>"
                + "".join(props) + "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>")

    def dav_stat(self, serial, remote):
        if remote == HOME_DIR or remote in dav_roots(serial).values():
            return {"dir": True, "size": 0, "mtime": int(time.time())}
        parent, name = posixpath.split(remote)
        for e in dav_cached_list(serial, parent):
            if e["name"] == name:
                return e
        return None

    def handle_dav(self):
        if not self.dav_allowed():
            return self.dav_send(403, b"Forbidden", "text/plain")
        m = self.command
        if m == "OPTIONS":
            return self.dav_send(200, b"", "text/plain", {"DAV": "1, 2", "MS-Author-Via": "DAV",
                                 "Allow": "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, PROPPATCH, MKCOL, COPY, MOVE, LOCK, UNLOCK"})
        serial, vol, remote, raw = self.dav_resolve()
        if m in ("PUT", "PROPPATCH", "LOCK") and not serial:
            self.dav_drain()
        if not serial:
            if raw.rstrip("/") == "/dav" and m == "PROPFIND":  # list connected phones
                body = '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">'
                body += "<D:response><D:href>/dav/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
                for d in list_devices()["devices"]:
                    if d["state"] == "device":
                        v = dav_volume_name(d["serial"])
                        body += f"<D:response><D:href>/dav/{xml_escape(urllib.parse.quote(v))}/</D:href><D:propstat><D:prop><D:displayname>{xml_escape(v)}</D:displayname><D:resourcetype><D:collection/></D:resourcetype></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
                return self.dav_send(207, (body + "</D:multistatus>").encode())
            return self.dav_send(404, b"Phone not connected", "text/plain")
        junk = bool(DAV_JUNK.search(remote))
        try:
            if m == "PROPFIND":
                if junk:
                    return self.dav_send(404, b"")
                self.dav_drain()
                e = self.dav_stat(serial, remote)
                if not e:
                    return self.dav_send(404, b"")
                depth = self.headers.get("Depth", "1")
                quota = None
                if remote == HOME_DIR:
                    quota = device_info(serial).get("storage")
                elif remote in dav_roots(serial).values():
                    quota = next((v["storage"] for v in list_volumes(serial) if v["path"] == remote), None)
                out = ['<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">', self.dav_prop(vol, remote, e, quota)]
                if e["dir"] and depth != "0":
                    for c in dav_cached_list(serial, remote):
                        if c["name"] == posixpath.basename(TRASH_DIR) and (remote == HOME_DIR or remote in dav_roots(serial).values()):
                            continue
                        out.append(self.dav_prop(vol, posixpath.join(remote, c["name"]), c))
                    if remote == HOME_DIR:
                        for disp, vpath in dav_roots(serial).items():
                            out.append(self.dav_prop(vol, vpath, {"name": disp, "dir": True, "size": 0, "mtime": int(time.time())}))
                out.append("</D:multistatus>")
                return self.dav_send(207, "".join(out).encode())
            if m in ("GET", "HEAD"):
                if junk:
                    return self.dav_send(404, b"")
                e = self.dav_stat(serial, remote)
                if not e:
                    return self.dav_send(404, b"")
                if e["dir"]:
                    return self.dav_send(200, f"<h1>{xml_escape(vol)}</h1><p>Open this in Finder.</p>".encode(), "text/html")
                if m == "HEAD":
                    return self._dav_head(e, remote)
                return self.stream_file(serial, remote, False)
            if m == "PUT":
                if junk:
                    self.dav_drain()
                    return self.dav_send(201, b"")
                existed = self.dav_stat(serial, remote) is not None
                fd, tmp = tempfile.mkstemp(prefix="cellar-dav-")
                try:
                    with os.fdopen(fd, "wb") as f:
                        self.dav_body_to(f)
                    adb(serial, "push", tmp, remote, timeout=6 * 3600)
                finally:
                    os.unlink(tmp)
                dav_invalidate(serial, remote)
                return self.dav_send(204 if existed else 201, b"")
            if m == "MKCOL":
                self.dav_drain()
                if junk:
                    return self.dav_send(403, b"")
                if self.dav_stat(serial, remote):
                    return self.dav_send(405, b"")
                out = sh(serial, f"mkdir {q(remote)} 2>&1; echo __rc=$?")
                dav_invalidate(serial, remote)
                return self.dav_send(201 if "__rc=0" in out else 409, b"")
            if m == "DELETE":
                if junk:
                    return self.dav_send(204, b"")
                if remote == HOME_DIR or remote in dav_roots(serial).values():
                    return self.dav_send(403, b"")
                if not self.dav_stat(serial, remote):
                    return self.dav_send(404, b"")
                phone_trash(serial, [remote])  # recoverable from Cellar's Trash
                dav_invalidate(serial, remote)
                return self.dav_send(204, b"")
            if m in ("MOVE", "COPY"):
                dest_url = urllib.parse.urlparse(self.headers.get("Destination", ""))
                dparts = [urllib.parse.unquote(p) for p in dest_url.path.split("/")[2:]]
                if len(dparts) < 2 or dparts[0] != vol or ".." in dparts:
                    return self.dav_send(502, b"")
                dparts = [p for p in dparts[1:] if p]
                dbase = HOME_DIR
                if dparts and dparts[0] in dav_roots(serial):
                    dbase, dparts = dav_roots(serial)[dparts[0]], dparts[1:]
                dest = posixpath.join(dbase, *dparts)
                if not self.dav_stat(serial, remote):
                    return self.dav_send(404, b"")
                exists = self.dav_stat(serial, dest) is not None
                if exists and self.headers.get("Overwrite", "T").upper() == "F":
                    return self.dav_send(412, b"")
                pre = f"rm -rf {q(dest)} && " if exists else ""
                cmd = f"mv {q(remote)} {q(dest)}" if m == "MOVE" else f"cp -rp {q(remote)} {q(dest)}"
                out = sh(serial, pre + cmd + " 2>&1; echo __rc=$?", timeout=6 * 3600)
                dav_invalidate(serial, remote, dest)
                if "__rc=0" not in out:
                    return self.dav_send(409, b"")
                return self.dav_send(204 if exists else 201, b"")
            if m == "LOCK":
                self.dav_drain()
                token = "opaquelocktoken:" + secrets.token_hex(16)
                body = ('<?xml version="1.0" encoding="utf-8"?><D:prop xmlns:D="DAV:"><D:lockdiscovery><D:activelock>'
                        "<D:locktype><D:write/></D:locktype><D:lockscope><D:exclusive/></D:lockscope><D:depth>0</D:depth>"
                        f"<D:timeout>Second-3600</D:timeout><D:locktoken><D:href>{token}</D:href></D:locktoken>"
                        "</D:activelock></D:lockdiscovery></D:prop>")
                return self.dav_send(200, body.encode(), extra={"Lock-Token": f"<{token}>"})
            if m == "UNLOCK":
                return self.dav_send(204, b"")
            if m == "PROPPATCH":
                self.dav_drain()
                body = (f'<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:"><D:response><D:href>{xml_escape(self.dav_href(vol, remote, False))}</D:href>'
                        "<D:propstat><D:prop/><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response></D:multistatus>")
                return self.dav_send(207, body.encode())
            return self.dav_send(405, b"")
        except AdbError as e:
            return self.dav_send(409, str(e).encode(), "text/plain")
        except subprocess.TimeoutExpired:
            return self.dav_send(504, b"")

    def _dav_head(self, e, remote):
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(remote)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(e["size"]))
        self.send_header("Last-Modified", formatdate(e["mtime"], usegmt=True))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()


# ---------------------------------------------------------------- HTTP

class Handler(DavMixin, BaseHTTPRequestHandler):
    server_version = "Cellar"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # Only answer to our own origin (blocks DNS-rebinding) and our own page
    # (the token is only ever embedded in the page we serve).
    def host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def authed(self, qs):
        tok = self.headers.get("X-Token") or qs.get("t", [""])[0]
        return secrets.compare_digest(tok, TOKEN)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_route(self, method):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        arg = lambda k, d="": qs.get(k, [d])[0]
        if u.path == "/dav" or u.path.startswith("/dav/"):
            return self.handle_dav()
        if not self.host_ok():
            return self.send_json({"error": "Forbidden"}, 403)
        if method == "GET" and u.path == "/":
            body = load_page().replace("__TOKEN__", TOKEN).replace("__HOME__", HOME_DIR).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        if not self.authed(qs):
            return self.send_json({"error": "Forbidden"}, 403)
        s = arg("s") or None
        try:
            if method == "GET" and u.path == "/api/devices":
                return self.send_json(list_devices())
            if method == "GET" and u.path == "/api/info":
                return self.send_json(device_info(s))
            if method == "GET" and u.path == "/api/exists":
                paths = [clean_path(x) for x in arg("paths").split("\n") if x.strip()][:50]
                script = "; ".join(f"[ -d {shlex.quote(x)} ] && echo {shlex.quote(x)}" for x in paths) + "; true"
                out = adb(s, "shell", script, check=False) if paths else ""
                return self.send_json({"exist": [x for x in out.splitlines() if x in paths]})
            if method == "GET" and u.path == "/api/ls":
                return self.send_json(list_dir(s, arg("path", HOME_DIR)))
            if method == "GET" and u.path == "/api/file":
                return self.stream_file(s, clean_path(arg("path")), arg("dl") == "1")
            if method == "GET" and u.path == "/api/screenshot":
                png = adb(s, "exec-out", "screencap -p", binary=True, timeout=30)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(png)
            if method == "POST" and u.path == "/api/pull":
                return self.send_json({"saved": pull_to_mac(s, arg("path"), arg("into"))})
            if method == "POST" and u.path == "/api/reveal":
                target = arg("path") or SAVE_DIR
                if not os.path.abspath(target).startswith(SAVE_DIR):
                    target = SAVE_DIR
                os.makedirs(SAVE_DIR, exist_ok=True)
                if sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", target])
                return self.send_json({"ok": True})
            if method == "POST" and u.path == "/api/wifi/enable":
                return self.send_json({"address": wifi_enable(s)})
            if method == "POST" and u.path == "/api/wifi/connect":
                addr = valid_addr(arg("addr"))
                if not adb_connect(addr, timeout=10):
                    raise AdbError(f"Couldn't reach {addr}. Check the address and that both are on the same Wi-Fi.")
                remember(addr)
                return self.send_json({"address": addr})
            if method == "POST" and u.path == "/api/wifi/pair":
                addr = wifi_pair(arg("addr"), arg("code"))
                return self.send_json({"address": addr, "needPort": addr is None})
            if method == "POST" and u.path == "/api/wifi/qr/start":
                return self.send_json(qr_start())
            if method == "POST" and u.path == "/api/wifi/qr/stop":
                QR.clear()
                QR["state"] = "idle"
                return self.send_json({"ok": True})
            if method == "GET" and u.path == "/api/wifi/qr/status":
                return self.send_json({k: v for k, v in QR.items() if k != "name"})
            if method == "GET" and u.path == "/api/wifi/known":
                return self.send_json({"known": load_known()})
            if method == "POST" and u.path == "/api/wifi/forget":
                forget(arg("addr"))
                return self.send_json({"ok": True})
            if method == "POST" and u.path == "/api/wifi/disconnect":
                if s:
                    adb(None, "disconnect", s, check=False)
                    if ":" in s:
                        forget(s)
                return self.send_json({"ok": True})
            if method == "POST" and u.path == "/api/mkdir":
                parts = [p for p in arg("name").split("/") if p not in ("", ".")]
                if not parts or ".." in parts:
                    raise AdbError("Invalid folder name")
                adb(s, "shell", "mkdir -p " + shlex.quote(posixpath.join(clean_path(arg("dir")), *parts)))
                return self.send_json({"ok": True})
            if method == "POST" and u.path == "/api/upload":
                return self.upload(s, arg("dir"), arg("name"))
            if self.api_ext(method, u.path, arg, s):
                return
            return self.send_json({"error": "Not found"}, 404)
        except AdbError as e:
            return self.send_json({"error": str(e)}, 502)
        except subprocess.TimeoutExpired:
            return self.send_json({"error": "The phone took too long to respond"}, 504)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.handle_route("GET")

    def do_POST(self):
        self.handle_route("POST")

    def _dav_or_405(self):
        if urllib.parse.urlparse(self.path).path.startswith("/dav"):
            return self.handle_dav()
        self.send_json({"error": "Method not allowed"}, 405)

    do_HEAD = do_PUT = do_DELETE = do_OPTIONS = _dav_or_405
    do_PROPFIND = do_PROPPATCH = do_MKCOL = do_COPY = do_MOVE = do_LOCK = do_UNLOCK = _dav_or_405

    # ------------------------------------------------------------ extended API

    def body_json(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > 20_000_000:
            raise AdbError("Request too large")
        raw = self.rfile.read(n) if n else b""
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            raise AdbError("Bad request")
        return d if isinstance(d, dict) else {}

    def send_file(self, path, ctype, cache=False):
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "private, max-age=604800" if cache else "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, CHUNK)

    def api_ext(self, method, path, arg, s):
        """Returns True when the request was handled."""
        R = (method, path)
        if R == ("GET", "/api/jobs"):
            jobs = sorted(JOBS.values(), key=lambda j: -j["created"])
            self.send_json({"jobs": [public_job(j) for j in jobs]})
        elif R == ("POST", "/api/jobs"):
            d = self.body_json()
            kind = d.get("kind")
            if kind == "pull":
                dest = SAVE_DIR
                if d.get("into"):
                    dest = os.path.join(SAVE_DIR, re.sub(r'[/:\\]', "-", d["into"]).strip(" ."))
                items = [{"path": clean_path(i["path"]), "as": i.get("as") or None, "policy": i.get("policy", "new")} for i in d.get("items", [])]
                if not items:
                    raise AdbError("Nothing to save")
                title = d.get("title") or (f"Save {len(items)} items to Mac" if len(items) > 1 else f"Save “{posixpath.basename(items[0]['path'])}”")
                j = new_job("pull", s, title, {"dest": dest, "items": items})
            elif kind == "push":
                roots = [{"name": r["name"], "as": r.get("as") or r["name"], "policy": r.get("policy", "new")} for r in d.get("roots", [])]
                stage_path(d.get("stage"), "x")  # validates id
                n = len(roots)
                title = d.get("title") or (f"Copy {n} items to phone" if n > 1 else f"Copy “{roots[0]['name']}” to phone")
                j = new_job("push", s, title, {"stage": d["stage"], "dir": d.get("dir") or HOME_DIR, "roots": roots})
            elif kind == "phoneop":
                op = "move" if d.get("op") == "move" else "copy"
                items = [{"path": clean_path(i["path"]), "as": i.get("as") or None, "policy": i.get("policy", "new")} for i in d.get("items", [])]
                dest = clean_path(d.get("dest") or "")
                n = len(items)
                verb = "Move" if op == "move" else "Copy"
                title = d.get("title") or (f"{verb} {n} items to {posixpath.basename(dest) or '/'}" if n > 1 else f"{verb} “{posixpath.basename(items[0]['path'])}” to {posixpath.basename(dest) or '/'}")
                j = new_job("phoneop", s, title, {"op": op, "items": items, "dest": dest}, lane="phone")
            elif kind == "install":
                stage_path(d.get("stage"), "x")
                j = new_job("install", s, d.get("title") or "Install app", {"stage": d["stage"]})
            else:
                raise AdbError("Unknown job")
            self.send_json(public_job(j))
        elif R == ("POST", "/api/jobs/cancel"):
            j = JOBS.get(arg("id"))
            if j:
                j["_cancel"] = True
                if j["state"] == "queued":
                    j["state"], j["finished"] = "cancelled", time.time()
                p = j.get("_proc")
                if p and p.poll() is None:
                    p.kill()
            self.send_json({"ok": True})
        elif R == ("POST", "/api/jobs/clear"):
            with _job_lock:
                for k in [k for k, j in JOBS.items() if j["finished"]]:
                    JOBS.pop(k, None)
            self.send_json({"ok": True})
        elif R == ("POST", "/api/stage"):
            dest = stage_path(arg("id"), arg("rel"))
            with open(dest, "wb") as f:
                self.dav_body_to(f)
            mt = arg("mtime")
            if mt.isdigit():
                os.utime(dest, (int(mt) / 1000, int(mt) / 1000))
            self.send_json({"ok": True})
        elif R == ("POST", "/api/stage/mkdir"):
            os.makedirs(os.path.dirname(stage_path(arg("id"), arg("rel") + "/.keep")), exist_ok=True)
            self.send_json({"ok": True})
        elif R == ("POST", "/api/check"):
            d = self.body_json()
            names = [n for n in d.get("names", []) if isinstance(n, str)][:2000]
            if d.get("side") == "mac":
                folder = os.path.join(SAVE_DIR, re.sub(r'[/:\\]', "-", d.get("into", "")).strip(" .")) if d.get("into") else SAVE_DIR
                found = {}
                for n in names:
                    p = os.path.join(folder, n)
                    if os.path.lexists(p):
                        st = os.stat(p)
                        found[n] = {"dir": os.path.isdir(p), "size": 0 if os.path.isdir(p) else st.st_size, "mtime": int(st.st_mtime)}
                self.send_json({"existing": found})
            else:
                self.send_json({"existing": stat_names(s, clean_path(d.get("dir", "")), names)})
        elif R == ("POST", "/api/rename"):
            d = self.body_json()
            self.send_json(phone_rename(s, d.get("path"), d.get("name")))
        elif R == ("POST", "/api/newfolder"):
            d = self.body_json()
            self.send_json(phone_mkdir(s, d.get("dir"), d.get("name", "")))
        elif R == ("POST", "/api/trash"):
            self.send_json(phone_trash(s, self.body_json().get("paths", [])))
        elif R == ("POST", "/api/untrash"):
            self.send_json(phone_untrash(s, set(self.body_json().get("ids", []))))
        elif R == ("GET", "/api/trash"):
            self.send_json({"entries": phone_trash_list(s), "days": TRASH_DAYS})
        elif R == ("POST", "/api/trash/empty"):
            ids = self.body_json().get("ids")
            self.send_json(phone_trash_empty(s, set(ids) if ids else None))
        elif R == ("GET", "/api/search"):
            self.send_json(phone_search(s, arg("q"), arg("root") or HOME_DIR))
        elif R == ("POST", "/api/scan"):
            d = self.body_json()
            if d.get("kind") not in SCAN_RUNNERS:
                raise AdbError("Unknown scan")
            self.send_json(start_scan(d["kind"], s, d.get("root"), **(d.get("opts") or {})))
        elif R == ("GET", "/api/scan"):
            sc = SCANS.get(arg("id"))
            if not sc:
                raise AdbError("That scan has expired. Start it again.")
            self.send_json(public_scan(sc))
        elif R == ("POST", "/api/scan/cancel"):
            sc = SCANS.get(arg("id"))
            if sc:
                sc["_cancel"] = True
            self.send_json({"ok": True})
        elif R == ("POST", "/api/export"):
            what = [w for w in self.body_json().get("what", []) if w in EXPORTERS]
            if not what:
                raise AdbError("Choose what to export")
            self.send_json(run_exports(s, what))
        elif R == ("GET", "/api/sms/check"):
            self.send_json(sms_check(s))
        elif R == ("GET", "/api/sms/threads"):
            self.send_json(sms_threads(s))
        elif R == ("POST", "/api/sms/export"):
            d = self.body_json()
            fmt = d.get("format") if d.get("format") in ("csv", "pdf", "both") else "csv"
            keys = set(d["threads"]) if isinstance(d.get("threads"), list) else None
            self.send_json(sms_export(s, fmt, keys))
        elif R == ("GET", "/api/extras"):
            self.send_json(extras_info(s))
        elif R == ("POST", "/api/media"):
            self.send_json(media_key(s, self.body_json().get("key")))
        elif R == ("POST", "/api/dnd"):
            self.send_json(set_dnd(s, self.body_json().get("mode")))
        elif R == ("POST", "/api/ring"):
            self.body_json()   # always drain the request body so the connection stays in sync
            self.send_json(ring_phone(s))
        elif R == ("GET", "/api/sync"):
            hw = hw_id(s)
            self.send_json({"pairs": [sync_public(p) for p in sync_pairs_all() if p.get("hw") == hw], "versions": SYNC_VERSIONS})
        elif R == ("POST", "/api/sync/pairs"):
            d = self.body_json()
            self.send_json(sync_public(sync_create(s, d.get("mac"), d.get("phone"), d.get("name", ""), d.get("auto", False))))
        elif R == ("POST", "/api/sync/pairs/update"):
            d = self.body_json()
            sync_pair(d.get("id"))
            def upd(p):
                if "auto" in d:
                    p["auto"] = bool(d["auto"])
                if isinstance(d.get("name"), str) and d["name"].strip():
                    p["name"] = d["name"].strip()
                if d.get("dismiss_conflicts"):
                    p["conflicts"] = []
            sync_update_pair(d["id"], upd)
            self.send_json(sync_public(sync_pair(d["id"])))
        elif R == ("POST", "/api/sync/pairs/delete"):
            pid = self.body_json().get("id")
            sync_pair(pid)
            update_cfg(lambda c: c.update(sync_pairs=[p for p in c.get("sync_pairs", []) if p.get("id") != pid]))
            try:
                os.remove(sync_manifest_path(pid))
            except OSError:
                pass
            self.send_json({"ok": True})
        elif R == ("GET", "/api/sync/preview"):
            self.send_json(sync_preview(s, arg("id")))
        elif R == ("POST", "/api/sync/run"):
            d = self.body_json()
            self.send_json(public_job(sync_start(s, d.get("id"), confirm=bool(d.get("confirm")))))
        elif R == ("GET", "/api/volumes"):
            self.send_json({"volumes": list_volumes(s)})
        elif R == ("GET", "/api/recent"):
            self.send_json(phone_recent(s))
        elif R == ("GET", "/api/thumb"):
            f, ctype = thumb_file(s, clean_path(arg("path")), arg("m"), arg("z"), arg("px", "360"))
            self.send_file(f, ctype, cache=True)
        elif R == ("GET", "/api/backup"):
            scan = backup_scan(s)
            self.send_json({k: v for k, v in scan.items() if not k.startswith("_")})
        elif R == ("POST", "/api/backup/settings"):
            self.send_json(backup_save_settings(s, self.body_json()))
        elif R == ("POST", "/api/backup/run"):
            j = backup_start(s)
            self.send_json(public_job(j) if j else {"nothing": True})
        elif R == ("POST", "/api/pickfolder"):
            if not IS_MAC:
                raise AdbError("Folder picker needs macOS")
            prompt = re.sub(r'["\\]', "", (arg("prompt") or "Choose where Cellar saves backups"))[:80]
            r = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}")'],
                               capture_output=True, text=True, timeout=600)
            self.send_json({"path": r.stdout.strip().rstrip("/")} if r.returncode == 0 else {"cancelled": True})
        elif R == ("GET", "/api/apps"):
            self.send_json(list_apps(s))
        elif R == ("POST", "/api/apps/backup"):
            self.send_json(public_job(app_backup(s, arg("pkg"))))
        elif R == ("POST", "/api/apps/uninstall"):
            pkg = arg("pkg")
            if not re.fullmatch(r"[\w.]+", pkg):
                raise AdbError("Invalid app id")
            out = adb(s, "uninstall", pkg, timeout=60, check=False)
            if "Success" not in out:
                raise AdbError("Couldn't uninstall: " + adb_msg(out))
            self.send_json({"ok": True})
        elif R == ("GET", "/api/tools"):
            exe = find_scrcpy()
            self.send_json({"adb": ADB, "scrcpy": exe, "scrcpy_version": list(scrcpy_version(exe) or []) if exe else None, "mac": IS_MAC})
        elif R == ("POST", "/api/tools/install"):
            tool = arg("tool")
            self.send_json(install_adb() if tool == "adb" else install_scrcpy())
        elif R == ("POST", "/api/mirror"):
            self.send_json(start_mirror(s, self.body_json()))
        elif R == ("GET", "/api/settings"):
            st = load_cfg().get("settings", {})
            self.send_json({"notifications": st.get("notifications", True), "finder_auto": st.get("finder_auto", False)})
        elif R == ("POST", "/api/settings"):
            d = self.body_json()
            clean = {k: bool(d[k]) for k in ("notifications", "finder_auto") if k in d}
            update_cfg(lambda c: c.setdefault("settings", {}).update(clean))
            self.send_json({"ok": True})
        elif R == ("GET", "/api/finder"):
            vol = dav_volume_name(s) if s else ""
            self.send_json({"mounted": bool(s and finder_mountpoint(vol)), "volume": vol, "mac": IS_MAC,
                            "url": f"http://127.0.0.1:{SERVER_PORT[0]}/dav/{urllib.parse.quote(vol)}/"})
        elif R == ("POST", "/api/finder/mount"):
            self.send_json(finder_mount(s))
        elif R == ("POST", "/api/finder/unmount"):
            self.send_json(finder_unmount(s))
        elif R == ("POST", "/api/openmac"):
            self.send_json(open_on_mac(s, clean_path(arg("path"))))
        else:
            return False
        return True

    def stream_file(self, serial, path, download):
        size = file_size(serial, path)
        q = shlex.quote(path)
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes=") and size > 0:
            a, _, b = rng[6:].split(",")[0].strip().partition("-")
            try:
                if a == "":
                    start, end = max(0, size - int(b)), size - 1
                else:
                    start, end = int(a), min(int(b) if b else size - 1, size - 1)
            except ValueError:
                start, end = 0, size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        length = max(0, end - start + 1)
        if start == 0 and length == size:
            cmd = f"cat {q}"
        elif start == 0:
            cmd = f"head -c {length} {q}"
        else:
            cmd = f"tail -c +{start + 1} {q} | head -c {length}"
        proc = subprocess.Popen([ADB, "-s", serial, "exec-out", cmd],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            self.send_response(status)
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            fname = urllib.parse.quote(posixpath.basename(path))
            disp = "attachment" if download else "inline"
            self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{fname}")
            self.end_headers()
            while True:
                chunk = proc.stdout.read(CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def upload(self, serial, remote_dir, name):
        length = int(self.headers.get("Content-Length", "0"))
        fd, tmp = tempfile.mkstemp(prefix="cellar-")
        try:
            with os.fdopen(fd, "wb") as f:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left > 0:
                raise AdbError("The upload was interrupted")
            push_from_mac(serial, tmp, remote_dir, name)
        finally:
            os.unlink(tmp)
        return self.send_json({"ok": True})


def main():
    port = int(os.environ.get("CELLAR_PORT", "8765"))
    server = None
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    if not server:
        sys.exit("Couldn't find a free port.")
    server.daemon_threads = True
    SERVER_PORT[0] = server.server_address[1]
    threading.Thread(target=device_watcher, daemon=True).start()
    threading.Thread(target=prune_cache, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print("\n  Cellar is running at " + url)
    if not ADB:
        print("  ! Android tools (adb) not found. Cellar can download them for you from its window.")
    else:
        subprocess.run([ADB, "start-server"], capture_output=True)
    print("  Files you save go to " + SAVE_DIR)
    print("  Press Ctrl+C to quit.\n")
    if not os.environ.get("CELLAR_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Bye.")


# ---------------------------------------------------------------- UI

UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")


def load_page():
    import base64
    with open(UI_FILE, encoding="utf-8") as f:
        page = f.read()
    # Geist (SIL Open Font License) ships next to the app and is inlined, so it works offline. System fonts are the fallback.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(UI_FILE)), "fonts", "Geist-Variable.woff2"), "rb") as f:
            uri = "data:font/woff2;base64," + base64.b64encode(f.read()).decode()
        page = page.replace("/*__GEIST__*/", "@font-face{font-family:Geist;src:url(%s) format('woff2');font-weight:100 900;font-display:swap}" % uri, 1)
    except OSError:
        pass
    return page

if __name__ == "__main__":
    main()
