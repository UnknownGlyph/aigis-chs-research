import os, sys, json, re

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import build_android_complete as B

glossary, _, _ = B.load_merged_translations()
orig_map = B.get_clean_orig_map()

for fn in ["QuestNameText100008.atb", "QuestNameText100009.atb", "QuestNameText700101.atb", "QuestNameText910001.atb", "QuestNameText920233.atb"]:
    raw = open(orig_map[fn], "rb").read()
    is_a4 = af.is_all4(raw)
    tbl = af.parse_altb(af.decompress_all4(raw)[2] if is_a4 else raw)
    print(f"=== {fn} (orig_size={len(raw)}, a4={is_a4}, rows={tbl.count}) ===")
    for r in range(tbl.count):
        jp = tbl.get_row_strings(r).get("Message") or ""
        zh = glossary.get(jp, "<MISSING>")
        jp_b = len(jp.encode("utf-8"))
        zh_b = len(zh.encode("utf-8"))
        mark = "OVER" if zh_b > jp_b else "ok"
        print(f"  [{r:2d}] ({jp_b:2d}->{zh_b:2d}B {mark:4s}) {jp!r:28s} => {zh!r}")
