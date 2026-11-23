import os, sys, re, struct, json

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"

# 1. Inspect HarlemEventText1.aar binary structure
h1_path = os.path.join(DATA_DIR, "HarlemEventText1.aar")
raw1 = open(h1_path, "rb").read()
dec1 = af.decompress_all4(raw1)[2] if af.is_all4(raw1) else raw1
print("=== 1. HarlemEventText1.aar header & TOC inspection ===")
print("First 128 bytes hex:", dec1[:128].hex(" "))
print("Bytes 128..256 ascii:", repr(dec1[128:256]))
# Check strings in first 4KB
for m in re.finditer(rb"EventText_[0-9_]+\.txt", dec1[:200000]):
    print(f"  found {m.group().decode()} at 0x{m.start():x}")
    if m.start() > 1000:
        break
# Print bytes around first EventText_ match
m0 = re.search(rb"EventText_[0-9_]+\.txt", dec1)
if m0:
    st = max(0, m0.start() - 32)
    print(f"  Around first entry (0x{st:x}):", repr(dec1[st:m0.end()+32]))

# 2. Inspect Battle.aar -> MainPanel.aod & MnObj_Pause.aod ALOD binary structure
print("\n=== 2. ALOD binary inspection ===")
battle_raw = open(os.path.join(DATA_DIR, "Battle.aar"), "rb").read()
battle_dec = af.decompress_all4(battle_raw)[2] if af.is_all4(battle_raw) else battle_raw
for e in af.parse_alar_v3(battle_dec):
    if e.name in ("MnObj_Pause.aod", "MainPanel.aod", "BattleResult.aod"):
        d = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
        print(f"ALOD {e.name}: len={len(d)}, head={d[:64].hex(' ')}")
        for kw in ["ゲームに戻る", "ギブアップ", "@ライフ", "@撃破数", "報酬"]:
            idx = d.find(kw.encode("utf-8"))
            if idx != -1:
                ctx = d[max(0, idx-24):idx+len(kw.encode("utf-8"))+16]
                print(f"  kw {kw!r} at 0x{idx:x}: {ctx.hex(' ')} | {ctx!r}")

# 3. Inspect why patch_manifest had gaps (dropped vs missing in glossary)
print("\n=== 3. Check 81 gap tables in WorkBuddy manifest vs device_data ===")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import patcher as P
glossary = P.ensure_glossary()
m = json.load(open(r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\build\patch_out\patch_manifest.json", encoding="utf-8"))
# Check a few top gap files in device_data
for fn in ["BattleTalkEvent200567.aar", "BattleTalkEvent920208.aar", "BattleTalkEvent100011.aar", "QuestNameText920233.atb", "QuestNameText700101.atb", "QuestNameText100101.atb"]:
    p = os.path.join(DATA_DIR, fn)
    raw = open(p, "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if fn.endswith(".aar"):
        for e in af.parse_alar_v3(dec):
            if e.name == "BattleTalkEvent.atb":
                ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
                tbl = af.parse_altb(ed)
                unmatched = []
                for r in range(tbl.count):
                    rs = tbl.get_row_strings(r)
                    for col in ["Message", "Name"]:
                        v = rs.get(col) or ""
                        if v and re.search(r"[\u3041-\u3096\u30a1-\u30fa]", v):
                            unmatched.append((r, col, v[:40], v in glossary))
                print(f"  {fn}: rows={tbl.count}, entry_sz={e.size}, still_kana={len(unmatched)}, in_gloss={sum(1 for x in unmatched if x[3])}, samples={unmatched[:3]}")
    else:
        tbl = af.parse_altb(dec)
        unmatched = []
        for r in range(tbl.count):
            v = tbl.get_row_strings(r).get("Message") or ""
            if v and v not in glossary.values():
                unmatched.append((r, v, v in glossary))
        print(f"  {fn}: rows={tbl.count}, not_in_gloss_vals={len(unmatched)}, samples={unmatched[:5]}")

# 4. Check real readable Japanese strings in libAqualeadApp.so (require >= 2 kana/kanji or known patterns)
print("\n=== 4. Clean Japanese UI literals in libAqualeadApp.so missing in MainFont ===")
so_bytes = open(r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\apk_assets\lib\arm64-v8a\libAqualeadApp.so", "rb").read()
mf = af.parse_alft(open(os.path.join(DATA_DIR, "MainFont.aft"), "rb").read())
mf_cps = set(mf.glyphs.keys())
# Import jis_level1 check from font_builder
import font_builder as fb
real_so_missing = set()
real_so_samples = []
for ck in re.findall(rb"[\x20-\x7e\x80-\xff]{4,300}\x00", so_bytes):
    try:
        s = ck[:-1].decode("utf-8", "strict")
    except Exception:
        continue
    # Must contain at least one kana or >=2 JIS L1 kanji and no weird non-JIS kanji
    has_kana = bool(re.search(r"[\u3041-\u3096\u30a1-\u30fa]", s))
    cjk_chars = [c for c in s if 0x4E00 <= ord(c) <= 0x9FFF]
    if not (has_kana or len(cjk_chars) >= 2):
        continue
    if all((0x20 <= ord(c) <= 0x7E) or fb._is_displayable_jp(ord(c)) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆\n\r\t" for c in s):
        miss = [c for c in s if ord(c) >= 0x21 and ord(c) not in mf_cps]
        if miss:
            real_so_missing.update(miss)
            real_so_samples.append((s, "".join(miss)))
print(f"Clean SO missing chars ({len(real_so_missing)}): {''.join(sorted(real_so_missing))}")
for s, mchars in real_so_samples[:20]:
    print(f"  miss={mchars!r} in {s!r}")
