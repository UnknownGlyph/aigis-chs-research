import os, sys, re, json
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
MAINFONT_PATH = os.path.join(DATA_DIR, "MainFont.aft")
MAINFONTFIX_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\apk_assets\assets\MainFontFix.aft"
SO_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\apk_assets\lib\arm64-v8a\libAqualeadApp.so"
REPORT_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\diag_report.txt"

KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
CJK_RE = re.compile(r"[\u3000-\u303f\u3040-\u30ff\uff00-\uffef\u4e00-\u9fff]")
SCRIPT_RE = re.compile(r"[()\[\]{}=,;\"'<>|%\\]|^[A-Za-z0-9_.\-/]+$")
ASCII_ONLY_RE = re.compile(r"^[\x20-\x7e]*$")

# Load existing translations from WorkBuddy (including batch_09..14)
TRANS_DIR = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research\translations"
glossary = {}
for fn in sorted(os.listdir(TRANS_DIR)):
    if fn.endswith(".json"):
        try:
            d = json.load(open(os.path.join(TRANS_DIR, fn), encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(k, str) and isinstance(v, str) and v:
                        glossary[k] = v
        except Exception:
            pass

# Fonts
mf = af.parse_alft(open(MAINFONT_PATH, "rb").read())
mff = af.parse_alft(open(MAINFONTFIX_PATH, "rb").read())
mf_cps = set(mf.glyphs.keys())
mff_cps = set(mff.glyphs.keys())

lines_out = []
def log(s=""):
    lines_out.append(s)

log(f"Loaded glossary entries: {len(glossary)}")
log(f"Device MainFont.aft    : {len(mf_cps)} glyphs, file={os.path.getsize(MAINFONT_PATH)} B, gw={mf.gw}, gh={mf.gh}, cols={mf.cols}, img_w={mf.img_w}")
log(f"APK MainFontFix.aft    : {len(mff_cps)} glyphs, file={os.path.getsize(MAINFONTFIX_PATH)} B, gw={mff.gw}, gh={mff.gh}, cols={mff.cols}, img_w={mff.img_w}")
log(f"MainFontFix Chinese test ('的','是','战','军','这','们'): {[chr(c) for c in [ord(x) for x in '的是战军这们'] if c in mff_cps]}")
log(f"MainFont Chinese test    ('的','是','战','军','这','们'): {[chr(c) for c in [ord(x) for x in '的是战军这们'] if c in mf_cps]}")

# Check all files in device_data
# Store per (table_family, col_name): stats and sample values
col_stats = defaultdict(lambda: {"rows": 0, "nonempty": 0, "cjk": 0, "kana": 0, "not_in_gloss": 0, "files": set(), "samples": [], "kana_samples": []})
missing_in_mf = Counter()
missing_examples = defaultdict(list)

# Track files containing non-trivial untranslated JP or missing glyphs
file_missing_glyphs = defaultdict(set)
archive_internal_tables = defaultdict(set)

def scan_altb(file_label: str, inner_label: str, tbl: af.AltbTable):
    if not (tbl.form & 0x04):
        return
    try:
        sfields = [f.name_en for f in tbl.string_fields()]
    except Exception:
        return
    if not sfields:
        return

    fam = re.sub(r"\d+", "<N>", os.path.basename(file_label))
    if inner_label:
        inner_fam = re.sub(r"\d+", "<N>", inner_label)
        key_prefix = f"{fam}::{inner_fam}"
    else:
        key_prefix = fam

    for r in range(tbl.count):
        row_s = tbl.get_row_strings(r)
        for col in sfields:
            val = row_s.get(col) or ""
            st = col_stats[(key_prefix, col)]
            st["rows"] += 1
            st["files"].add(file_label)
            if not val:
                continue
            st["nonempty"] += 1
            if not ASCII_ONLY_RE.match(val):
                st["cjk"] += 1
                has_kana = bool(KANA_RE.search(val))
                if has_kana:
                    st["kana"] += 1
                    if val not in glossary:
                        st["not_in_gloss"] += 1
                    if len(st["kana_samples"]) < 4 and val not in st["kana_samples"]:
                        st["kana_samples"].append(val.replace("\n", "\\n")[:80])
                if len(st["samples"]) < 4 and val not in st["samples"]:
                    st["samples"].append(val.replace("\n", "\\n")[:80])

                # Check every character against MainFont.aft
                # Note: differentiate scripty/keylike vs normal text
                is_key = bool(re.search(r"_|[A-Za-z]{4,}|\(|\)|=", val))
                for ch in val:
                    cp = ord(ch)
                    if cp >= 0x21 and cp not in mf_cps:
                        missing_in_mf[(cp, is_key)] += 1
                        file_missing_glyphs[file_label].add((ch, col, is_key))
                        if len(missing_examples[cp]) < 3:
                            ctx = f"{file_label}/{inner_label}[{col}]: {val.replace(chr(10),' ')[:40]}"
                            missing_examples[cp].append(ctx)

def walk_data(file_label: str, inner_path: str, payload: bytes, depth: int = 0):
    if depth > 5 or len(payload) < 8:
        return
    head = payload[:4]
    if head == b"ALL4":
        try:
            _, _, dec = af.decompress_all4(payload)
            walk_data(file_label, inner_path, dec, depth + 1)
        except Exception as e:
            pass
    elif head == b"ALTB":
        try:
            tbl = af.parse_altb(payload)
            scan_altb(file_label, inner_path, tbl)
            if inner_path:
                archive_internal_tables[re.sub(r"\d+", "<N>", file_label)].add(re.sub(r"\d+", "<N>", inner_path))
        except Exception:
            pass
    elif head == b"ALAR" and af.is_alar_v3(payload):
        try:
            ents = af.parse_alar_v3(payload)
            for e in ents:
                subp = f"{inner_path}/{e.name}" if inner_path else e.name
                walk_data(file_label, subp, e.data, depth + 1)
        except Exception:
            pass

files = sorted(os.listdir(DATA_DIR))
for fn in files:
    p = os.path.join(DATA_DIR, fn)
    if not os.path.isfile(p):
        continue
    if fn.endswith((".atb", ".aar")):
        raw = open(p, "rb").read()
        walk_data(fn, "", raw, 0)

log("\n" + "="*80)
log("1. CHARACTERS MISSING FROM DEVICE MainFont.aft (NON-KEY vs KEYLIKE)")
log("="*80)
non_key_missing = [(cp, cnt) for (cp, is_key), cnt in missing_in_mf.items() if not is_key]
key_missing = [(cp, cnt) for (cp, is_key), cnt in missing_in_mf.items() if is_key]
non_key_missing.sort(key=lambda x: -x[1])
key_missing.sort(key=lambda x: -x[1])

log(f"Missing NON-KEY unique chars: {len(non_key_missing)}")
for cp, cnt in non_key_missing[:120]:
    log(f"  {chr(cp)} (U+{cp:04X}) x{cnt:<4d} | {missing_examples[cp][:2]}")
if len(non_key_missing) > 120:
    log(f"  ... and {len(non_key_missing)-120} more non-key chars: " + "".join(chr(c) for c, _ in non_key_missing[120:]))

log(f"\nMissing KEYLIKE/SCRIPTY unique chars: {len(key_missing)}")
for cp, cnt in key_missing[:30]:
    log(f"  {chr(cp)} (U+{cp:04X}) x{cnt:<4d} | {missing_examples[cp][:1]}")

log("\n" + "="*80)
log("2. TABLES/ARCHIVES WITH REMAINING KANA (POTENTIAL UNTRANSLATED TEXT)")
log("="*80)
kana_cols = [(k, v) for k, v in col_stats.items() if v["kana"] > 0]
kana_cols.sort(key=lambda kv: -kv[1]["kana"])
for (key_prefix, col), v in kana_cols:
    log(f"  {key_prefix:45s} | col={col:22s} | files={len(v['files']):3d} | kana_rows={v['kana']:5d}/{v['nonempty']:5d} (not_in_gloss={v['not_in_gloss']:5d})")
    for s in v["kana_samples"][:2]:
        log(f"      sample: {s}")

log("\n" + "="*80)
log("3. NON-KANA CJK COLUMNS (PURE KANJI JAPANESE TABLES)")
log("="*80)
kanji_only_cols = [(k, v) for k, v in col_stats.items() if v["cjk"] > 0 and v["kana"] == 0]
kanji_only_cols.sort(key=lambda kv: -kv[1]["cjk"])
for (key_prefix, col), v in kanji_only_cols[:50]:
    log(f"  {key_prefix:45s} | col={col:22s} | files={len(v['files']):3d} | cjk_rows={v['cjk']:5d} | samples={v['samples'][:2]}")

log("\n" + "="*80)
log("4. ARCHIVES CONTAINING ALTB TABLES")
log("="*80)
for afam, tbls in sorted(archive_internal_tables.items()):
    log(f"  {afam:36s} -> {sorted(tbls)[:8]} (total {len(tbls)})")

with open(REPORT_PATH, "w", encoding="utf-8") as fp:
    fp.write("\n".join(lines_out))
print(f"Report written to {REPORT_PATH} ({len(lines_out)} lines)")
print("\n".join(lines_out[:45]))
