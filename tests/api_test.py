import json, re, time, urllib.request, os, sys
B="http://127.0.0.1:8765"; H=os.environ["HOME_DIR"]="/storage/emulated/0"
TOK=re.search(r'const T = "([^"]+)"', urllib.request.urlopen(B+"/").read().decode()).group(1)
def call(path, method="GET", body=None, raw=None, **params):
    params.setdefault("s","FAKE123"); qs="&".join(f"{k}={urllib.parse.quote(str(v))}" for k,v in params.items())
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req=urllib.request.Request(f"{B}{path}?{qs}", data=data, method=method, headers={"X-Token":TOK,"Content-Type":"application/json"})
    try: return json.loads(urllib.request.urlopen(req, timeout=60).read() or b"{}")
    except urllib.error.HTTPError as e: return {"HTTP":e.code, **json.loads(e.read() or b"{}")}
import urllib.parse
def wait(j):
    for _ in range(100):
        jj=[x for x in call("/api/jobs")["jobs"] if x["id"]==j["id"]][0]
        if jj["state"] in ("done","error","cancelled"): return jj
        time.sleep(0.2)
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
H="/storage/emulated/0"
# rename / newfolder
r=call("/api/newfolder","POST",{"dir":H+"/Documents"}); ok(r.get("name")=="untitled folder", f"new folder {r}")
r2=call("/api/newfolder","POST",{"dir":H+"/Documents"}); ok(r2.get("name")=="untitled folder 2", f"second new folder {r2.get('name')}")
r=call("/api/rename","POST",{"path":r["path"],"name":"Trip to Bali"}); ok(r.get("to","").endswith("Trip to Bali"), "rename")
r=call("/api/rename","POST",{"path":r2["path"],"name":"Trip to Bali"}); ok("already an item" in r.get("error",""), "rename clash refused")
r=call("/api/rename","POST",{"path":r2["path"],"name":"a/b"}); ok("can't" in r.get("error",""), "slash refused")
# conflict check
r=call("/api/check","POST",{"side":"phone","dir":H+"/Documents","names":["Trip to Bali","nope.txt","hi.txt"]}); ok(set(r["existing"])=={"Trip to Bali","hi.txt"}, f"check {list(r['existing'])}")
# phone copy with keep-both + merge + move
j=call("/api/jobs","POST",{"kind":"phoneop","op":"copy","items":[{"path":H+"/Documents/hi.txt"}],"dest":H+"/Documents"}); j=wait(j)
ok(j["state"]=="done" and j["result"]["created"][0].endswith("hi 2.txt"), f"copy same folder keeps both -> {j['result']}")
j=wait(call("/api/jobs","POST",{"kind":"phoneop","op":"move","items":[{"path":H+"/Documents/hi 2.txt"}],"dest":H+"/Documents/Trip to Bali"}))
ok(j["state"]=="done" and os.path.exists(H+"/Documents/Trip to Bali/hi 2.txt"), "move into folder")
j=wait(call("/api/jobs","POST",{"kind":"phoneop","op":"move","items":[{"path":H+"/Documents/Trip to Bali"}],"dest":H+"/Documents/Trip to Bali"}))
ok("inside itself" in str(j["errors"]), "move folder into itself refused")
os.makedirs(H+"/Download/Work",exist_ok=True); open(H+"/Download/Work/extra.txt","w").write("x")
j=wait(call("/api/jobs","POST",{"kind":"phoneop","op":"copy","items":[{"path":H+"/Download/Work","policy":"merge"}],"dest":H+"/Documents"}))
ok(os.path.exists(H+"/Documents/Work/extra.txt") and os.path.exists(H+"/Documents/Work/Q4/plan.txt"), "copy folder merge")
# trash / untrash / list / empty
r=call("/api/trash","POST",{"paths":[H+"/Documents/Trip to Bali", H+"/Download/Work"]}); ok(len(r["items"])==2 and not os.path.exists(H+"/Download/Work"), "trash 2 items")
t=call("/api/trash"); ok(len(t["entries"])==2, f"trash list {[e['name'] for e in t['entries']]}")
r=call("/api/untrash","POST",{"ids":[r["items"][0]["id"]]}); ok(os.path.exists(H+"/Documents/Trip to Bali/hi 2.txt"), f"put back {r}")
r=call("/api/trash/empty","POST",{}); ok(r["removed"]==1 and call("/api/trash")["entries"]==[], "empty trash")
r=call("/api/trash","POST",{"paths":[H]}); ok("can't" in r.get("error",""), "can't trash storage root")
# search & recent
r=call("/api/search",q="invoice"); ok(any(e["name"]=="Invoice-Oct.pdf" for e in r["entries"]), f"search {[e['name'] for e in r['entries']]}")
r=call("/api/search",q="a"); ok("at least 2" in r.get("error",""), "short query refused")
r=call("/api/recent"); ok(len(r["entries"])>3 and r["entries"][0]["mtime"]>=r["entries"][-1]["mtime"], f"recent {len(r['entries'])}")
# pull job with conflict keep-both + replace
j=wait(call("/api/jobs","POST",{"kind":"pull","items":[{"path":H+"/Download/report.pdf"}]})); ok(j["state"]=="done", "pull 1")
j=wait(call("/api/jobs","POST",{"kind":"pull","items":[{"path":H+"/Download/report.pdf"}]})); ok(j["result"]["saved"][0].endswith("report 2.pdf"), f"pull again keeps both {j['result']['saved']}")
j=wait(call("/api/jobs","POST",{"kind":"pull","items":[{"path":H+"/Download/report.pdf","policy":"replace"}]})); ok(j["result"]["saved"][0].endswith("/report.pdf"), "pull replace")
r=call("/api/check","POST",{"side":"mac","names":["report.pdf","zzz"]}); ok(list(r["existing"])==["report.pdf"], "mac check")
# push via staging, folder, keep both
sid="ab12cd34ef"
call("/api/stage","POST",raw=b"hello", id=sid, rel="Notes/a.txt"); call("/api/stage","POST",raw=b"world", id=sid, rel="Notes/sub/b.txt"); call("/api/stage/mkdir","POST",raw=b"",id=sid,rel="Notes/empty")
j=wait(call("/api/jobs","POST",{"kind":"push","stage":sid,"dir":H+"/Documents","roots":[{"name":"Notes"}]}))
ok(j["state"]=="done" and open(H+"/Documents/Notes/sub/b.txt").read()=="world" and os.path.isdir(H+"/Documents/Notes/empty"), f"push folder {j['errors']}")
sid2="ab12cd34ff"; call("/api/stage","POST",raw=b"v2",id=sid2,rel="Notes/a.txt")
j=wait(call("/api/jobs","POST",{"kind":"push","stage":sid2,"dir":H+"/Documents","roots":[{"name":"Notes","policy":"merge"}]}))
ok(open(H+"/Documents/Notes/a.txt").read()=="v2" and os.path.exists(H+"/Documents/Notes/sub/b.txt"), "push merge")
r=call("/api/stage","POST",raw=b"x",id="../../etc",rel="a"); ok(r.get("HTTP")==502, "bad stage id refused")
# cancel queued job
j1=call("/api/jobs","POST",{"kind":"pull","items":[{"path":H+"/DCIM"}],"into":"big"}); call("/api/jobs/cancel","POST",raw=b"",id=j1["id"]); jj=wait(j1); ok(jj["state"] in("cancelled","done"), f"cancel -> {jj['state']}")
# backup
r=call("/api/backup"); ok(r["count"]>=7 and r["sources"][0]["on"], f"backup scan count={r['count']} bytes={r['bytes']}")
call("/api/backup/settings","POST",{"sources":["Camera","Screenshots"],"dest":"~/Pictures/Cellar/Test","heic":False})
r=call("/api/backup"); n=r["count"]; j=call("/api/backup/run","POST",raw=b""); j=wait(j)
ok(j["state"]=="done" and len(os.listdir(os.path.expanduser("~/Pictures/Cellar/Test/Camera")))>=7, f"backup ran {j['items_done']} items")
r=call("/api/backup"); ok(r["count"]==0, f"second scan finds nothing new ({r['count']})")
open(H+"/DCIM/Camera/NEW_1.jpg","wb").write(b"new"); r=call("/api/backup"); ok(r["count"]==1, "only the new photo")
# apps
r=call("/api/apps"); ok([a["name"] for a in r["apps"]]==["Telegram","Whatsapp"] and r["apps"][0]["size"]>0, f"apps {[(a['name'],a['size']) for a in r['apps']]}")
j=wait(call("/api/apps/backup","POST",raw=b"",pkg="org.telegram.messenger")); ok(len(os.listdir(os.path.expanduser("~/Downloads/Cellar/Apps/org.telegram.messenger")))==2, "split apk backup")
j=wait(call("/api/apps/backup","POST",raw=b"",pkg="com.whatsapp")); ok(os.path.exists(os.path.expanduser("~/Downloads/Cellar/Apps/com.whatsapp.apk")), "single apk backup")
sid3="ab12cd3400"; call("/api/stage","POST",raw=b"apk",id=sid3,rel="game.apk"); j=wait(call("/api/jobs","POST",{"kind":"install","stage":sid3})); ok(j["state"]=="done", "install apk")
# thumbs
r=urllib.request.urlopen(f"{B}/api/thumb?s=FAKE123&path={urllib.parse.quote(H+'/DCIM/Camera/PXL_20261100_12340.png')}&m=1&z=2&t={TOK}"); ok(r.status==200 and len(r.read())>100 and "max-age" in r.headers["Cache-Control"], "thumbnail served+cached")
print(call("/api/tools"), call("/api/settings"))
# --- step 1: SD cards and USB drives
SD="/storage/1A2B-3C4D"
v=call("/api/volumes")["volumes"]; ok(len(v)==1 and v[0]["path"]==SD and v[0]["name"]=="SD card" and v[0]["storage"]["total"]>0, f"volumes {v}")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importlib.util
spec=importlib.util.spec_from_file_location("cellar_mod", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cellar.py"))
cm=importlib.util.module_from_spec(spec); spec.loader.exec_module(cm)
pv=cm.parse_volumes("public:179,65 mounted 1A2B-3C4D\npublic:8,1 mounted 0123-4567\npublic:8,17 unmounted 9999-AAAA\nemulated;0 mounted null\n")
ok(pv=={"1A2B-3C4D":"SD card","0123-4567":"USB drive"}, f"parse_volumes sm output {pv}")
ok(cm.parse_volumes("", "emulated self 1A2B-3C4D")=={"1A2B-3C4D":"SD card or USB drive"}, "parse_volumes falls back to /storage names")
r=call("/api/trash","POST",{"paths":[SD+"/Documents/sd-notes.txt", H+"/Documents/hi.txt"]})
ok(len(r["items"])==2 and not os.path.exists(SD+"/Documents/sd-notes.txt") and os.path.isdir(SD+"/.CellarTrash") and len(os.listdir(SD+"/.CellarTrash"))>=2, "trash on the card stays on the card")
ok(not any("sd-notes" in n for n in os.listdir(H+"/.CellarTrash")), "card items are not copied to internal storage")
t=call("/api/trash"); ok({e["name"] for e in t["entries"]}=={"sd-notes.txt","hi.txt"}, f"trash lists both drives {[e['name'] for e in t['entries']]}")
r2=call("/api/untrash","POST",{"ids":[e["id"] for e in t["entries"]]}); ok(os.path.exists(SD+"/Documents/sd-notes.txt") and os.path.exists(H+"/Documents/hi.txt"), f"put back to the right drive {r2}")
r=call("/api/trash","POST",{"paths":[SD]}); ok("can't" in r.get("error",""), "can't trash a drive's root")
r=call("/api/search",q="sd-notes",root=SD); ok([e["name"] for e in r["entries"]]==["sd-notes.txt"], "search inside the card")
r=call("/api/search",q="sd-notes"); ok(r["entries"]==[], "internal search doesn't leak card files")
os.utime(SD+"/Documents/sd-notes.txt")
r=call("/api/recent"); ok(any(e["path"].startswith(SD) for e in r["entries"]), "recent includes the card")
call("/api/trash/empty","POST",{})
# --- step 2: what's taking space
def scan(kind, root=None, **opts):
    sc=call("/api/scan","POST",{"kind":kind,"root":root or H,"opts":opts})
    for _ in range(150):
        sc=call("/api/scan",id=sc["id"])
        if sc["state"]!="running": return sc
        time.sleep(0.2)
sc=scan("space"); r=sc["result"]
ok(sc["state"]=="done" and r["total"]>3_000_000 and r["files"]>10, f"space scan {sc['state']} {r['total']} bytes in {r['files']} files")
tn={t["type"]:t for t in r["types"]}; ok("Photos" in tn and "Documents" in tn and "Apps" in tn and tn["Apps"]["bytes"]==500_000, f"by type {list(tn)}")
ok(r["biggest"][0]["size"]>=r["biggest"][-1]["size"] and r["biggest"][0]["name"]=="report.pdf", f"biggest first: {r['biggest'][0]['name']}")
fn={f["name"]:f for f in r["folders"]}; ok("Download" in fn and "DCIM" in fn and fn["DCIM"]["kids"] and r["folders"][0]["bytes"]>=r["folders"][-1]["bytes"], f"by folder {list(fn)[:4]}")
ok(sum(t["bytes"] for t in r["types"])==r["total"], "type totals add up")
ok(not any(".CellarTrash" in e["path"] or "/Android/data" in e["path"] for e in r["biggest"]), "Trash and protected folders left out")
sc=scan("space", SD); ok(sc["state"]=="done" and sc["result"]["files"]>=1 and all(e["path"].startswith(SD) for e in sc["result"]["biggest"]), "space scan on the SD card stays on the card")
r=call("/api/scan","POST",{"kind":"nope"}); ok("Unknown" in r.get("error",""), "unknown scan refused")
