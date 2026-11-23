import os, sys, re, struct, json
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import catalog
import patcher as P

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
ORIG_DIR = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\full_dump"
OUT_JSON = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\audit_plan.json"
OUT_TXT = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\audit_plan.txt"

KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
# Exclude middot and prolonged sound mark which appear legitimately in translated names: ・ ー
REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")

glossary = P.ensure_glossary()
lines = []
def log(s=""):
    lines.append(s)

# 1. Check questionable small config tables to confirm which columns are display vs logic
log("=== 1. AUDIT CONFIG TABLES (DISPLAY VS LOGIC) ===")
for fn in ["EnemyElem.atb", "EnemyType.atb", "QuestTermConfig.atb", "CfgSkillInfluenceId.atb", "CfgSkillTargetId.atb", "TrustBoostConfigTable.atb", "PresentFilterConfig.atb", "SpecialEffects.atb"]:
    p = os.path.join(DATA_DIR, fn)
    if not os.path.exists(p): continue
    raw = open(p, "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    t = af.parse_altb(dec)
    cols = [f.name_en for f in t.string_fields()]
    log(f"Table {fn} (rows={t.count}) cols={cols}")
    for r in range(min(6, t.count)):
        rs = t.get_row_strings(r)
        if any(rs.values()):
            log(f"  row[{r}]: {rs}")

# 2. Check HarlemEventText0 vs paev03
log("\n=== 2. HARLEM EVENT TEXT 0 vs PAEV03 CHECK ===")
h0_raw = open(os.path.join(DATA_DIR, "HarlemEventText0.aar"), "rb").read()
h0_dec = af.decompress_all4(h0_raw)[2] if af.is_all4(h0_raw) else h0_raw
h0_ents = af.parse_alar_v3(h0_dec)
log(f"HarlemEventText0 entries={len(h0_ents)}: {[e.name for e in h0_ents[:5]]}")
for e in h0_ents[:2]:
    txt = e.data.decode("utf-8-sig", errors="replace")
    log(f"  [{e.name}] first 150 chars: {txt[:150].replace(chr(10), ' | ')}")

# Also parse HarlemEventText1.aar sequentially by reading entry headers starting at 18 + cnt*2?
h1_raw = open(os.path.join(DATA_DIR, "HarlemEventText1.aar"), "rb").read()
h1_dec = af.decompress_all4(h1_raw)[2] if af.is_all4(h1_raw) else h1_raw
cnt1 = struct.unpack_from("<H", h1_dec, 6)[0]
pos = 18 + cnt1 * 2
# Look at 0x1a74: 18 + 3377*2 = 0x1a74! At 0x1a74 was '7d 8a', and entry 0 started at 0x1a76? Wait check why +2!
# Scan for pattern \x01\x00\x00\x80..\x00EventText_
m_h1 = list(re.finditer(rb"EventText_\d+_\d+\.txt\x00", h1_dec[:200000]))
log(f"HarlemEventText1.aar EventText_* matches in first 200KB: {len(m_h1)}")
if m_h1:
    m0 = m_h1[0]
    eh = m0.start() - 18
    idx, u2, foff, fsz, ffl = struct.unpack_from("<HHIII", h1_dec, eh)
    sample = h1_dec[foff:foff+fsz].decode("utf-8-sig", errors="replace")
    log(f"  Entry 0 name={m0.group()[:-1].decode()} foff=0x{foff:x} fsz={fsz}: {sample[:120].replace(chr(10), ' | ')}")

# 3. Check ALL display tables/archives in DATA_DIR (including NEW ones and UiText Faq/FaqDetail)
log("\n=== 3. EXACT AUDIT OF UNTRANSLATED / KANA-MIXED / DROPPED ITEMS ===")
# Collect all files matching display rules
all_files = sorted(os.listdir(DATA_DIR))
specs = []
# Load base specs with UiText updated to include Faq, FaqDetail
for s in catalog.TRANSLATABLE_TABLES:
    if s.name == "UiText.atb":
        specs.append(("atb", s.name, ["Caption", "Help", "HelpMessage", "Faq", "FaqDetail"]))
    else:
        specs.append(("atb", s.name, list(s.columns)))

known_atb = {x[1] for x in specs}
for fn in all_files:
    if fn in known_atb:
        continue
    if re.fullmatch(r"MessageText\d+\.atb", fn):
        specs.append(("atb", fn, ["Message"]))
    elif re.fullmatch(r"QuestNameText\d+\.atb", fn):
        specs.append(("atb", fn, ["Message"]))
    elif re.fullmatch(r"RewardText\d+\.atb", fn):
        specs.append(("atb", fn, ["Text"]))

aar_specs = []
known_aar = set()
for a in catalog.ALAR_ARCHIVES:
    aar_specs.append((a.name, a.mode, a.target_entry, list(a.columns)))
    known_aar.add(a.name)
for fn in all_files:
    if fn not in known_aar and re.fullmatch(r"BattleTalkEvent\d+\.aar", fn):
        aar_specs.append((fn, "direct_atb", "BattleTalkEvent.atb", ["Message", "Name"]))

# Check every entry: classify into:
# - untrans_orig: still matching raw original Japanese (either never translated or dropped or new file)
# - broken_zh: translated text that STILL contains REAL_KANA (e.g. さん, ちゃん, の, ク莉亚, プロ盗贼)
# - pure_kanji_jp: no kana, not in glossary values and looks like untranslated JP
untrans_strings = set()
broken_zh_map = {}  # broken_zh -> list of (file, col)
dropped_from_gloss = defaultdict(list)

# Build set of known valid zh values for quick lookup
zh_values = set(glossary.values())

def inspect_tbl(fn, tbl, cols):
    # Also load original table if available in ORIG_DIR so we know what the original JP was for broken_zh!
    orig_tbl = None
    orig_p = os.path.join(ORIG_DIR, fn)
    if os.path.exists(orig_p) and fn.endswith(".atb"):
        try:
            oraw = open(orig_p, "rb").read()
            odec = af.decompress_all4(oraw)[2] if af.is_all4(oraw) else oraw
            orig_tbl = af.parse_altb(odec)
        except Exception:
            pass
    _check_rows(fn, tbl, orig_tbl, cols)

def _check_rows(fn, tbl, orig_tbl, cols):
    if not (tbl.form & 0x04):
        return
    fields = {f.name_en for f in tbl.string_fields()}
    use_cols = [c for c in cols if c in fields]
    for r in range(tbl.count):
        rs = tbl.get_row_strings(r)
        ors = orig_tbl.get_row_strings(r) if orig_tbl and r < orig_tbl.count else {}
        for c in use_cols:
            val = rs.get(c) or ""
            if not val:
                continue
            orig_val = ors.get(c) or ""
            # Case 1: exact match to a glossary key (meaning untranslated or dropped!)
            if val in glossary and glossary[val] != val:
                dropped_from_gloss[fn].append((r, c, val[:50]))
            # Case 2: contains real kana (hiragana or non-middot/non-dash katakana)
            elif REAL_KANA_RE.search(val):
                # Check if orig_val exists and differs (meaning a partial/dirty MT translation!)
                if orig_val and orig_val != val:
                    broken_zh_map.setdefault(val, []).append((fn, r, c, orig_val))
                elif val in zh_values:
                    # A dirty translation in glossary!
                    broken_zh_map.setdefault(val, []).append((fn, r, c, orig_val or val))
                else:
                    untrans_strings.add(val)
            # Case 3: Pure kanji (no kana), check if it matches original JP (or is in new files) and wasn't translated
            elif CJK_RE.search(val):
                # Check if original == val and val not in glossary.values() (except single/short terms that are identical in CN/JP like "魔王城", "初級" vs "初级")
                if orig_val == val and val not in zh_values:
                    untrans_strings.add(val)
                elif not orig_val and val not in zh_values:
                    # New file with kanji-only string
                    untrans_strings.add(val)

for _, fn, cols in specs:
    p = os.path.join(DATA_DIR, fn)
    if not os.path.exists(p): continue
    raw = open(p, "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if dec[:4] == b"ALTB":
        inspect_tbl(fn, af.parse_altb(dec), cols)

for fn, mode, target, cols in aar_specs:
    p = os.path.join(DATA_DIR, fn)
    if not os.path.exists(p): continue
    raw = open(p, "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if not af.is_alar_v3(dec): continue
    orig_map = {}
    op = os.path.join(ORIG_DIR, fn)
    if os.path.exists(op):
        try:
            oraw = open(op, "rb").read()
            odec = af.decompress_all4(oraw)[2] if af.is_all4(oraw) else oraw
            for oe in af.parse_alar_v3(odec):
                orig_map[oe.name] = oe.data
        except Exception:
            pass
    for e in af.parse_alar_v3(dec):
        if mode == "direct_atb" and e.name == target:
            ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
            otbl = None
            if e.name in orig_map:
                oed = af.decompress_all4(orig_map[e.name])[2] if af.is_all4(orig_map[e.name]) else orig_map[e.name]
                otbl = af.parse_altb(oed)
            _check_rows(fn, af.parse_altb(ed), otbl, cols)
        elif mode == "nested_evtxt" and af.is_alar_v3(e.data):
            osubs = {}
            if e.name in orig_map and af.is_alar_v3(orig_map[e.name]):
                for ose in af.parse_alar_v3(orig_map[e.name]):
                    osubs[ose.name] = ose.data
            for se in af.parse_alar_v3(e.data):
                if se.name.endswith(target):
                    ed = af.decompress_all4(se.data)[2] if af.is_all4(se.data) else se.data
                    if ed[:4] == b"ALTB":
                        otbl = None
                        if se.name in osubs:
                            oed = af.decompress_all4(osubs[se.name])[2] if af.is_all4(osubs[se.name]) else osubs[se.name]
                            if oed[:4] == b"ALTB":
                                otbl = af.parse_altb(oed)
                        _check_rows(f"{fn}/{e.name}", af.parse_altb(ed), otbl, cols)

log(f"1) Dropped / still in glossary key (not applied to live device files): {sum(len(v) for v in dropped_from_gloss.values())} rows across {len(dropped_from_gloss)} files")
for fn, items in sorted(dropped_from_gloss.items(), key=lambda kv: -len(kv[1]))[:25]:
    log(f"   {fn:34s}: {len(items):4d} rows  ex={items[0]}")

log(f"\n2) Dirty/partial translations containing kana (broken_zh): {len(broken_zh_map)} unique strings")
for bz, occs in list(broken_zh_map.items())[:35]:
    log(f"   {bz[:60]!r}  (orig={occs[0][3][:40]!r}) [{occs[0][0]}]")

log(f"\n3) Completely untranslated display strings (new files / missed pure-kanji / etc): {len(untrans_strings)} unique strings")
# Group by Kana vs Pure-Kanji
u_kana = sorted(s for s in untrans_strings if REAL_KANA_RE.search(s))
u_kanji = sorted(s for s in untrans_strings if not REAL_KANA_RE.search(s))
log(f"   with kana: {len(u_kana)}, pure-kanji/no-kana: {len(u_kanji)}")
for s in u_kana[:25]:
    log(f"   KANA_UNTRANS: {s[:70]!r}")
for s in u_kanji[:35]:
    log(f"   KANJI_ONLY  : {s[:70]!r}")

# 4. Also check ALL dirty entries in glossary_values directly! (e.g. "ク莉亚", "プロ盗贼", "さん", "ちゃん", "の")
dirty_in_glossary = []
# Check glossary entries where JP had kana/text and ZH still contains kana or bad artifacts
for k, v in glossary.items():
    if REAL_KANA_RE.search(v):
        # Ignore intentional kana matching puzzles like 「ヨ,ロ,シ,ク」 or 「ア,イ,ウ,エ,オ」 or Japanese title quotes
        if re.search(r"「[ァ-ヶ,]+」", v):
            continue
        dirty_in_glossary.append((k, v))
    elif "ク莉亚" in v or "プロ盗贼" in v or "专业盗贼" in v:
        dirty_in_glossary.append((k, v))

log(f"\n4) Dirty entries inside existing translations/*.json: {len(dirty_in_glossary)}")
for k, v in dirty_in_glossary[:30]:
    log(f"   GLOSS_DIRTY: {k[:35]!r} -> {v[:45]!r}")

with open(OUT_TXT, "w", encoding="utf-8") as fp:
    fp.write("\n".join(lines))

# Save machine-readable lists for next step
json.dump({
    "untrans_kana": u_kana,
    "untrans_kanji": u_kanji,
    "broken_zh_occs": {k: v[0] for k, v in broken_zh_map.items()},
    "dirty_glossary": dirty_in_glossary,
    "dropped_files": {k: len(v) for k, v in dropped_from_gloss.items()},
}, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print(f"Wrote {OUT_TXT} ({len(lines)} lines) and {OUT_JSON}")
