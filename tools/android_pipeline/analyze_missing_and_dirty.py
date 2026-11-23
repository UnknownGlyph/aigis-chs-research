import os, sys, re, struct, json
from collections import Counter

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"

# 1. Fully parse HarlemEventText1.aar (sequential entry headers)
h1_raw = open(os.path.join(DATA_DIR, "HarlemEventText1.aar"), "rb").read()
h1_dec = af.decompress_all4(h1_raw)[2] if af.is_all4(h1_raw) else h1_raw
cnt1 = struct.unpack_from("<H", h1_dec, 6)[0]
print(f"HarlemEventText1.aar: cnt={cnt1}, dec_len={len(h1_dec)}")

# Inspect first entry offset vs 18 + cnt1*2
# Earlier: 18 + 3377*2 = 0x1a74. And entry 0 name was at 0x1a86! Wait 0x1a86 - 18 = 0x1a74!
# Wait: look back at 0x1a68..0x1a90:
# 0x1a68: 4b 8a 55 8a 5f 8a 69 8a 73 8a 7d 8a [10 10 73 00]
# Oh!! 0x1a74 IS 18 + 3377*2 = 0x1a74!!
# So 0x1a74 starts with `10 10 73 00 1c 2a 02 00 8b 04 00 00 01 00 00 80 0f d3` (18 bytes) followed by `EventText_0016_1.txt\x00`!!
# Let's parse sequentially from pos = 18 + cnt1*2!
pos = 18 + cnt1 * 2
h1_entries = []
for i in range(cnt1):
    # Wait: are there padding bytes before each entry header? Let's check 4-byte alignment
    idx, u2, foff, fsz, fflags = struct.unpack_from("<HHIII", h1_dec, pos)
    # Name starts at pos + 18? Wait check bytes at pos+16..pos+18
    nend = h1_dec.find(b"\x00", pos + 18)
    fname = h1_dec[pos + 18 : nend].decode("utf-8", errors="replace")
    h1_entries.append((i, idx, foff, fsz, fname))
    # Advance to next entry header: nend + 1, align to 2 or 4?
    # Check entry 0: 0x1a86 + len("EventText_0016_1.txt")=20 -> 0x1a9a, then `\x00\x00`, next starts at 0x1a9c (`20 10 73 00`)!
    # 0x1a9b -> next even / align4? Wait: 0x1a9a is 2 mod 4 -> `\x00\x00` pads to 0x1a9c (0 mod 4)!
    nxt = nend + 1
    while nxt % 4 != 0 and nxt < len(h1_dec) and h1_dec[nxt] == 0:
        nxt += 1
    # Verify align4
    pos = af.align4(nend + 1)

print(f"Parsed {len(h1_entries)} entries in HarlemEventText1.aar! First 3: {h1_entries[:3]}, Last 3: {h1_entries[-3:]}")
bad_h1 = 0
h1_lines = 0
h1_chars = 0
h1_cps = Counter()
for i, idx, foff, fsz, fname in h1_entries:
    if not fname.endswith(".txt") or foff + fsz > len(h1_dec):
        bad_h1 += 1
        continue
    chunk = h1_dec[foff:foff+fsz]
    if af.is_all4(chunk):
        chunk = af.decompress_all4(chunk)[2]
    txt = chunk.decode("utf-8-sig", errors="replace")
    h1_lines += len([ln for ln in txt.splitlines() if ln.strip()])
    h1_chars += len(txt)
    for ch in txt:
        if ord(ch) >= 0x21:
            h1_cps[ord(ch)] += 1
print(f"  bad={bad_h1}, non-empty lines={h1_lines}, total_chars={h1_chars}, unique_cps={len(h1_cps)}")

# Also check HarlemEventText0.aar
h0_raw = open(os.path.join(DATA_DIR, "HarlemEventText0.aar"), "rb").read()
h0_dec = af.decompress_all4(h0_raw)[2] if af.is_all4(h0_raw) else h0_raw
h0_ents = af.parse_alar_v3(h0_dec)
h0_lines = 0
h0_chars = 0
h0_cps = Counter()
for e in h0_ents:
    d = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
    txt = d.decode("utf-8-sig", errors="replace")
    h0_lines += len([ln for ln in txt.splitlines() if ln.strip()])
    h0_chars += len(txt)
    for ch in txt:
        if ord(ch) >= 0x21:
            h0_cps[ord(ch)] += 1
print(f"HarlemEventText0.aar: entries={len(h0_ents)}, lines={h0_lines}, chars={h0_chars}, unique_cps={len(h0_cps)}")

# Print sample full EventText file from Harlem0 and Harlem1
print("\nSample Harlem0 EventText_0007_1.txt:")
print(h0_ents[0].data.decode("utf-8-sig")[:400])

# 2. Extract ALL ALOD unique strings across all 358 .aod files to curate translation list!
JP_OR_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
aod_items = {}  # orig_str -> {"count": n, "files": [...], "orig_bytes": len}
for fn in sorted(os.listdir(DATA_DIR)):
    if not fn.endswith(".aar"): continue
    raw = open(os.path.join(DATA_DIR, fn), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if not af.is_alar_v3(dec): continue
    for e in af.parse_alar_v3(dec):
        ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
        if ed[:4] in (b"ALOD", b"AOLD"):
            # Search null-terminated UTF-8 strings preceded by non-ASCII or clean boundaries
            # Specifically match \x00-terminated UTF-8 strings starting after a control/struct byte (like \x00, \x40, \x01..)
            # Better: split on \x00 and check valid UTF-8 C strings!
            pos_s = 0
            while pos_s < len(ed):
                nul = ed.find(b"\x00", pos_s)
                if nul == -1: break
                seg = ed[pos_s:nul]
                pos_s = nul + 1
                if len(seg) < 2: continue
                # Sometimes struct binary floats precede the string directly without a null byte (e.g. `00 40 e3 83 a9...`, `3d 00 00 80 3f ... 18 00 e7 ac ac...`)
                # So find longest suffix of `seg` that decodes cleanly as UTF-8 displayable text!
                # Find the start of UTF-8 CJK/ASCII string from the tail:
                best = None
                for k in range(len(seg)):
                    sub = seg[k:]
                    try:
                        s = sub.decode("utf-8", "strict")
                    except UnicodeDecodeError:
                        continue
                    if JP_OR_CJK.search(s) and all((0x20 <= ord(c) <= 0x7E) or (0x3000 <= ord(c) <= 0x30FF) or (0x4E00 <= ord(c) <= 0x9FFF) or (0xFF00 <= ord(c) <= 0xFFEF) or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆●○▲△■□◆◇※→←↑↓\n" for c in s):
                        # Avoid accidental 1-byte garbage ASCII prefix before Japanese like '@' (`\x40`) or '\x18' or 'L' (`\x4c`)
                        # Check if first char is odd ASCII symbol/letter right before CJK when pre-byte wasn't null:
                        best = (k, s, sub)
                        break
                if best:
                    k, s, sub = best
                    # Heuristic: if first char is single ASCII punctuation/letter followed immediately by CJK and preceded by binary struct bytes (k > 0), strip leading artifact char unless it's legitimate like `[Y]` or `1位:` or `★4` or `/600体`
                    if k > 0 and len(s) >= 2 and ord(s[0]) < 0x80 and s[0] not in "[0123456789★・※/(" and ord(s[1]) >= 0x3000:
                        s = s[1:]
                        sub = s.encode("utf-8")
                    elif k > 0 and len(s) >= 2 and s[0] in ("@", "d", "a", "x", "L", "R", "P", "T") and ord(s[1]) >= 0x3000:
                        s = s[1:]
                        sub = s.encode("utf-8")
                    if len(sub) >= 3 and JP_OR_CJK.search(s):
                        rec = aod_items.setdefault(s, {"count": 0, "files": [], "bytes": len(sub)})
                        rec["count"] += 1
                        if len(rec["files"]) < 3 and f"{fn}/{e.name}" not in rec["files"]:
                            rec["files"].append(f"{fn}/{e.name}")

print(f"\nExtracted {len(aod_items)} unique ALOD strings:")
out_aod = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\aod_strings.json"
json.dump(aod_items, open(out_aod, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for s, rec in sorted(aod_items.items(), key=lambda kv: -kv[1]["count"])[:60]:
    print(f"  x{rec['count']:<3d} ({rec['bytes']:2d}B) {s!r:30s} {rec['files'][0]}")
