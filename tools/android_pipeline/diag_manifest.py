import json, os

m_path = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\build\patch_out\patch_manifest.json"
m = json.load(open(m_path, encoding="utf-8"))
partial = [f for f in m["files"] if "total_jp_entries" in f and f["covered_entries"] < f["total_jp_entries"]]
print(f"Total manifest files: {len(m['files'])}, Partial/dropped files: {len(partial)}")
for f in sorted(partial, key=lambda x: x["total_jp_entries"] - x["covered_entries"], reverse=True):
    print(f"  {f['name']:36s} {f['covered_entries']:5d}/{f['total_jp_entries']:5d} (gap={f['total_jp_entries']-f['covered_entries']:4d}, chg={f['translated_entries']})")
