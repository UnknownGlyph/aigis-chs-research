import os, sys, re, json

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import font_builder as fb

WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
STEP1_PATH = os.path.join(WORK_DIR, "step1_payload.json")
FIX_PATH = os.path.join(WORK_DIR, "batch_15_fix_tables.json")
ALOD_PATH = os.path.join(WORK_DIR, "batch_16_alod_ui.json")

s1 = json.load(open(STEP1_PATH, encoding="utf-8"))
fix_d = json.load(open(FIX_PATH, encoding="utf-8"))
alod_d = json.load(open(ALOD_PATH, encoding="utf-8"))

# 1. Check placeholders [xxx] in ALOD translations!
PH_RE = re.compile(r"\[[A-Za-z0-9_]+\]")
bad_alod_ph = []
for k, v in alod_d.items():
    if sorted(PH_RE.findall(k)) != sorted(PH_RE.findall(v)):
        bad_alod_ph.append((k, v))
print(f"ALOD placeholder mismatches: {len(bad_alod_ph)}")
for k, v in bad_alod_ph:
    print(f"  {k!r} -> {v!r}")

# 2. Check all 87 still_kana entries in batch_15_fix_tables
REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
PUZZLE_KANA_RE = re.compile(r"「[ァ-ヶ,、]+」")
still_kana = [(k, v) for k, v in fix_d.items() if REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", v))]
print(f"\nbatch_15 still_kana ({len(still_kana)}):")
for k, v in still_kana:
    print(f"  {k!r:42s} -> {v!r}")

# 3. Check codepoint budget WITHOUT Harlem0/1 (merged clean_glossary + batch_15 + batch_16 + so_ui + Base_Always + MUST_KEEP)
merged = dict(s1["clean_glossary"])
merged.update(fix_d)
merged.update(alod_d)

zh_cps = set()
for v in merged.values():
    for ch in v:
        if 0x21 <= ord(ch) <= 0xFFFF:
            zh_cps.add(ord(ch))

base = set(range(0x21, 0x7F)) | set(range(0x3000, 0x30FF)) | set(range(0xFF01, 0xFF60)) | set(range(0xFFE0, 0xFFE6))
must = {ord(c) for c in fb.MUST_KEEP_UI_CHARS}
# Clean SO literals:
so_bytes = open(r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\apk_assets\lib\arm64-v8a\libAqualeadApp.so", "rb").read()
so_cps = set()
for ck in re.findall(rb"[\x20-\x7e\x80-\xff]{4,300}\x00", so_bytes):
    try:
        s = ck[:-1].decode("utf-8", "strict")
    except Exception:
        continue
    if bool(re.search(r"[\u3041-\u3096\u30a1-\u30fa]", s)) or len([c for c in s if 0x4E00 <= ord(c) <= 0x9FFF]) >= 2:
        if all((0x20 <= ord(c) <= 0x7E) or fb._is_displayable_jp(ord(c)) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆\n\r\t" for c in s):
            so_cps.update(ord(c) for c in s if ord(c) >= 0x21)

# Plus kept base JP chars in original MainFont? Wait: if we ONLY keep zh_cps + base + must + so_cps + any remaining unpatched table display chars:
# Let's see size of (zh_cps | base | must | so_cps)!
union_no_harlem = fb._assigned(zh_cps | base | must | so_cps)
# Filter out kana-free rare artifacts if any: count total!
print(f"\n=== FONT CODEPOINT BUDGET (zh_dict + base_kana_punct + must + clean_SO) ===")
print(f"  zh_cps={len(zh_cps)}, base={len(base)}, so_cps={len(so_cps)} -> TOTAL UNION = {len(union_no_harlem)}")
print(f"  MainFont.aft capacity = 4284  (headroom: {4284 - len(union_no_harlem)})")
print(f"  MainFontFix.aft capacity = 4071 (headroom: {4071 - len(union_no_harlem)})")
