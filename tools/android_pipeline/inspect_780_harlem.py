import os, sys, struct, re, json
sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import build_android_complete as B

glossary, _, harlem_dict = B.load_merged_translations()
orig_map = B.get_clean_orig_map()

for hfn in ("HarlemEventText0.aar", "HarlemEventText1.aar"):
    raw = open(orig_map[hfn], "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    cnt = struct.unpack_from("<H", dec, 6)[0]
    pos = 18 + cnt * 2
    seen = set()
    for _ in range(cnt):
        idx, u2, foff, fsz, fflags = struct.unpack_from("<HHIII", dec, pos)
        nend = dec.find(b"\x00", pos + 18)
        fn = dec[pos + 18 : nend].decode("utf-8", errors="replace")
        pos = af.align4(nend + 1)
        if fsz in (704, 706, 780, 782) and (hfn, fsz) not in seen:
            txt = dec[foff:foff+fsz].decode("utf-8-sig", errors="replace")
            if "イベント" in txt or "未" in txt or len(txt.strip()) > 10:
                seen.add((hfn, fsz))
                print(f"=== {hfn}/{fn} ({fsz}B) ===")
                print(repr(txt[:300]))
                for part in re.split(r"\r?\n\r?\n+", txt):
                    p = part.strip()
                    if p and p in harlem_dict:
                        print("  BLK_ZH:", repr(harlem_dict[p]))
