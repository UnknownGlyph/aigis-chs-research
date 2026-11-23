import os, re, subprocess, tarfile, zipfile
from collections import Counter

LIST_PATH = r"C:\Users\19409\.gemini\antigravity\brain\e32544e3-fcc1-42e7-8a6a-fac252878ec1\device_nonmedia_list.txt"
ADB = r"D:\software\MuMu Player 12\nx_main\adb.exe"
SERIAL = "127.0.0.1:7555"
OUT_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync"
os.makedirs(OUT_DIR, exist_ok=True)

lines = open(LIST_PATH, encoding="utf-8-sig").read().splitlines()
prefixes = Counter()
to_pull = []
SKIP_AAR_RE = re.compile(r"^(BattleEffect_\d+|Card\d+_\d+|EnemyDot\d+|PlayerDot\d+|PromotionCard\d+|Texture\d+|Sound\d+|Unit\d+|Voice\d+)\.aar$", re.I)

for ln in lines:
    parts = ln.split()
    if len(parts) < 8 or ln.startswith("total"):
        continue
    sz = int(parts[4])
    name = parts[-1]
    pref = re.sub(r"[0-9_]+.*$", "", os.path.splitext(name)[0])
    ext = os.path.splitext(name)[1]
    prefixes[(pref, ext)] += 1
    if name.endswith(".atb") or name.endswith(".aft"):
        to_pull.append((name, sz))
    elif name.endswith(".aar") and not SKIP_AAR_RE.match(name):
        to_pull.append((name, sz))

print(f"Total non-media listed: {sum(prefixes.values())}")
for (p, e), c in prefixes.most_common(45):
    print(f"  {p+e:36s}: {c:4d}")

print(f"\nWill pull {len(to_pull)} files ({sum(s for _,s in to_pull)/1e6:.1f} MB) + MainFontFix.aft from APK...")

# Write list of filenames to pull
flist_txt = "\n".join(n for n, _ in to_pull)
tar_out = os.path.join(OUT_DIR, "sync_data.tar")

subprocess.run([ADB, "connect", SERIAL], check=True)
# Push filelist to /data/local/tmp/pull_list.txt
tmp_list = os.path.join(OUT_DIR, "_pull_list.txt")
with open(tmp_list, "w", encoding="utf-8", newline="\n") as fp:
    fp.write(flist_txt + "\n")
subprocess.run([ADB, "-s", SERIAL, "push", tmp_list, "/data/local/tmp/pull_list.txt"], check=True)

# Stream tar from device
cmd = [
    ADB, "-s", SERIAL, "exec-out",
    "su -c 'cd /data/data/com.dmm.games.aigisgp/files/data && toybox tar -cf - -T /data/local/tmp/pull_list.txt'"
]
with open(tar_out, "wb") as fp:
    p = subprocess.Popen(cmd, stdout=fp, stderr=subprocess.PIPE)
    _, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"tar failed: {err.decode(errors='replace')}")

data_dir = os.path.join(OUT_DIR, "device_data")
os.makedirs(data_dir, exist_ok=True)
count = 0
with tarfile.open(tar_out) as tf:
    for m in tf:
        if not m.isfile():
            continue
        dst = os.path.join(data_dir, os.path.basename(m.name))
        with tf.extractfile(m) as src, open(dst, "wb") as out:
            out.write(src.read())
        count += 1
print(f"Extracted {count} device data files to {data_dir}")

# Also pull MainFontFix.aft from installed base.apk on device
apk_info = subprocess.check_output([ADB, "-s", SERIAL, "shell", "pm path com.dmm.games.aigisgp"]).decode().strip()
apk_remote = apk_info.split("package:")[-1].splitlines()[0].strip()
print(f"Device APK path: {apk_remote}")
local_apk = os.path.join(OUT_DIR, "device_base.apk")
subprocess.run([ADB, "-s", SERIAL, "pull", apk_remote, local_apk], check=True)
with zipfile.ZipFile(local_apk) as z:
    for zname in z.namelist():
        if zname.endswith(".aft") or zname.endswith("libAqualeadApp.so"):
            out_p = os.path.join(OUT_DIR, "apk_assets", zname)
            os.makedirs(os.path.dirname(out_p), exist_ok=True)
            with z.open(zname) as src, open(out_p, "wb") as out:
                out.write(src.read())
            print(f"  Extracted from APK: {zname} ({os.path.getsize(out_p)} B)")
