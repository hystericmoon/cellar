import os, shutil
R = "/storage/emulated/0"
for d in [R + "/Documents", os.path.expanduser("~/Downloads/Cellar"), os.path.expanduser("~/Pictures/Cellar"), R + "/.CellarTrash"]:
    if os.path.isdir(d):
        for n in os.listdir(d):
            p = os.path.join(d, n)
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
os.makedirs(R + "/Documents/Work/Q4", exist_ok=True); open(R + "/Documents/Work/Q4/plan.txt", "w").write("q4")
open(R + "/Documents/Work/plan.txt", "w").write("plan")
shutil.copy(R + "/Download/report.pdf", R + "/Documents/report.pdf")
open(R + "/Documents/notes.txt", "w").write("Shopping list")
open(R + "/Documents/hi.txt", "w").write("hello")
for f in [os.path.expanduser("~/Library/Application Support/Cellar/" + n) for n in os.listdir(os.path.expanduser("~/Library/Application Support/Cellar")) if n.startswith("backup-")] if os.path.isdir(os.path.expanduser("~/Library/Application Support/Cellar")) else []:
    os.remove(f)
print(sorted(os.listdir(R + "/Documents")))
# test machine only: forget settings (including ones migrated from the old DroidView name)
for f in ["~/.cellar.json", "~/.droidview.json"]:
    p = os.path.expanduser(f)
    if os.path.exists(p):
        os.remove(p)
