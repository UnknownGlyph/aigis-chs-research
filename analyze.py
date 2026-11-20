import os
import re
import hashlib
import struct
import lz4.frame

ROOT = r"d:\game\DMM\aigis_exe"
CACHE = os.path.join(ROOT, ".cache")
EXE_PATH = os.path.join(ROOT, "Aigis.exe")

def main():
    exe = open(EXE_PATH, "rb").read()
    rdata = exe[0x8ed800 : 0x8ed800 + 0x239000]

    cands = set()
    for m in re.finditer(rb"[A-Za-z0-9_/\-\.]+\.(?:atb|aar|aft|atx|ard|aod|amt|ogg|mp4|xml|txt|bin|dat)", rdata):
        cands.add(m.group(0).decode("ascii"))
    for m in re.finditer(rb"[A-Za-z0-9_\-]{3,40}\.(?:atb|aar|aft|atx|ard)", rdata):
        cands.add(m.group(0).decode("ascii"))
    for m in re.finditer(rb"[A-Za-z0-9_/\-\.%]+%0?\d*[dx][A-Za-z0-9_/\-\.]*\.(?:atb|aar|aft|atx)", rdata):
        pat = m.group(0).decode("ascii")
        if pat.count("%") == 1:
            for i in range(0, 500):
                try:
                    cands.add(pat % i)
                except Exception:
                    break
    # Also scan known Aigis asset names and substrings
    for extra in [
        "MainFont.aft", "MainFontFix.aft", "LoadIcon.aar", "LoadIconBack.aar",
        "SystemText.atb", "NameText.atb", "StatusText.atb", "SkillText.atb",
        "SkillList.atb", "AbilityText.atb", "AbilityList.atb", "ClassData.atb",
        "CardData.atb", "MessageText.atb", "QuestNameText.atb", "QuestEventText.atb",
        "EventText.atb", "UIText.atb", "HelpText.atb", "LoginAll.aar", "LoginR18.aar",
        "TitleBack.atx", "Title.aar", "Common.aar", "Boot.aar", "Startup.aar",
        "PlayerTitle.atb", "TitleText.atb", "ShopText.atb", "ItemText.atb",
    ]:
        cands.add(extra)

    sha_to_name = {}
    for c in cands:
        sha_to_name[hashlib.sha256(c.encode()).hexdigest()] = c
        bn = os.path.basename(c)
        sha_to_name[hashlib.sha256(bn.encode()).hexdigest()] = bn

    print("=== ROOT FILES MAPPED ===")
    for fn in sorted(os.listdir(ROOT)):
        if len(fn) == 64:
            print(f"  {fn[:16]} -> {sha_to_name.get(fn, '(unknown)')}")

    cache_files = [f for f in sorted(os.listdir(CACHE)) if not f.endswith(".md5")]
    matched = {fn: sha_to_name[fn] for fn in cache_files if fn in sha_to_name}
    print(f"\n=== .cache MAPPED: {len(matched)} / {len(cache_files)} ===")

    # Check ALL Japanese ALTB & ALAR files and print their mapped names!
    jp_re = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

    def align4(x):
        return (x + 3) & ~3

    def parse_alrd(b, off):
        ver, count, rec_size = struct.unpack_from("<HHH", b, off + 4)
        pos = off + 10
        fields = []
        for _ in range(count):
            foff = struct.unpack_from("<H", b, pos)[0]
            ftype = b[pos + 2]
            fempty = b[pos + 3]
            len_en = b[pos + 4]
            len_jp = b[pos + 5]
            pos += 6
            name_en = b[pos : pos + len_en].decode("utf-8", errors="replace")
            pos += len_en + 1
            name_jp = b[pos : pos + len_jp].decode("utf-8", errors="replace")
            pos += len_jp + 1
            pos = align4(pos)
            pos += align4(fempty)
            fields.append((foff, ftype, name_en, name_jp))
        return fields, pos

    rows = []
    for fn in cache_files:
        p = os.path.join(CACHE, fn)
        raw = open(p, "rb").read()
        kind = raw[:4].decode("ascii", errors="replace")
        b = raw
        if raw[:4] == b"ALL4":
            b = lz4.frame.decompress(raw[raw.find(b"\x04\x22\x4d\x18") :])
            kind = "ALL4+" + b[:4].decode("ascii", errors="replace")
        if b[:4] == b"ALTB":
            ver, form, count, alrd_off, entry_off, entry_sz = struct.unpack_from("<BBHHHI", b, 4)
            if not (form & 0x04):
                continue
            str_sz, str_off = struct.unpack_from("<II", b, 16)
            label = b[alrd_off - 4 : alrd_off].decode("ascii", errors="replace") if (form & 0x10) else ""
            fields, _ = parse_alrd(b, alrd_off)
            pool = b[str_off : str_off + str_sz]
            strs = [s.decode("utf-8", errors="replace") for s in pool.split(b"\x00") if s]
            jp_strs = [s for s in strs if jp_re.search(s)]
            if jp_strs:
                str_cols = [en for _, ft, en, _ in fields if ft == 0x20]
                rows.append((sum(len(s) for s in jp_strs), len(jp_strs), fn, matched.get(fn, "?"), kind, label, form, len(raw), len(b), str_cols))

    print("\n=== ALL 55 JAPANESE ALTB TABLES (WITH MAPPED FILENAMES) ===")
    for nchr, nstr, fn, name, kind, label, form, rsz, usz, cols in sorted(rows, key=lambda x: -x[0]):
        print(f"  {fn[:12]} {name:34s} {kind:9s} lbl={label:4s} f=0x{form:02x} sz={rsz:7d} strs={nstr:5d} ch={nchr:6d} cols={cols[:3]}")

    # Also check the 8 ALAR files with ALTB + JP
    print("\n=== ALAR FILES WITH ALTB + JP (MAPPED) ===")
    for pref in ["8d6e4b480d77", "44f75f2f9e7f", "aaa6f2770689", "92ca35763512", "099e7679950b", "cd6846b812db", "634a6fe94804", "37d341e20e86"]:
        fn = [f for f in cache_files if f.startswith(pref)][0]
        print(f"  {pref} -> {matched.get(fn, '?')} ({os.path.getsize(os.path.join(CACHE, fn))} B)")

    # Check form=0x1e trailing section on both files
    print("\n=== form=0x1e TRAILING SECTION ===")
    for nchr, nstr, fn, name, kind, label, form, rsz, usz, cols in rows:
        if form == 0x1e:
            raw = open(os.path.join(CACHE, fn), "rb").read()
            b = lz4.frame.decompress(raw[raw.find(b"\x04\x22\x4d\x18") :]) if raw[:4] == b"ALL4" else raw
            ver, form, count, alrd_off, entry_off, entry_sz = struct.unpack_from("<BBHHHI", b, 4)
            str_sz, str_off, tail_off = struct.unpack_from("<III", b, 16)
            tail = b[tail_off:]
            print(f"  {fn[:12]} {name}: count={count} str_off=0x{str_off:x} str_sz=0x{str_sz:x} tail_off=0x{tail_off:x} tail_len={len(tail)} tail[:64]={tail[:64].hex()}")

if __name__ == "__main__":
    main()
