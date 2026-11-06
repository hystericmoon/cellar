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
# --- step 3: duplicates
D=H+"/Documents"
open(D+"/dupA.bin","wb").write(b"A"*5000); open(D+"/dupB.bin","wb").write(b"A"*5000); open(D+"/dupC.bin","wb").write(b"A"*4999+b"B"); open(D+"/Work/dupA copy.bin","wb").write(b"A"*5000)
os.utime(D+"/dupA.bin",(1_700_000_000,1_700_000_000))
sc=scan("dupes"); r=sc["result"]; ok(sc["state"]=="done", f"dupes scan {sc['state']} {sc.get('error')}")
g=[x for x in r["groups"] if x["files"][0]["name"]=="dupA.bin"]
ok(len(g)==1 and len(g[0]["files"])==3 and {f["name"] for f in g[0]["files"]}=={"dupA.bin","dupB.bin","dupA copy.bin"}, f"identical files grouped: {[f['name'] for f in g[0]['files']] if g else None}")
ok(not any(f["name"]=="dupC.bin" for x in r["groups"] for f in x["files"]), "same size but different content is not a duplicate")
ok(g and g[0]["files"][0]["name"]=="dupA.bin" and g[0]["wasted"]==10000, "oldest copy first, wasted = size x (copies-1)")
ok(any(x["files"][0]["name"] in ("report.pdf",) for x in r["groups"]) and r["groups"][0]["wasted"]>=r["groups"][-1]["wasted"], "biggest waste first")
ok(not any(f["name"].startswith(".") for x in r["groups"] for f in x["files"]), "hidden files ignored")
for n in ("dupA.bin","dupB.bin","dupC.bin","Work/dupA copy.bin"): os.remove(D+"/"+n)
# --- step 4: export contacts, calls, calendar
import datetime, glob
XD=os.path.expanduser("~/Downloads/Cellar/Exports/"+datetime.date.today().isoformat())
r=call("/api/export","POST",{"what":["contacts","calls","calendar"]})
ok(set(r["results"])=={"contacts","calls","calendar"} and all("error" not in x for x in r["results"].values()), f"export ran {[(k,v.get('count'),v.get('error')) for k,v in r['results'].items()]}")
vcf=open(XD+"/contacts.vcf",newline="").read()
ok(vcf.count("BEGIN:VCARD")==3 and "FN:Ada Lovelace" in vcf and "TEL;TYPE=CELL:+44 20 7946 0001" in vcf and "EMAIL;TYPE=HOME:ada@example.com" in vcf and "N:Lovelace;Ada;;;" in vcf, "contacts.vcf has names, phones, emails")
ok("NOTE:Met at the fair\\; likes maths\\,\\nsecond line" in vcf and "ORG:Analytical Engines\\, Ltd" in vcf, "vcard escapes commas, semicolons and line breaks")
import csv
rows=list(csv.reader(open(XD+"/contacts.csv",encoding="utf-8-sig",newline=""))); ok(rows[0][0]=="Name" and rows[1][3]=="+44 20 7946 0001" and rows[2][3]=="0412 345 678; 0412 999 000" and "second line" in rows[1][6], "contacts.csv keeps multi-line notes in one cell")
ok(len(rows)==4 and rows[3][0]=="Cy Dee" and rows[3][3]=="+62 811-0000-001" and rows[3][4]=="cy@example.com", f"one contact stored under two accounts exports once, numbers and emails merged {rows[3]}")
calls=list(csv.reader(open(XD+"/call-history.csv",encoding="utf-8-sig",newline=""))); ok(len(calls)==4 and calls[1][3]=="Incoming" and calls[2][3]=="Outgoing" and calls[3][3]=="Missed" and calls[1][4]=="75", f"call history csv {calls[1]}")
ok(cm.sheet_safe("628123456789")=="6281 2345 6789" and cm.sheet_safe("085729571234")=="0857 2957 1234" and cm.sheet_safe("+6281234567890")=="+6281 2345 6789 0" and cm.sheet_safe("+62 815-1135-5600")=="+62 815-1135-5600" and cm.sheet_safe("=1+1")=="'=1+1" and cm.sheet_safe("Hello")=="Hello", "CSV: bare phone numbers stay text in spreadsheets, formula-looking cells are neutralised")
ics=open(XD+"/calendar.ics",newline="").read()
ok(ics.count("BEGIN:VEVENT")==3 and "Cancelled" not in ics and "SUMMARY:Dentist\\, 3rd floor" in ics and "DESCRIPTION:Bring forms\\;\\nreception opens at 9" in ics, "calendar.ics skips deleted events and escapes text")
ok("DTSTART;VALUE=DATE:20241029" in ics and "RRULE:FREQ=WEEKLY;BYDAY=MO" in ics and "DURATION:P3600S" in ics and "DTSTART:20241028T100000Z" in ics, "all-day, repeating and timed events")
r=call("/api/export","POST",{"what":["calls"]}); ok(os.path.exists(XD+"/call-history 2.csv"), "a second export never overwrites the first")
open(os.path.dirname(os.path.abspath(__file__))+"/fakebin/calendar_denied","w").close()
r=call("/api/export","POST",{"what":["calendar","calls"]}); os.remove(os.path.dirname(os.path.abspath(__file__))+"/fakebin/calendar_denied")
ok("won't let Cellar read your calendar" in r["results"]["calendar"].get("error","") and "error" not in r["results"]["calls"], "a refused provider is explained and doesn't stop the others")
r=call("/api/export","POST",{"what":[]}); ok("Choose" in r.get("error",""), "nothing chosen is refused")
rows=cm.parse_rows("Row: 0 a=1, b=hello, world, c=x\nline2\nRow: 1 a=2, b=NULL, c=y\n",["a","b","c"]); ok(rows==[{"a":"1","b":"hello, world","c":"x\nline2"},{"a":"2","b":"","c":"y"}], f"parse_rows handles commas, line breaks, NULL {rows}")
# --- step 5: text messages
FB=os.path.dirname(os.path.abspath(__file__))+"/fakebin"
ok(call("/api/sms/check")["ok"], "sms readable on the fake phone")
t=call("/api/sms/threads"); ok(t["total"]==3 and len(t["threads"])==2 and t["threads"][0]["name"] in ("Bo Zhang",) and {x["name"] for x in t["threads"]}=={"Ada Lovelace","Bo Zhang"}, f"threads with contact names {[(x['name'],x['count']) for x in t['threads']]}")
r=call("/api/sms/export","POST",{"format":"csv","threads":None}); MD=XD+"/Messages"
rows=list(csv.reader(open(MD+"/messages.csv",encoding="utf-8-sig",newline="")))
ok(len(rows)==4 and rows[0][2]=="Direction" and rows[1][2]=="Received" and rows[2][2]=="Sent" and 'red' in rows[2][5] and "\n" in rows[2][5], f"messages.csv keeps quotes and line breaks in one cell: {rows[2][5]!r}")
ada=[x["key"] for x in t["threads"] if x["name"]=="Ada Lovelace"]
r=call("/api/sms/export","POST",{"format":"csv","threads":ada}); rows=list(csv.reader(open(MD+"/messages 2.csv",encoding="utf-8-sig",newline=""))); ok(len(rows)==3, "export only the chosen conversation, never overwrite")
r=call("/api/sms/export","POST",{"format":"pdf","threads":None}); ok(r["files"]==["messages.pdf"] and open(MD+"/messages.pdf","rb").read(5)==b"%PDF-" and not os.path.exists(MD+"/messages.html"), f"pdf made from html {r['files']} {r.get('note')}")
cm_html=cm.sms_html([{"when":1730000000000,"number":"+4420","key":"4420","name":"Ada Lovelace","dir":"in","body":"say \"red\" <b>","kind":"SMS"}],"T"); ok("Ada Lovelace" in cm_html and "&quot;red&quot;" in cm_html and "<b>" not in cm_html.split("</style>")[1], "pdf html groups by name and escapes text")
cm.find_pdf_browser=lambda: None; ok(cm.html_to_pdf("/nonexistent.html","/tmp/x.pdf") is False, "no browser and no cupsfilter: falls back instead of crashing")

r=call("/api/sms/export","POST",{"format":"csv","threads":[]}); ok("no messages" in r.get("error","").lower(), "empty selection refused")
open(FB+"/sms_denied","w").close()
c=call("/api/sms/check"); r=call("/api/sms/threads"); os.remove(FB+"/sms_denied")
ok(c["ok"] is False and "doesn't let Cellar read text messages" in c["reason"] and "error" in r, f"refused SMS is detected and explained: {c.get('reason','')[:60]}")
# --- step 6: phone camera in the mirror dialog (scrcpy itself can't run here; these check the command we would run)
info={"manufacturer":"Google","model":"Pixel 8 Pro","android":"15"}
c=cm.build_mirror_cmd("/x/scrcpy","S1",{"source":"camera","facing":"front"},info,(2,4))
ok("--video-source=camera" in c and "--camera-facing=front" in c and "--no-control" in c and "--no-audio" in c and "--stay-awake" not in c, f"camera command {c[3:]}")
ok("--audio-source=mic" in cm.build_mirror_cmd("/x/scrcpy","S1",{"source":"camera","mic":True},info,(2,4)) and "--camera-facing=back" in cm.build_mirror_cmd("/x/scrcpy","S1",{"source":"camera","facing":"bogus"},info,(2,4)), "mic is opt-in; unknown facing falls back to back")
try: cm.build_mirror_cmd("/x/scrcpy","S1",{"source":"camera"},dict(info,android="11"),(2,4)); ok(False,"Android 11 refused")
except cm.AdbError as e: ok("Android 12" in str(e) and "Android 11" in str(e), f"Android 11 refused: {e}")
try: cm.build_mirror_cmd("/x/scrcpy","S1",{"source":"camera"},info,(2,1)); ok(False,"old scrcpy refused")
except cm.AdbError as e: ok("brew upgrade scrcpy" in str(e), "old scrcpy explains how to update")
s=cm.build_mirror_cmd("/x/scrcpy","S1",{"screen_off":True,"keyboard":"uhid"},info,(2,4)); ok("--turn-screen-off" in s and "--keyboard=uhid" in s and "--video-source=camera" not in s and "--stay-awake" in s, "screen mirroring command unchanged")
ok(cm.android_major("15")==15 and cm.android_major("")==0 and cm.android_major("12.1")==12, "android_major")
# --- step 7: ring, media keys, Do Not Disturb
LOG=FB+"/calls.log"
def calls(): return open(LOG).read() if os.path.exists(LOG) else ""
x=call("/api/extras"); ok(x["can_ring"] and x["dnd"]=="off", f"extras {x}")
open(LOG,"w").close()
r=call("/api/media","POST",{"key":"playpause"}); r2=call("/api/media","POST",{"key":"next"}); ok("input keyevent 85" in calls() and "input keyevent 87" in calls(), "media keys send the right key codes")
ok("Unknown" in call("/api/media","POST",{"key":"rm -rf"}).get("error",""), "unknown media key refused")
r=call("/api/dnd","POST",{"mode":"priority"}); ok(r.get("dnd")=="priority" and call("/api/extras")["dnd"]=="priority", f"DND on {r}")
r=call("/api/dnd","POST",{"mode":"off"}); ok(r.get("dnd")=="off", "DND off")
open(FB+"/dnd_denied","w").close(); r=call("/api/dnd","POST",{"mode":"alarms"}); os.remove(FB+"/dnd_denied")
ok("didn't change Do Not Disturb" in r.get("error","") and call("/api/extras")["dnd"]=="off", f"a phone that refuses DND is told so: {r.get('error','')[:70]}")
ok("Unknown" in call("/api/dnd","POST",{"mode":"x"}).get("error",""), "unknown DND mode refused")
open(LOG,"w").close(); r=call("/api/ring","POST",{})
ok(r.get("at")=="00:00" and "SET_ALARM" in calls() and "extra.alarm.HOUR 0" in calls() and "SKIP_UI true" in calls() and "stream 4" in calls(), f"ring sets a one-time alarm for the next minute (rolls over midnight): {r}")
ok("am start -p com.google.android.deskclock -a android.intent.action.SET_ALARM" in calls(), "ring targets one Clock app so a phone with two doesn't show a chooser")
open(FB+"/no_clock","w").close(); r=call("/api/ring","POST",{}); x=call("/api/extras"); os.remove(FB+"/no_clock")
ok("no Clock app" in r.get("error","") and x["can_ring"] is False, "no Clock app: ring is unavailable and explained")
# --- step 8: two-way folder sync
import shutil
MAC=os.path.expanduser("~/SyncTest/Docs"); PH=H+"/SyncTest"; VERS=os.path.expanduser("~/Downloads/Cellar/Sync versions")
shutil.rmtree(os.path.expanduser("~/SyncTest"),ignore_errors=True); shutil.rmtree(PH,ignore_errors=True); shutil.rmtree(VERS,ignore_errors=True)
def put(path,text,mt=None):
    os.makedirs(os.path.dirname(path),exist_ok=True); open(path,"w").write(text)
    if mt: os.utime(path,(mt,mt))
now=int(time.time())
put(MAC+"/a.txt","A",now-5000); put(MAC+"/sub/b.txt","B",now-5000); put(PH+"/c.txt","C",now-4000); put(PH+"/a.txt","A",now-3000)
r=call("/api/sync/pairs","POST",{"mac":"/nonexistent/folder","phone":PH}); ok("doesn't exist" in r.get("error",""), "pair: missing Mac folder refused")
r=call("/api/sync/pairs","POST",{"mac":os.path.expanduser("~"),"phone":PH}); ok("more specific" in r.get("error",""), "pair: whole home folder refused")
r=call("/api/sync/pairs","POST",{"mac":MAC,"phone":H}); ok("not the whole storage" in r.get("error",""), "pair: whole phone storage refused")
r=call("/api/sync/pairs","POST",{"mac":MAC,"phone":PH+"/nope"}); ok("doesn't exist on the phone" in r.get("error",""), "pair: missing phone folder refused")
pair=call("/api/sync/pairs","POST",{"mac":MAC,"phone":PH,"name":"Docs"}); pid=pair["id"]; ok(pair["confirmed"] is False and pair["name"]=="Docs", f"pair created {pair['id']}")
ok("already paired" in call("/api/sync/pairs","POST",{"mac":MAC,"phone":PH}).get("error",""), "same pair twice refused")
pv=call("/api/sync/preview",id=pid)
ok(pv["counts"]=={"push":1,"pull":1} and pv["in_sync"]==1 and {i["rel"] for i in pv["items"]}=={"sub/b.txt","c.txt"}, f"first preview: copy b to phone, c to Mac, a already identical: {pv['counts']} same={pv['in_sync']}")
ok(not os.path.exists(MAC+"/c.txt") and not os.path.exists(PH+"/sub/b.txt"), "preview changes nothing")
ok("Look over" in call("/api/sync/run","POST",{"id":pid}).get("error",""), "first sync needs the preview to be confirmed")
j=wait(call("/api/sync/run","POST",{"id":pid,"confirm":True})); ok(j["state"]=="done" and j["result"]["pushed"]==1 and j["result"]["pulled"]==1, f"first sync {j['state']} {j['result']}")
ok(open(PH+"/sub/b.txt").read()=="B" and open(MAC+"/c.txt").read()=="C", "files copied both ways")
ok(call("/api/sync/preview",id=pid)["total"]==0, "nothing to do after a sync")
# edits on each side
put(MAC+"/a.txt","AA",now+100); put(PH+"/c.txt","CC",now+200)
pv=call("/api/sync/preview",id=pid); ok(pv["counts"]=={"push":1,"pull":1}, f"edit on each side {pv['counts']}")
j=wait(call("/api/sync/run","POST",{"id":pid})); ok(open(PH+"/a.txt").read()=="AA" and open(MAC+"/c.txt").read()=="CC", f"edits copied across {j['result']}")
tr=[e["name"] for e in call("/api/trash")["entries"]]; ok("a.txt" in tr, "replaced phone file went to the Cellar Trash, not deleted")
vs=glob.glob(VERS+"/Docs/*/c.txt"); ok(len(vs)==1 and open(vs[0]).read()=="C", "replaced Mac file went to Sync versions")
# conflict: both sides edit b.txt, Mac newer
put(MAC+"/sub/b.txt","B-mac",now+400); put(PH+"/sub/b.txt","B-phone!",now+300)
pv=call("/api/sync/preview",id=pid); ok(pv["counts"]=={"conflict":1} and pv["items"][0]["winner"]=="mac", f"conflict detected, Mac newer {pv['counts']}")
j=wait(call("/api/sync/run","POST",{"id":pid}))
cm_files=[f for f in os.listdir(MAC+"/sub") if "conflict" in f]; ph_files=[f for f in os.listdir(PH+"/sub") if "conflict" in f]
ok(open(MAC+"/sub/b.txt").read()=="B-mac" and open(PH+"/sub/b.txt").read()=="B-mac" and len(cm_files)==1 and cm_files==ph_files and open(MAC+"/sub/"+cm_files[0]).read()=="B-phone!" and open(PH+"/sub/"+ph_files[0]).read()=="B-phone!", f"conflict keeps both versions on both sides: {cm_files}")
st=[p for p in call("/api/sync")["pairs"] if p["id"]==pid][0]; ok(len(st["conflicts"])==1 and st["conflicts"][0]["rel"]=="sub/b.txt" and st["last"]["conflicts"]==1, "conflict is listed on the pair")
ok(call("/api/sync/preview",id=pid)["total"]==0, "conflict copy is in step on both sides afterwards")
put(MAC+"/sub/b.txt","B-mac2",now+500); put(PH+"/sub/b.txt","B-phone-newer",now+600)
j=wait(call("/api/sync/run","POST",{"id":pid})); ok(open(MAC+"/sub/b.txt").read()=="B-phone-newer" and any(open(MAC+"/sub/"+f).read()=="B-mac2" for f in os.listdir(MAC+"/sub") if "conflict" in f and f!=cm_files[0]), "when the phone is newer, the Mac's version is kept as the conflict copy")
call("/api/sync/pairs/update","POST",{"id":pid,"dismiss_conflicts":True}); ok([p for p in call("/api/sync")["pairs"] if p["id"]==pid][0]["conflicts"]==[], "conflicts can be dismissed")
# deletions propagate, but into versions / Trash
os.remove(MAC+"/c.txt"); os.remove(PH+"/a.txt")
pv=call("/api/sync/preview",id=pid); ok(pv["counts"]=={"rm_phone":1,"rm_mac":1}, f"deletes planned {pv['counts']}")
j=wait(call("/api/sync/run","POST",{"id":pid}))
ok(not os.path.exists(PH+"/c.txt") and not os.path.exists(MAC+"/a.txt"), "deleted on one side, gone on the other")
ok(glob.glob(VERS+"/Docs/*/a.txt") and any(e["name"]=="c.txt" for e in call("/api/trash")["entries"]), "…but kept in Sync versions / the phone Trash")
# names that differ only by case can't live on a Mac
put(PH+"/X.txt","1"); put(PH+"/x.txt","2")
pv=call("/api/sync/preview",id=pid); ok({s["rel"] for s in pv["skipped"]}=={"X.txt","x.txt"} and pv["counts"]=={}, "case-only name clash is skipped with a reason")
os.remove(PH+"/X.txt"); os.remove(PH+"/x.txt")
# big deletion is flagged as risky (auto-sync would pause)
for i in range(12): put(MAC+f"/bulk/f{i}.txt",str(i),now-2000)
wait(call("/api/sync/run","POST",{"id":pid})); shutil.rmtree(MAC+"/bulk")
pv=call("/api/sync/preview",id=pid); ok(pv["risky"] is True and pv["counts"]=={"rm_phone":12}, f"12 deletions flagged risky {pv['counts']}")
# manifest lost: nothing is deleted, everything is treated as new
os.remove(os.path.expanduser("~/Library/Application Support/Cellar/sync/"+pid+".json"))
pv=call("/api/sync/preview",id=pid); ok("rm_mac" not in pv["counts"] and "rm_phone" not in pv["counts"], f"with no history, nothing is planned for deletion {pv['counts']}")
ok(call("/api/sync/pairs/delete","POST",{"id":pid}).get("ok") and call("/api/sync")["pairs"]==[], "pair removed; files untouched")
shutil.rmtree(os.path.expanduser("~/SyncTest"),ignore_errors=True); shutil.rmtree(PH,ignore_errors=True)
# --- Finder (WebDAV) now serves SD cards as a folder next to the internal folders
def dav(method, path, body=None, headers=None):
    req=urllib.request.Request(B+path, data=body, method=method, headers=headers or {})
    try:
        r=urllib.request.urlopen(req, timeout=30); return r.status, r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8","replace")
V="/dav/Google%20Pixel%208%20Pro"
c,t=dav("PROPFIND",V+"/",headers={"Depth":"1"}); ok(c==207 and V+"/SD%20card/" in t and V+"/Documents/" in t, f"Finder root lists the SD card beside internal folders ({c})")
c,t=dav("PROPFIND",V+"/SD%20card/",headers={"Depth":"1"}); ok(c==207 and V+"/SD%20card/Documents/" in t and "quota-available-bytes" in t, "SD card folder lists its contents and free space")
c,t=dav("GET",V+"/SD%20card/Documents/sd-notes.txt"); ok(c==200 and t=="on the card", "Finder can read a file on the card")
c,_=dav("PUT",V+"/SD%20card/Documents/from-finder.txt",body=b"hello card"); ok(c in (201,204) and open(SD+"/Documents/from-finder.txt").read()=="hello card", f"Finder can write to the card ({c})")
c,_=dav("DELETE",V+"/SD%20card/Documents/from-finder.txt"); ok(c==204 and not os.path.exists(SD+"/Documents/from-finder.txt") and len(os.listdir(SD+"/.CellarTrash"))>=1, "deleting from Finder uses the card's own Trash")
c,_=dav("DELETE",V+"/SD%20card"); ok(c==403 and os.path.isdir(SD), "the card itself can't be deleted from Finder")
c,_=dav("MOVE",V+"/Documents/hi.txt",headers={"Destination":B+V+"/SD%20card/Documents/hi.txt"}); ok(c in (201,204) and os.path.exists(SD+"/Documents/hi.txt") and not os.path.exists(H+"/Documents/hi.txt"), f"move from internal storage to the card ({c})")
shutil.move(SD+"/Documents/hi.txt",H+"/Documents/hi.txt"); call("/api/trash/empty","POST",{})
# --- Geist ships with the app and is inlined, so the look works offline
page=urllib.request.urlopen(B+"/").read().decode(); ok("@font-face{font-family:Geist;src:url(data:font/woff2;base64," in page and "__GEIST__" not in page, "Geist font is bundled into the page")
