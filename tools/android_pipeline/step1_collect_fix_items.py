import os, sys, re, json, glob
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import catalog

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
ORIG_AIGISPULL = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\orig\aigispull"
FULL_DUMP = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\full_dump"
WB_TRANS_DIR = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research\translations"
WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
os.makedirs(WORK_DIR, exist_ok=True)

REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
JP_OR_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

# Canonical originals: orig/aigispull first (unpatched 105 files), then full_dump (unpatched for 344 numbered + 115 BattleTalk), then device_data (newly downloaded)
clean_orig = {}
for base_dir in (ORIG_AIGISPULL, FULL_DUMP, DATA_DIR):
    if not os.path.isdir(base_dir): continue
    for fn in os.listdir(base_dir):
        if fn.endswith(".md5"): continue
        if fn not in clean_orig:
            clean_orig[fn] = os.path.join(base_dir, fn)

# Wait! In FULL_DUMP, 46 base tables were ALREADY patched in WorkBuddy's initial pack,
# EXCEPT they were ALSO in ORIG_AIGISPULL? Let's verify if EventArc.aar, EventHomeArc.aar, paev03.aar, QuestEventText.atb were in ORIG_AIGISPULL!
# Print check for those 4 large files:
for big in ("EventArc.aar", "EventHomeArc.aar", "paev03.aar", "QuestEventText.atb", "StatusText.atb", "SystemText.atb", "UiText.atb"):
    in_orig = os.path.exists(os.path.join(ORIG_AIGISPULL, big))
    print(f"  {big:20s}: in_orig_aigispull={in_orig}")

# Load all existing translations cleanly, separating dirty ones
raw_glossary = {}
for fn in sorted(os.listdir(WB_TRANS_DIR)):
    if fn.endswith(".json"):
        try:
            d = json.load(open(os.path.join(WB_TRANS_DIR, fn), encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(k, str) and isinstance(v, str) and v:
                        raw_glossary[k] = v
        except Exception:
            pass

# Clean dirty glossary entries!
clean_glossary = {}
retrans_needed = set()  # JP keys that need proper translation

BAD_ARTIFACT_RE = re.compile(r"ク莉亚|プロ盗贼|专业盗贼|さん|ちゃん|ですぽん")
# Intentional JP puzzle condition quotes that MUST stay JP kana:
PUZZLE_KANA_RE = re.compile(r"「[ァ-ヶ,、]+」")

for k, v in raw_glossary.items():
    # If key is not JP (e.g. pure ASCII or empty), keep
    # Fix known global typos inside translations directly first!
    v_fixed = v
    if "ク莉亚" in v_fixed:
        # Usually "任务改为ク莉亚" -> need full clean retranslation of JP key
        retrans_needed.add(k)
        continue
    if "プロ盗贼" in v_fixed or "专业盗贼" in v_fixed:
        if "プロローグ" in k:
            retrans_needed.add(k)
            continue
    # Check if key == value and contains kana (identity non-translation!)
    if k == v_fixed and REAL_KANA_RE.search(k):
        retrans_needed.add(k)
        continue
    # Check if translated value still has stray hiragana/katakana (excluding puzzle quotes)
    v_stripped = PUZZLE_KANA_RE.sub("", v_fixed)
    if REAL_KANA_RE.search(v_stripped):
        retrans_needed.add(k)
        continue
    clean_glossary[k] = v_fixed

print(f"\nGlossary cleaned: kept={len(clean_glossary)}, flagged for re-translation={len(retrans_needed)}")

# Now scan EVERY file on device / clean_orig matching display tables & archives
all_files = sorted(clean_orig.keys())
atb_rules = []
for s in catalog.TRANSLATABLE_TABLES:
    if s.name == "UiText.atb":
        atb_rules.append((s.name, ["Caption", "Help", "HelpMessage", "Faq", "FaqDetail"]))
    else:
        atb_rules.append((s.name, list(s.columns)))
known_atb = {n for n, _ in atb_rules}
for fn in all_files:
    if fn in known_atb: continue
    if re.fullmatch(r"MessageText\d+\.atb", fn): atb_rules.append((fn, ["Message"]))
    elif re.fullmatch(r"QuestNameText\d+\.atb", fn): atb_rules.append((fn, ["Message"]))
    elif re.fullmatch(r"RewardText\d+\.atb", fn): atb_rules.append((fn, ["Text"]))

aar_rules = []
known_aar = set()
for a in catalog.ALAR_ARCHIVES:
    aar_rules.append((a.name, a.mode, a.target_entry, list(a.columns)))
    known_aar.add(a.name)
for fn in all_files:
    if fn not in known_aar and re.fullmatch(r"BattleTalkEvent\d+\.aar", fn):
        aar_rules.append((fn, "direct_atb", "BattleTalkEvent.atb", ["Message", "Name"]))

# Compare against device_data (current live files) AND clean_orig!
# If a table was partially patched in FULL_DUMP/device_data and we have clean_orig, clean_orig has the true JP.
# If FULL_DUMP was already patched (for EventArc etc), device_data still has the patched text; any dirty/untranslated in device_data should also be collected!
todo_strings = set(retrans_needed)
zh_vals = set(clean_glossary.values())

# Helper to inspect an ALTB
def scan_tbl(fn, tbl, cols):
    if not (tbl.form & 0x04): return
    fields = {f.name_en for f in tbl.string_fields()}
    use = [c for c in cols if c in fields]
    for r in range(tbl.count):
        rs = tbl.get_row_strings(r)
        for c in use:
            v = rs.get(c) or ""
            if not v or not JP_OR_CJK.search(v):
                continue
            if v in clean_glossary:
                continue
            if v in zh_vals:
                # Already a clean translation! Wait: check if clean translation has kana
                if REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", v)):
                    todo_strings.add(v)
                continue
            # Not in clean_glossary and not in zh_vals!
            # Check if pure ASCII/symbol+kanji or kana
            # Skip short CJK strings that are identical in SC/JP only if they contain NO Japanese-only chars and NO kana? No! Better translate any unknown JP string (Hy-MT2 or manual) unless it's purely numbers/ASCII.
            # Wait: check if it's purely identical like "？？？", "Lv1", "HP+10%"
            if not re.search(r"[\u3041-\u3096\u30a1-\u30f6\u4e00-\u9fff]", v):
                continue
            todo_strings.add(v)

# Scan both clean_orig (where available) and device_data (live) so nothing escapes!
checked_dirs = [clean_orig, {fn: os.path.join(DATA_DIR, fn) for fn in os.listdir(DATA_DIR) if os.path.isfile(os.path.join(DATA_DIR, fn))}]

for src_map in checked_dirs:
    for fn, cols in atb_rules:
        p = src_map.get(fn)
        if not p or not os.path.exists(p): continue
        raw = open(p, "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        if dec[:4] == b"ALTB":
            scan_tbl(fn, af.parse_altb(dec), cols)
    for fn, mode, target, cols in aar_rules:
        p = src_map.get(fn)
        if not p or not os.path.exists(p): continue
        raw = open(p, "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        if not af.is_alar_v3(dec): continue
        for e in af.parse_alar_v3(dec):
            if mode == "direct_atb" and e.name == target:
                ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
                if ed[:4] == b"ALTB":
                    scan_tbl(fn, af.parse_altb(ed), cols)
            elif mode == "nested_evtxt" and af.is_alar_v3(e.data):
                for se in af.parse_alar_v3(e.data):
                    if se.name.endswith(target):
                        ed = af.decompress_all4(se.data)[2] if af.is_all4(se.data) else se.data
                        if ed[:4] == b"ALTB":
                            scan_tbl(fn, af.parse_altb(ed), cols)

# Filter out strings that are ALREADY clean Chinese (e.g. from already-patched EventArc where full_dump was patched or slightly edited?)
# Wait: how to tell a string from patched EventArc/paev03 that is clean SC vs untranslated pure-kanji JP?
# Actually if EventArc/paev03 came from a patched full_dump, any translated string IS in `zh_vals` (except maybe if `full_dump` came from an older batch? All batches 01..14 are in `WB_TRANS_DIR`!).
# Let's see how many `todo_strings` don't have kana (kanji-only) vs have kana!
todo_kana = sorted(s for s in todo_strings if REAL_KANA_RE.search(s))
todo_nokana = sorted(s for s in todo_strings if not REAL_KANA_RE.search(s))
print(f"\nCollected todo_strings total={len(todo_strings)}: with_kana={len(todo_kana)}, no_kana={len(todo_nokana)}")
print("Sample no_kana (first 40):")
for s in todo_nokana[:40]:
    print(f"  {s!r}")

# Clean ALOD strings extraction (fixing the leading ?/@/WDxx/SKxx prefix bug properly!)
aod_clean = {}
for fn in sorted(os.listdir(DATA_DIR)):
    if not fn.endswith(".aar"): continue
    raw = open(os.path.join(DATA_DIR, fn), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if not af.is_alar_v3(dec): continue
    for e in af.parse_alar_v3(dec):
        ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
        if ed[:4] not in (b"ALOD", b"AOLD"): continue
        pos = 0
        while pos < len(ed):
            nul = ed.find(b"\x00", pos)
            if nul == -1: break
            seg = ed[pos:nul]
            pos = nul + 1
            if len(seg) < 3: continue
            start_idx = None
            for k in range(len(seg)):
                try:
                    s = seg[k:].decode("utf-8", "strict")
                except UnicodeDecodeError:
                    continue
                if JP_OR_CJK.search(s) and all((0x20 <= ord(c) <= 0x7E) or c in "\n\r\t" or (0x3000 <= ord(c) <= 0x30FF) or (0x4E00 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆●○▲△■□◆◇※→←↑↓〇" for c in s):
                    start_idx = k
                    break
            if start_idx is None: continue
            raw_s = seg[start_idx:]
            s = raw_s.decode("utf-8")
            # Strip leading binary struct byte(s) + optional 4-char widget ID like ?WD01 / ?SK21 / @SP08 / ?TWSP
            # Specifically check if byte before CJK/prefix matches binary tag:
            m_dirty_tag = re.match(r"^[^0-9A-Za-z\u3000-\u9fff\uff00-\uffef\[(/*「『★※・\n]?(?:WD|SP|SK|TX|BT|TW)[A-Z0-9]{2}", s)
            if m_dirty_tag:
                rest = s[m_dirty_tag.end():]
                if rest and JP_OR_CJK.search(rest):
                    s = rest
            # Strip single leading binary symbol (`?` from 0x3f, `@` from 0x40, etc.) before CJK/symbols >= U+2000
            while len(s) >= 2 and s[0] in "@?`~^|\\#$%&*+=<>{}!\"',.;:" and (ord(s[1]) >= 0x2000 or s[1:] in ("ID:[ID]",) or re.match(r"^(ID:|1/|1日|4月|\[REMAINING|★|※|〇)", s[1:])):
                s = s[1:]
            # Also if single ASCII letter right before Japanese CJK (from binary byte like `0x4c` 'L' or `0x64` 'd' before multibyte UTF-8):
            if len(s) >= 2 and s[0].isascii() and s[0].isalpha() and ord(s[1]) >= 0x2000 and not s.startswith(("y", "DMM", "EP", "HP", "EXP")):
                s = s[1:]
            if "あいうえお" in s or "＠＠＠" in s or "最大全角" in s or "最大１１文字" in s or "開発実装用サンプル" in s or s in ("ユニット名", "テキスト", "名前", "本文", "クエストタイトル", "５行まであり得る", "システムテキストによる説明文"):
                continue
            if not JP_OR_CJK.search(s): continue
            # Double check exact raw_s exists in ed with trailing NUL!
            b = s.encode("utf-8")
            if b + b"\x00" not in ed:
                continue
            rec = aod_clean.setdefault(s, {"bytes": len(b), "count": 0, "files": []})
            rec["count"] += 1
            if len(rec["files"]) < 3 and f"{fn}/{e.name}" not in rec["files"]:
                rec["files"].append(f"{fn}/{e.name}")

print(f"\nVerified clean ALOD UI strings (exact bytes + NUL confirmed): {len(aod_clean)}")
for s, r in sorted(aod_clean.items())[:30]:
    print(f"  [{r['bytes']:3d}B x{r['count']:<3d}] {s!r}")

json.dump({
    "clean_glossary": clean_glossary,
    "todo_kana": todo_kana,
    "todo_nokana": todo_nokana,
    "aod_clean": aod_clean,
}, open(os.path.join(WORK_DIR, "step1_payload.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
