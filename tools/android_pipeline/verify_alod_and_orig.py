import os, sys, struct, re, json

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
ORIG_AIGISPULL = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\orig\aigispull"
FULL_DUMP = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\full_dump"
PACK_DATA = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\pack\data"

print("=== 1. Check available clean originals ===")
print("orig/aigispull:", len(os.listdir(ORIG_AIGISPULL)) if os.path.isdir(ORIG_AIGISPULL) else 0)
print("orig sample:", sorted(os.listdir(ORIG_AIGISPULL))[:15] if os.path.isdir(ORIG_AIGISPULL) else [])
print("full_dump count:", len(os.listdir(FULL_DUMP)))

# 2. Exact binary structure of ALOD (inspect BattleResult.aod & MainPanel.aod & DataRemoveTop.aod)
def inspect_alod_exact(aar_name, aod_name):
    raw = open(os.path.join(DATA_DIR, aar_name), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    for e in af.parse_alar_v3(dec):
        if e.name == aod_name:
            d = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
            magic = d[:4]
            ver, form, obj_cnt, unk = struct.unpack_from("<BBHH", d, 4)
            print(f"\n=== ALOD {aar_name}/{aod_name} (size={len(d)}, ver={ver}, form={form}, u6={obj_cnt:#x}, u8={unk:#x}) ===")
            # Look at bytes 0x00..0x80
            print("  hdr[0:48]:", d[:48].hex(" "))
            # Look at the component ID pattern `TX01TX  ` or `WD01WD  `
            for m in re.finditer(rb"(TX|WD|SP|BT)[A-Z0-9_]{2}\1[A-Z0-9_ ]{2}", d):
                pos = m.start()
                # Print 64 bytes before the component tag to see where the string lives!
                seg = d[max(0, pos-64):pos]
                # Find last NUL before pos
                last_nul = seg.rfind(b"\x00")
                # Actually there may be trailing padding NULs (align4)! Walk backwards past NULs:
                p_end = len(seg)
                while p_end > 0 and seg[p_end - 1] == 0:
                    p_end -= 1
                # Wait what's right before p_end?
                print(f"  tag={m.group()!r} @ 0x{pos:04x} | prev40={seg[-40:].hex(' ')} | repr={seg[-32:]!r}")

inspect_alod_exact("Battle.aar", "BattleResult.aod")
inspect_alod_exact("DataRemove.aar", "DataRemoveTop.aod")
inspect_alod_exact("TempleTopMenu.aar", "TempleTopBanner.aod")
