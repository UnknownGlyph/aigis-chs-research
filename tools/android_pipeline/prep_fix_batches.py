import os, sys, re, struct, json
from collections import defaultdict

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import catalog
import patcher as P

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
ORIG_AIGISPULL = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\orig\aigispull"
FULL_DUMP = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\full_dump"
TRANS_DIR = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research\translations"
OUT_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync"

REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
JP_OR_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

glossary = P.ensure_glossary()

# 1. Check which files in DATA_DIR exist in ORIG_AIGISPULL or FULL_DUMP (note: FULL_DUMP had 46 already patched files, ORIG_AIGISPULL has the clean 46!)
clean_orig_map = {}
if os.path.isdir(ORIG_AIGISPULL):
    for fn in os.listdir(ORIG_AIGISPULL):
        clean_orig_map[fn] = os.path.join(ORIG_AIGISPULL, fn)
for fn in os.listdir(FULL_DUMP):
    if fn.endswith(".md5"): continue
    if fn not in clean_orig_map:
        clean_orig_map[fn] = os.path.join(FULL_DUMP, fn)

# Wait: what about the files that were patched in push2/3/4 (like BattleTalkEvent*, QuestNameText*, MessageText*, RewardText*)?
# Wait: FULL_DUMP was dumped at 2026-11-20 20:49, BEFORE push2/3/4 (2026-11-21)!
# So FULL_DUMP has the CLEAN UNPATCHED ORIGINALS for ALL 344 numbered tables and 115 BattleTalkEvent archives!!
# And ORIG_AIGISPULL has the clean originals for the initial 46 files!
print(f"Clean original sources mapped: {len(clean_orig_map)}")

# 2. Check why those 81 files in patch_manifest had gaps: simulate rebuild_altb_fit on clean originals!
audit = json.load(open(os.path.join(OUT_DIR, "audit_plan.json"), encoding="utf-8"))
m = json.load(open(r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\build\patch_out\patch_manifest.json", encoding="utf-8"))

drop_causes = []
for f in m["files"]:
    if "total_jp_entries" in f and f["covered_entries"] < f["total_jp_entries"]:
        name = f["name"]
        gap = f["total_jp_entries"] - f["covered_entries"]
        # Check if clean original exists
        op = clean_orig_map.get(name) or os.path.join(DATA_DIR, name)
        raw = open(op, "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        # Test exact missing vs dropped
        drop_causes.append((gap, name, f["kind"], len(raw), f["covered_entries"], f["total_jp_entries"], f["translated_entries"]))

drop_causes.sort(reverse=True)
print(f"\nTop 20 manifest gap files (check missing in glossary vs size overflow):")
for gap, name, kind, sz, cov, tot, chg in drop_causes[:20]:
    op = clean_orig_map.get(name) or os.path.join(DATA_DIR, name)
    raw = open(op, "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if name.endswith(".atb"):
        spec = next((s for s in catalog.TRANSLATABLE_TABLES if s.name == name), None)
        if spec:
            tbl = af.parse_altb(dec)
            reps, cov2, tot2, bph = P.patch_altb_with_glossary(tbl, spec.columns, glossary, {}, set())
            try:
                rebuilt, drp = P.rebuild_altb_fit(tbl, reps, len(raw), af.is_all4(raw))
            except Exception as e:
                drp = -1
            print(f"  {name:32s} gap={gap:3d} tot={tot2:4d} matched={cov2:4d} overflow_drop={drp:3d} bad_ph={bph}")
    elif name.startswith("BattleTalkEvent") and af.is_alar_v3(dec):
        for e in af.parse_alar_v3(dec):
            if e.name == "BattleTalkEvent.atb":
                ia4 = af.is_all4(e.data)
                ed = af.decompress_all4(e.data)[2] if ia4 else e.data
                tbl = af.parse_altb(ed)
                reps, cov2, tot2, bph = P.patch_altb_with_glossary(tbl, ["Message", "Name"], glossary, {}, set())
                rebuilt, drp = P.rebuild_altb_fit(tbl, reps, e.size, ia4)
                print(f"  {name:32s} gap={gap:3d} tot={tot2:4d} matched={cov2:4d} overflow_drop={drp:3d} bad_ph={bph} (entry={e.size}B, a4={ia4})")

# 3. Clean extraction of ALL ALOD strings with exact byte verification!
# How ALOD works for text controls (TXxx / WDxx / SPxx):
# Look at all verified examples: text is NUL-terminated UTF-8 string.
# Earlier `best` grabbed 1 garbage byte before UTF-8 when that byte was ASCII (0x20..0x7E, e.g. `0x40` '@' from preceding float `00 00 00 40`, or `0x3f` '?' from `00 00 80 3f`, or `0x18`..).
# Notice in ALOD records, floats always end in `3f` ('?'), `40` ('@'), `41` ('A'), `42` ('B'), `43` ('C'), `44` ('D'), or uint16/uint32 length/flags end in `00`, `01`, `02`, `0a`, `18`, etc.!
# To find the EXACT start of the UTF-8 string in `ed`:
# Any genuine CJK text string in ALOD either:
#  - starts immediately with a multibyte UTF-8 CJK/symbol char (>= 0xC2), OR
#  - starts with `[`, `1`-`9`, `y`, `★`, `※`, `・`, `(`, `/`, `「`, `『`, `?`? Wait: NEVER starts with `@` or `?` in Aigis! (Verify!)
# Wait: what about `@獲得G`? Earlier we proved at 0x629 in MainPanel.aod: `pre = ... 00 00 80 3f 01 00 00 00 00 00 00 00 00 40 [e3 83 a9 e3 82 a4 e3 83 95 00]`!
# The byte `40` was `0x00000040` (or `00 40` = 2-byte field before string!), NOT '@'!!
# Let's extract ALOD strings by taking NUL-terminated segments and stripping known binary header patterns, OR finding valid starts!
aod_clean = {}
for fn in sorted(os.listdir(DATA_DIR)):
    if not fn.endswith(".aar"): continue
    raw = open(os.path.join(DATA_DIR, fn), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if not af.is_alar_v3(dec): continue
    for e in af.parse_alar_v3(dec):
        ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
        if ed[:4] not in (b"ALOD", b"AOLD"):
            continue
        pos = 0
        while pos < len(ed):
            nul = ed.find(b"\x00", pos)
            if nul == -1: break
            seg = ed[pos:nul]
            pos = nul + 1
            if len(seg) < 3: continue
            # Find start of valid UTF-8 CJK text inside `seg`:
            # Look backwards from end of `seg` across valid UTF-8 characters, stopping before any non-printable byte or binary float/tag prefix!
            # First find earliest valid UTF-8 suffix
            start_idx = None
            for k in range(len(seg)):
                try:
                    s = seg[k:].decode("utf-8", "strict")
                except UnicodeDecodeError:
                    continue
                if not JP_OR_CJK.search(s):
                    continue
                if not all((0x20 <= ord(c) <= 0x7E) or c in "\n\r\t" or (0x3000 <= ord(c) <= 0x30FF) or (0x4E00 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆●○▲△■□◆◇※→←↑↓〇" for c in s):
                    continue
                start_idx = k
                break
            if start_idx is None:
                continue
            # Trim binary prefix bytes that happened to be printable ASCII right before a multibyte UTF-8 char!
            # Check bytes right before `start_idx` or first 1-6 bytes of `seg[start_idx:]`:
            raw_s = seg[start_idx:]
            # Common binary prefixes before ALOD strings:
            # 1) `... 00 40` -> '@' at start
            # 2) `... 80 3f` -> '?' at start
            # 3) `WD00`, `WD01`, `WD02`, `SP08`, `SP11`, `SK21`, `TWSP` (4-char widget IDs right before string without NUL!)
            # Strip 4-char widget/tag ID prefixes if followed directly by CJK/fullwidth/bracket/bullet!
            m_tag = re.match(rb"^(?:WD|SP|SK|TX|BT|TW)[A-Z0-9]{2}", raw_s)
            if m_tag and len(raw_s) > 4 and (raw_s[4] >= 0x80 or chr(raw_s[4]) in "・([「『★※"):
                raw_s = raw_s[4:]
            s = raw_s.decode("utf-8")
            # Strip spurious leading '?' or '@' or random single ASCII letter directly attached to CJK (from preceding binary field `3f`/`40`/etc)
            while len(s) >= 2 and s[0] in "@?`~^|\\#$%&*+=<>{}" and ord(s[1]) >= 0x3000:
                s = s[1:]
            # Also handle `?ID:[ID]` -> `ID:[ID]` (`?` came from `80 3f` float `1.0`!)
            if s.startswith("?ID:[ID]") or s.startswith("?1/") or s.startswith("?1日") or s.startswith("?4月"):
                s = s[1:]
            # Skip single ASCII letter prefix attached to non-ASCII if preceding byte in seg wasn't NUL and isn't numeric/unit
            if len(s) >= 2 and s[0].isalpha() and ord(s[0]) < 0x80 and not s.startswith(("yyyy", "DMM", "EP", "HP", "EXP", "Lv", "ID")):
                if ord(s[1]) >= 0x3000:
                    s = s[1:]
            if "あいうえお" in s or "＠＠＠" in s or "最大全角" in s or "最大１１文字" in s or s in ("ユニット名", "テキスト", "名前", "本文", "クエストタイトル", "５行まであり得る", "システムテキストによる説明文"):
                continue
            if not JP_OR_CJK.search(s):
                continue
            b_len = len(s.encode("utf-8"))
            rec = aod_clean.setdefault(s, {"bytes": b_len, "count": 0, "files": []})
            rec["count"] += 1
            if len(rec["files"]) < 3 and f"{fn}/{e.name}" not in rec["files"]:
                rec["files"].append(f"{fn}/{e.name}")

print(f"\nClean unique ALOD UI strings to translate: {len(aod_clean)}")
json.dump(aod_clean, open(os.path.join(OUT_DIR, "aod_clean.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for s, r in sorted(aod_clean.items())[:40]:
    print(f"  [{r['bytes']:3d}B x{r['count']:<3d}] {s!r}")
