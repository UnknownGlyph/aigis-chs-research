import os, sys, re, struct, json
from collections import defaultdict, Counter

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
OUT_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\diag_remaining.txt"

KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
JP_OR_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

out = []
def log(s=""):
    out.append(s)

# 1. Inspect HarlemEventText0, HarlemEventText1, pcev*, LoginAll headers
log("=== 1. HARLEM & PCEV & LOGIN ARCHIVES ===")
for fn in sorted(os.listdir(DATA_DIR)):
    if re.match(r"^(HarlemEventText|pcev|paev|pevconfig|LoginAll)", fn):
        p = os.path.join(DATA_DIR, fn)
        raw = open(p, "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        log(f"File: {fn} size={len(raw)} dec_head={dec[:16]!r}")
        if dec[:4] == b"ALAR":
            ver = dec[4]
            log(f"  ALAR ver={ver}, ver_byte5={dec[5]}, cnt={struct.unpack_from('<H', dec, 6)[0]}")
            if af.is_alar_v3(dec):
                ents = af.parse_alar_v3(dec)
                log(f"  entries={len(ents)}: {[e.name for e in ents[:6]]}")
                if ents:
                    e0 = ents[0]
                    d0 = af.decompress_all4(e0.data)[2] if af.is_all4(e0.data) else e0.data
                    log(f"    entry[0] {e0.name} size={len(e0.data)} dec_head={d0[:16]!r}")
                    if e0.name.endswith(".txt"):
                        log("    txt sample: " + d0[:200].decode("utf-8", errors="replace").replace("\n", "\\n"))
            elif ver == 2:
                # Try parsing ALAR v2: header 16B: magic(4), ver(1), flags(1), cnt(2), unk(8)?
                cnt = struct.unpack_from("<H", dec, 6)[0]
                log(f"  ALAR v2 hex header: {dec[:64].hex()}")

# 2. Scan ALL .aar files in DATA_DIR for .aod (ALOD) files with Japanese UI strings
log("\n=== 2. ALL ALOD (.aod) FILES WITH CJK STRINGS ===")
aod_strings = {}  # (aar_name, aod_name) -> list of strings
all_aod_files = 0
def walk_for_aod(aar_name, prefix, data, depth=0):
    global all_aod_files
    if depth > 4 or len(data) < 8:
        return
    h = data[:4]
    if h == b"ALL4":
        try:
            walk_for_aod(aar_name, prefix, af.decompress_all4(data)[2], depth+1)
        except Exception:
            pass
    elif h == b"ALAR" and af.is_alar_v3(data):
        try:
            for e in af.parse_alar_v3(data):
                subp = f"{prefix}/{e.name}" if prefix else e.name
                walk_for_aod(aar_name, subp, e.data, depth+1)
        except Exception:
            pass
    elif h in (b"ALOD", b"AOLD"):
        all_aod_files += 1
        strs = []
        for ck in re.findall(rb"[\x20-\x7e\x80-\xff]{2,200}\x00", data):
            try:
                s = ck[:-1].decode("utf-8", "strict")
            except Exception:
                continue
            if JP_OR_CJK.search(s) and all((0x20 <= ord(c) <= 0x7E) or (0x3000 <= ord(c) <= 0x30FF) or (0x4E00 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆●○▲△■□◆◇※→←↑↓\n" for c in s):
                # Exclude technical property keys? Keep anything with kana or common UI labels
                strs.append(s)
        if strs:
            aod_strings[(aar_name, prefix)] = strs

for fn in sorted(os.listdir(DATA_DIR)):
    if fn.endswith(".aar"):
        raw = open(os.path.join(DATA_DIR, fn), "rb").read()
        walk_for_aod(fn, "", raw, 0)

log(f"Total ALOD files scanned: {all_aod_files}, with CJK strings: {len(aod_strings)}")
unique_aod_texts = Counter()
for (aar, aod), strs in sorted(aod_strings.items()):
    for s in strs:
        unique_aod_texts[s] += 1
log(f"Unique ALOD CJK strings: {len(unique_aod_texts)}")
for (aar, aod), strs in sorted(aod_strings.items())[:80]:
    log(f"  {aar}::{aod} -> {strs[:10]}")

# 3. Inspect why manifest had gaps & which files are untranslated in device_data
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import catalog
import patcher as P

glossary = P.ensure_glossary()
log(f"\n=== 3. DEVICE DISPLAY-COLUMN AUDIT (CURRENT DEVICE FILES) ===")

# Audit every spec + newly downloaded QuestNameText/MessageText/RewardText/BattleTalkEvent
all_files = sorted(os.listdir(DATA_DIR))
untranslated_samples = defaultdict(list)
table_gaps = []

def audit_table(fn, tbl, cols):
    jp_rows = 0
    untrans_kana = 0
    untrans_no_kana = 0
    samples = []
    for r in range(tbl.count):
        rs = tbl.get_row_strings(r)
        for col in cols:
            v = rs.get(col) or ""
            if not v:
                continue
            has_kana = bool(KANA_RE.search(v))
            has_jp = bool(JP_OR_CJK.search(v))
            if has_kana:
                jp_rows += 1
                untrans_kana += 1
                if len(samples) < 3:
                    samples.append((col, v.replace("\n", "\\n")[:60]))
            elif has_jp and v not in glossary and v not in glossary.values():
                # Could be pure kanji JP or already translated? Check if in glossary values or has JP-only chars
                pass
    return jp_rows, untrans_kana, samples

# Check all ATB and BattleTalkEvent files matching patterns
CHECK_PATS = [
    (r"^BattleTalkEvent\d+\.aar$", ["Message", "Name"], "aar_bt"),
    (r"^MessageText\d*\.atb$", ["Message"], "atb"),
    (r"^QuestNameText\d*\.atb$", ["Message"], "atb"),
    (r"^RewardText\d*\.atb$", ["Text"], "atb"),
    (r"^UiText\.atb$", ["Caption", "Help", "HelpMessage", "Faq", "FaqDetail"], "atb"),
    (r"^Shop2ItemV2\.atb$", ["ProductName"], "atb"),
    (r"^SpecialEffectsType\.atb$", ["Name", "Effect", "Target"], "atb"),
    (r"^QuestEventText\.atb$", ["Message", "Name"], "atb"),
    (r"^StatusText\.atb$", ["Message"], "atb"),
    (r"^SkillList\.atb$", ["SkillName"], "atb"),
    (r"^SkillText\.atb$", ["Data_Text"], "atb"),
    (r"^AbilityList\.atb$", ["AbilityName"], "atb"),
    (r"^AbilityText\.atb$", ["AbilityText"], "atb"),
    (r"^NameText\.atb$", ["Message", "RealName"], "atb"),
    (r"^SystemText\.atb$", ["Data_Text"], "atb"),
    (r"^PlayerUnitTable\.aar$", ["Name", "Explanation"], "aar_cls"),
    (r"^EventArc\.aar$", ["_TalkerName", "_TalkText"], "aar_ev"),
    (r"^EventHomeArc\.aar$", ["_TalkerName", "_TalkText"], "aar_ev"),
    (r"^paev03\.aar$", ["_TalkerName", "_TalkText"], "aar_ev"),
]

# Track known specs in catalog
known_names = {s.name for s in catalog.TRANSLATABLE_TABLES} | {a.name for a in catalog.ALAR_ARCHIVES}

for fn in all_files:
    for pat, cols, kind in CHECK_PATS:
        if not re.match(pat, fn):
            continue
        raw = open(os.path.join(DATA_DIR, fn), "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        in_cat = fn in known_names
        if kind == "atb" and dec[:4] == b"ALTB":
            t = af.parse_altb(dec)
            _, uk, smp = audit_table(fn, t, cols)
            if uk > 0 or not in_cat:
                table_gaps.append((fn, in_cat, uk, t.count, smp))
        elif kind == "aar_bt" and af.is_alar_v3(dec):
            uk_tot = 0; tot_r = 0; smp_all = []
            for e in af.parse_alar_v3(dec):
                if e.name == "BattleTalkEvent.atb":
                    ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
                    t = af.parse_altb(ed)
                    _, uk, smp = audit_table(fn, t, cols)
                    uk_tot += uk; tot_r += t.count; smp_all.extend(smp)
            if uk_tot > 0 or not in_cat:
                table_gaps.append((fn, in_cat, uk_tot, tot_r, smp_all[:3]))
        elif kind == "aar_ev" and af.is_alar_v3(dec):
            uk_tot = 0; tot_r = 0; smp_all = []
            for e in af.parse_alar_v3(dec):
                if af.is_alar_v3(e.data):
                    for se in af.parse_alar_v3(e.data):
                        if se.name.endswith("evtxt.atb"):
                            ed = af.decompress_all4(se.data)[2] if af.is_all4(se.data) else se.data
                            if ed[:4] == b"ALTB":
                                t = af.parse_altb(ed)
                                _, uk, smp = audit_table(fn, t, cols)
                                uk_tot += uk; tot_r += t.count; smp_all.extend(smp)
            if uk_tot > 0:
                table_gaps.append((fn, in_cat, uk_tot, tot_r, smp_all[:3]))

log(f"Files with remaining kana or missing from catalog: {len(table_gaps)}")
for fn, in_cat, uk, tr, smp in sorted(table_gaps, key=lambda x: (-x[2], x[0])):
    log(f"  {fn:30s} in_cat={'Y' if in_cat else 'NEW'}  kana_left={uk:4d}/{tr:5d}  samples={smp[:2]}")

with open(OUT_PATH, "w", encoding="utf-8") as fp:
    fp.write("\n".join(out))
print(f"Wrote {len(out)} lines to {OUT_PATH}")
