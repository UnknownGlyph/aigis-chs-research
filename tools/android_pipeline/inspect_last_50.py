import os, sys, json
from collections import defaultdict, Counter

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import build_android_complete as B

LAST_50 = "酋酝酪酵醛鏖钞钳钵铰锃锏锝锢镌镐镝镳闩阈阑陇陡陲雁霉颚飒飓饺骡髦鬓魈鯐鯱鲷鳕鸥鹃鹉鹡鹦鹬鹮麽黜鼾ＨＰ"
LSET = set(LAST_50)

OUT_DATA = B.OUT_DATA
ctx = defaultdict(list)
cnt = Counter()

def feed_str(src_name, s):
    for ch in s:
        if ch in LSET:
            cnt[ch] += 1
            if len(ctx[ch]) < 2:
                i = s.find(ch)
                snip = s[max(0, i-10):i+12].replace("\n", " ").replace("\r", "")
                ctx[ch].append(f"[{src_name}] {snip!r}")

for fn in sorted(os.listdir(OUT_DATA)):
    raw = open(os.path.join(OUT_DATA, fn), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if dec[:4] == b"ALTB":
        t = af.parse_altb(dec)
        for ch_row in t.get_all_rows_strings():
            for v in ch_row.values():
                if v: feed_str(fn, v)
    elif af.is_alar_v3(dec):
        if fn.startswith("HarlemEventText"):
            c = int.from_bytes(dec[6:8], "little")
            pos = 18 + c * 2
            for _ in range(c):
                foff = int.from_bytes(dec[pos+4:pos+8], "little")
                fsz = int.from_bytes(dec[pos+8:pos+12], "little")
                nend = dec.find(b"\x00", pos+18)
                efn = dec[pos+18:nend].decode("utf-8", "ignore")
                pos = af.align4(nend+1)
                if efn.endswith(".txt"):
                    feed_str(f"{fn}/{efn}", dec[foff:foff+fsz].decode("utf-8-sig", "ignore"))
        else:
            for e in af.parse_alar_v3(dec):
                ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
                if ed[:4] == b"ALTB":
                    t = af.parse_altb(ed)
                    for row in t.get_all_rows_strings():
                        for v in row.values():
                            if v: feed_str(fn, v)

for ch in LAST_50:
    print(f"  {ch} x{cnt[ch]:<3d}: {ctx[ch]}")
