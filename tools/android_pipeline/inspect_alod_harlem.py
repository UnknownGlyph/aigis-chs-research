import os, sys, re, struct, json

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
import aigis_formats as af

DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"

# 1. Decode HarlemEventText1.aar structure
raw1 = open(os.path.join(DATA_DIR, "HarlemEventText1.aar"), "rb").read()
dec1 = af.decompress_all4(raw1)[2] if af.is_all4(raw1) else raw1
print("=== HarlemEventText1.aar ===")
print("0x000..0x040:", dec1[:0x40].hex(" "))
print("0x680..0x700:", dec1[0x680:0x700].hex(" "))
print("0x1a60..0x1af0:", dec1[0x1a60:0x1af0].hex(" "))
print("0x1a60..0x1af0 repr:", repr(dec1[0x1a60:0x1af0]))
# Wait: look at 0x069d vs 0x1a74! Check if 0x10 0x10 0x73 0x00 is the entry marker or 0x1a76!
# What is at 0x0010? 87 8a 9d 06 ... Wait: 0x0010 has 0x8a87?! No, 0x0010..0x0012 = 87 8a, 0x0012..0x0014 = 9d 06!
# Wait: 0x000c = 20 88 7e 00, 0x0010 = 87 8a, 0x0012 = 9d 06 -> if it's 32-bit or delta or TOC at 0x069d?
# Let's print 0x1a76 + 0x100 bytes
# Parse sequential entries starting at 0x1a76? Look at 0x1a76: '10 10 73 00 ...'Wait: is 0x1a76 or 0x1a74 right after hdr_offs?
cnt = struct.unpack_from("<H", dec1, 6)[0]
print("cnt =", cnt, "18 + cnt*2 =", hex(18 + cnt*2))
# Check values of uint16 at offset 18:
u16s = struct.unpack_from("<20H", dec1, 18)
print("first 20 u16 from off 18:", [hex(x) for x in u16s])
# Wait! u16s[0] = 0x069d, u16s[1] = 0x06a7 -> diff = 10 bytes! Wait what is 10 bytes long at 0x069d?!
# Check if at offset 0x069d there are 10-byte records?! No, 0x1a76 is 6774!
# Wait: why is u16s[0] = 0x069d, when 0x1a76 - 0x069d = 0x13d9? No! Check dec1[0x1a74:0x1a90]!
# Wait: earlier Around first entry (0x1a66):
# b'A\x8aK\x8aU\x8a_\x8ai\x8as\x8a}\x8a\x10\x10s\x00\x1c*\x02\x00\x8b\x04\x00\x00\x01\x00\x00\x80\x0f\xd3EventText_0016_1.txt\x00\x00 '
# Look at 0x1a76: '\x10\x10s\x00'!! Before it at 0x1a74 was '}\x8a' which is 0x8a7d! Wait 0x8a41, 0x8a4b, 0x8a55, 0x8a5f, 0x8a69, 0x8a73, 0x8a7d!!
# Diff is ALSO 10 bytes (0x0a)!
# AND WAIT: what is at 0x1a76? Compare to EventText_0016_1.txt entry header:
# Standard ALAR v3 entry header (see parse_alar_v3): idx(2), unk2(2), foff(4), fsz(4), fflags(4), len/unk(2)?, fname!
# Wait: in parse_alar_v3: idx, unk2, foff, fsz, fflags = <HHIII (16 bytes), then 2 bytes, then fname at +18!
# In 0x1a76: `\x10\x10`? Wait no: `10 10 73 00` is 0x00731010? Wait: `0x0f\xd3` is at +16?! 0x0fd3 = 4051?! No: idx=0? Look at 0x1a76 + 0:
# Check the 2nd entry: `\x10s\x00\xa8.\x02\x00X\x04\x00\x00\x01\x00\x00\x80\x10\xd3EventText_00...`
# Notice `\x0f\xd3` -> `\x10\xd3` -> 0xd30f, 0xd310!! Wait: 0x0fd3 vs 0x10d3: 0x0f -> 0x10! That's the index low byte, or <HH = 0x100f? No, 0xd30f = idx, 0xd310 = next!
# Wait: look at `foff` of entry 1: `0x00022a1c`, size `0x048b` = 1163! Add 0x48b to 0x22a1c = 0x22ea7! Align4 -> 0x22ea8! And entry 2 `foff` is `0x00022ea8` (`\xa8.\x02\x00`)!
# So each entry header starts at `EventText_...` minus 18 bytes! Wait: `EventText_0016_1.txt` starts at `0x1a86` -> `0x1a86 - 18 = 0x1a74`? Let's check exact bytes around 0x1a70..0x1ae0!
print("Exact 0x1a68..0x1ae0:")
for off in range(0x1a68, 0x1ae0, 16):
    print(f"  0x{off:04x}: {dec1[off:off+16].hex(' ')}  {dec1[off:off+16]!r}")

# Check what is at 0x00022a1c (first file data!)
print("First file data at 0x22a1c:", repr(dec1[0x22a1c:0x22a1c+120]))

# 2. Check ALL ALOD text entries: are they safe to replace if utf8 len <= orig_len_including_null_pad?
print("\n=== ALOD structure around text slots ===")
# Pick 5 different .aar -> .aod and inspect the bytes before and after EVERY CJK string
for aar_fn, aod_fn in [("Battle.aar", "MainPanel.aod"), ("Battle.aar", "BattleResult.aod"), ("FairyFarmMenu.aar", "BtnBarracks.aod"), ("TempleTopMenu.aar", "TempleTopBanner.aod"), ("TowerPortalMenu.aar", "TowerPortalFooter.aod")]:
    raw = open(os.path.join(DATA_DIR, aar_fn), "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    for e in af.parse_alar_v3(dec):
        if e.name == aod_fn:
            d = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
            ver, form, n_objs = struct.unpack_from("<BBH", d, 4)
            # Check header offsets
            print(f"\nALOD {aar_fn}/{aod_fn}: ver={ver} form={form} count_u16=0x{n_objs:x} raw_head={d[:32].hex(' ')}")
            for m in re.finditer(rb"[\x80-\xff][\x20-\xff]{1,120}\x00", d):
                try:
                    s = m.group()[:-1].decode("utf-8")
                except Exception:
                    continue
                if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", s):
                    # Check bytes before and after
                    b_start = m.start()
                    b_end = m.end()
                    # Check alignment of b_start and b_end
                    pre = d[max(0, b_start-16):b_start]
                    post = d[b_end:min(len(d), b_end+12)]
                    print(f"  off=0x{b_start:04x}(%4={b_start%4}) end=0x{b_end:04x}(%4={b_end%4}) pre={pre[-8:].hex(' ')} s={s!r} post={post[:8].hex(' ')}")
