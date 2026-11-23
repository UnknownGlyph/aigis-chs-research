import os, sys, json, re
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import font_builder as fb
import build_android_complete as B

MISSING_160 = "缅缔缜翳耷肛胶腆腋腌腼臀臆臟臻舛舟舵舷芮芯芹茬荚荧莨菁菈菪菱萍萧萼葚蒜蒲蓼蔼薯藓蘸虞蚊蚓蚯蛀蛆蛭蛰蛹蛾蜇蜊蜒蜗蜱蜿衒袤裡褴襟見規觐詹誅誊謹譲讥讧讪诏诙诵诿谏谚谩谪貓貪赊跻踊踝踱踵轩辄辐辗辻迂迩迸逍逾遏遐遨邓酋酝酪酵醛鏑鏖钞钳钵铰锃锏锝锢镌镐镳闩阈阑陇陡陣陲險雁雑霉颚風飒飓飛餅饺駒骡髦鬓魈鯐鯱鲷鳕鳥鷲鸥鹃鹉鹡鹦鹬鹮麽黜鼾"
MSET = set(MISSING_160)

glossary, alod_dict, harlem_dict = B.load_merged_translations()
# Check how many slots compact _BASE_ALWAYS saves!
compact_base = fb._assigned(
    set(range(0x21, 0x7F))
    | set(range(0x3000, 0x30FD))
    | set(ord(c) for c in "！？（）＋－：；＝％＆／～・ー「」『』【】、。　")
)
print(f"Original _BASE_ALWAYS={len(fb._BASE_ALWAYS)}, compact_base={len(compact_base)}, saved={len(fb._BASE_ALWAYS)-len(compact_base)} slots!")

# Check occurrences in OUT_DATA (already built files!)
OUT_DATA = B.OUT_DATA
char_srcs = defaultdict(list)
char_cnt = Counter()

for fn in sorted(os.listdir(OUT_DATA)):
    raw = open(os.path.join(OUT_DATA, fn), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if dec[:4] == b"ALTB":
        t = af.parse_altb(dec)
        for ch in t.string_pool.decode("utf-8", "ignore"):
            if ch in MSET:
                char_cnt[ch] += 1
                if len(char_srcs[ch]) < 2 and fn not in char_srcs[ch]:
                    char_srcs[ch].append(fn)
    elif af.is_alar_v3(dec):
        if fn.startswith("HarlemEventText"):
            # check text files inside harlem
            cnt = int.from_bytes(dec[6:8], "little")
            pos = 18 + cnt * 2
            for _ in range(cnt):
                foff = int.from_bytes(dec[pos+4:pos+8], "little")
                fsz = int.from_bytes(dec[pos+8:pos+12], "little")
                nend = dec.find(b"\x00", pos+18)
                efn = dec[pos+18:nend].decode("utf-8", "ignore")
                pos = af.align4(nend+1)
                if not efn.endswith(".txt"): continue
                txt = dec[foff:foff+fsz].decode("utf-8-sig", "ignore")
                for ch in txt:
                    if ch in MSET:
                        char_cnt[ch] += 1
                        if len(char_srcs[ch]) < 2 and f"{fn}/{efn}" not in char_srcs[ch]:
                            char_srcs[ch].append(f"{fn}/{efn}")
        else:
            for e in af.parse_alar_v3(dec):
                ed = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
                if ed[:4] == b"ALTB":
                    t = af.parse_altb(ed)
                    for ch in t.string_pool.decode("utf-8", "ignore"):
                        if ch in MSET:
                            char_cnt[ch] += 1
                            if len(char_srcs[ch]) < 2 and fn not in char_srcs[ch]:
                                char_srcs[ch].append(fn)

print(f"\nExact occurrence breakdown of the 160 chars:")
for ch in sorted(MSET, key=lambda c: (-char_cnt[c], c)):
    print(f"  {ch} (U+{ord(ch):04X}) x{char_cnt[ch]:<4d} in {char_srcs[ch]}")
