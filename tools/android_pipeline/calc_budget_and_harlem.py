import os, sys, re, struct, json
from collections import Counter

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import patcher as P

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
AUDIT_JSON = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\audit_plan.json"
AOD_JSON = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\aod_strings.json"

glossary = P.ensure_glossary()

def parse_harlem_aar(path):
    raw = open(path, "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    cnt = struct.unpack_from("<H", dec, 6)[0]
    pos = 18 + cnt * 2
    entries = []
    for i in range(cnt):
        idx, u2, foff, fsz, fflags = struct.unpack_from("<HHIII", dec, pos)
        nend = dec.find(b"\x00", pos + 18)
        fname = dec[pos + 18 : nend].decode("utf-8", errors="replace")
        entries.append((foff, fsz, fname, dec[foff:foff+fsz]))
        pos = af.align4(nend + 1)
    return entries

h0 = parse_harlem_aar(os.path.join(DATA_DIR, "HarlemEventText0.aar"))
h1 = parse_harlem_aar(os.path.join(DATA_DIR, "HarlemEventText1.aar"))

# Count unique lines & paragraphs in Harlem0/1
uniq_lines = set()
uniq_blocks = set()
speaker_lines = 0
for _, _, fn, data in h0 + h1:
    d = af.decompress_all4(data)[2] if af.is_all4(data) else data
    txt = d.decode("utf-8-sig", errors="replace")
    # Split paragraphs by empty line
    for blk in re.split(r"\r?\n\r?\n+", txt):
        blk = blk.strip()
        if blk:
            uniq_blocks.add(blk)
    for ln in txt.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("＠"):
            speaker_lines += 1
        elif s not in glossary:
            uniq_lines.add(s)

print(f"Harlem0+1 files: {len(h0)+len(h1)}")
print(f"  Unique paragraphs (blocks): {len(uniq_blocks)}")
print(f"  Unique non-speaker lines not in glossary: {len(uniq_lines)}, chars={sum(map(len, uniq_lines))}")

# Collect codepoint budgets
mf = af.parse_alft(open(os.path.join(DATA_DIR, "MainFont.aft"), "rb").read())
mf_cps = set(mf.glyphs.keys())
h_cps = set()
for _, _, _, data in h0 + h1:
    d = af.decompress_all4(data)[2] if af.is_all4(data) else data
    for ch in d.decode("utf-8-sig", errors="replace"):
        if ord(ch) >= 0x21:
            h_cps.add(ord(ch))

h_missing_in_mf = sorted(c for c in h_cps if c not in mf_cps)
print(f"Harlem0+1 unique codepoints: {len(h_cps)}, MISSING in MainFont.aft: {len(h_missing_in_mf)}")
print("  Sample missing:", "".join(chr(c) for c in h_missing_in_mf[:100]))

# Print all ALOD strings categorized
aod = json.load(open(AOD_JSON, encoding="utf-8"))
print(f"\nALOD unique strings ({len(aod)}):")
# Filter out obvious placeholders like あいうえお...
clean_aod = []
for s, rec in sorted(aod.items()):
    if "あいうえお" in s or "＠＠＠" in s or "最大全角" in s or "最大１１文字" in s or "ユニット名" == s or "テキスト" == s:
        continue
    clean_aod.append((s, rec["bytes"], rec["count"], rec["files"][0]))
print(f"Non-placeholder ALOD strings: {len(clean_aod)}")
for s, b, c, f in clean_aod[:120]:
    print(f"  [{b:3d}B x{c:<3d}] {s!r:42s} ({f})")
if len(clean_aod) > 120:
    print(f"  ... ({len(clean_aod)-120} more)")
