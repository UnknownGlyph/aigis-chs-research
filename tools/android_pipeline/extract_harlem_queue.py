import os, sys, re, json, struct

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import patcher as P

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
OUT_QUEUE = os.path.join(WORK_DIR, "harlem_queue.json")

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

# Extract unique speakers and unique paragraphs (for block-level translation, keeping single-line breaks clean)
speakers = set()
blocks = set()
for label, ents in [("h0", h0), ("h1", h1)]:
    for _, _, fn, data in ents:
        d = af.decompress_all4(data)[2] if af.is_all4(data) else data
        txt = d.decode("utf-8-sig", errors="replace")
        for blk in re.split(r"\r?\n\r?\n+", txt):
            blk = blk.strip()
            if not blk:
                continue
            lines = blk.splitlines()
            # Separate speaker line `＠...` from dialogue block
            if lines and lines[0].strip().startswith("＠"):
                sp = lines[0].strip()[1:].strip()
                if sp and sp not in glossary:
                    speakers.add(sp)
                rest = "\n".join(lines[1:]).strip()
                if rest and rest not in glossary:
                    blocks.add(rest)
            else:
                if blk not in glossary:
                    blocks.add(blk)

sp_list = sorted(speakers, key=len)
blk_list = sorted(blocks, key=len)
print(f"Harlem0+1 unique speakers not in glossary: {len(sp_list)}, unique text blocks: {len(blk_list)}, chars: {sum(map(len, blk_list))}")
json.dump({"speakers": sp_list, "blocks": blk_list}, open(OUT_QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
