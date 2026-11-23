import os, sys, re, struct, json
from collections import defaultdict

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
SO_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\apk_assets\lib\arm64-v8a\libAqualeadApp.so"
MAINFONT_PATH = os.path.join(DATA_DIR, "MainFont.aft")
OUT_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\diag_deep.txt"

mf = af.parse_alft(open(MAINFONT_PATH, "rb").read())
mf_cps = set(mf.glyphs.keys())

out = []
def log(s=""):
    out.append(s)

# 1. Scan libAqualeadApp.so for null-terminated UTF-8 strings containing Japanese/CJK
log("=== 1. libAqualeadApp.so EMBEDDED CJK UTF-8 STRINGS ===")
so_bytes = open(SO_PATH, "rb").read()
# Find contiguous printable UTF-8 C-strings in .rodata / binary
KANA_OR_JP = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
# Extract NUL-delimited byte chunks from binary
chunks = re.findall(rb"[\x20-\x7e\x80-\xff]{3,300}\x00", so_bytes)
so_strings = []
so_missing_cps = set()
seen_so = set()
for ck in chunks:
    raw = ck[:-1]
    try:
        s = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        continue
    if KANA_OR_JP.search(s):
        # Filter obvious false UTF-8 coincidences: require valid CJK/ASCII ratio and no weird private/surrogate/hangul
        if all((0x20 <= ord(c) <= 0x7E) or (0x3000 <= ord(c) <= 0x30FF) or (0x4E00 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆●○▲△■□◆◇※→←↑↓\n\r\t" for c in s):
            if s not in seen_so:
                seen_so.add(s)
                so_strings.append(s)
                for c in s:
                    if ord(c) >= 0x21 and ord(c) not in mf_cps:
                        so_missing_cps.add(c)

log(f"Found {len(so_strings)} clean CJK C-strings in libAqualeadApp.so")
log(f"Chars from .so strings MISSING in device MainFont.aft ({len(so_missing_cps)}): {''.join(sorted(so_missing_cps))}")
for s in so_strings[:100]:
    log("  SO: " + repr(s))

# 2. Check specific unknown / un-audited ATB and AAR files in device_data
log("\n=== 2. SPECIFIC UN-AUDITED FILES & AOD LAYOUT STRINGS ===")
interesting_files = [
    "AwakeningText.atb", "BeginnerBonus.atb", "Battle.aar",
    "AnnounceMenu.aar", "BackButtonMenu.aar", "BattleGodBlessListMenu.aar",
    "DataLink.aar", "DataRemove.aar", "LoginAll.aar",
    "ShopMenu.aar", "MissionTopMenu.aar", "TempleTopMenu.aar",
]
# Also add HarlemEventText*.aar, pcev*.aar, EvtCard*.aar, OnCommand*.atb, QuestTermConfig.atb, Shop*.atb
for fn in sorted(os.listdir(DATA_DIR)):
    if re.match(r"^(HarlemEventText|pcev|EvtCard|OnCommand|QuestTermConfig|Shop|Tower|Coop|AssaultMissionQuestList|BattleMenuLayout|SpecialEffects)", fn):
        if fn not in interesting_files and fn.endswith((".atb", ".aar")):
            interesting_files.append(fn)

def inspect_blob(label, data, depth=0):
    if depth > 4 or len(data) < 8:
        return
    h = data[:4]
    if h == b"ALL4":
        try:
            _, _, dec = af.decompress_all4(data)
            inspect_blob(label, dec, depth + 1)
        except Exception as e:
            log(f"  [{label}] ALL4 err: {e}")
    elif h == b"ALAR" and af.is_alar_v3(data):
        try:
            ents = af.parse_alar_v3(data)
            log(f"  [{label}] ALAR v3 entries={len(ents)}: {[e.name for e in ents[:12]]}")
            for e in ents:
                inspect_blob(f"{label}/{e.name}", e.data, depth + 1)
        except Exception as e:
            log(f"  [{label}] ALAR err: {e}")
    elif h == b"ALTB":
        try:
            t = af.parse_altb(data)
            sf = [f.name_en for f in t.string_fields()]
            samples = []
            for r in range(min(t.count, 5)):
                samples.append(t.get_row_strings(r))
            log(f"  [{label}] ALTB rows={t.count} str_cols={sf} samples={samples[:2]}")
        except Exception as e:
            log(f"  [{label}] ALTB err: {e}")
    elif h in (b"ALOD", b"AOLD"):
        # Search for CJK strings inside ALOD layout
        strs = []
        for ck in re.findall(rb"[\x20-\x7e\x80-\xff]{3,200}\x00", data):
            try:
                s = ck[:-1].decode("utf-8", "strict")
            except Exception:
                continue
            if KANA_OR_JP.search(s) and all((0x20 <= ord(c) <= 0x7E) or (0x3000 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆\n" for c in s):
                strs.append(s)
        if strs:
            log(f"  [{label}] ALOD layout CJK strings ({len(strs)}): {strs[:25]}")
    elif h == b"ALTX":
        pass
    else:
        # Check if raw unknown format has UTF-8 text
        if len(data) < 200000:
            found = []
            for ck in re.findall(rb"[\x20-\x7e\x80-\xff]{3,200}\x00", data):
                try:
                    s = ck[:-1].decode("utf-8", "strict")
                except Exception:
                    continue
                if KANA_OR_JP.search(s) and all((0x20 <= ord(c) <= 0x7E) or (0x3000 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆\n" for c in s):
                    found.append(s)
            if found:
                log(f"  [{label}] RAW({h!r}, {len(data)}B) CJK strings: {found[:10]}")

for fn in interesting_files:
    p = os.path.join(DATA_DIR, fn)
    if os.path.exists(p):
        inspect_blob(fn, open(p, "rb").read())

with open(OUT_PATH, "w", encoding="utf-8") as fp:
    fp.write("\n".join(out))
print(f"Done. Wrote {len(out)} lines to {OUT_PATH}")
