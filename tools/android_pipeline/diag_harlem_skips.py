import os, sys, struct, re, json

sys.path.insert(0, r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n")
sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
import aigis_formats as af
import build_android_complete as B

glossary, alod_dict, harlem_dict = B.load_merged_translations()
orig_map = B.get_clean_orig_map()

for hfn in ("HarlemEventText0.aar", "HarlemEventText1.aar"):
    raw = open(orig_map[hfn], "rb").read()
    dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    cnt = struct.unpack_from("<H", dec, 6)[0]
    pos = 18 + cnt * 2
    skipped_unchanged = []
    skipped_oversize = []
    for _ in range(cnt):
        idx, u2, foff, fsz, fflags = struct.unpack_from("<HHIII", dec, pos)
        nend = dec.find(b"\x00", pos + 18)
        fname = dec[pos + 18 : nend].decode("utf-8", errors="replace")
        pos = af.align4(nend + 1)
        if not fname.endswith(".txt"): continue
        chunk = dec[foff:foff+fsz]
        ia4 = af.is_all4(chunk)
        tb = af.decompress_all4(chunk)[2] if ia4 else chunk
        txt = tb.decode("utf-8-sig", errors="replace")
        has_bom = tb.startswith(b"\xef\xbb\xbf")
        parts = re.split(r"(\r?\n\r?\n+)", txt)
        changed = False
        new_parts = []
        for part in parts:
            if not part or re.fullmatch(r"\r?\n\r?\n+", part):
                new_parts.append(part)
                continue
            blk = part.strip()
            lines = blk.splitlines()
            if lines and lines[0].strip().startswith("＠"):
                sp = lines[0].strip()[1:].strip()
                sp_zh = harlem_dict.get(sp) or glossary.get(sp) or sp
                rest = "\n".join(lines[1:]).strip()
                rest_zh = (harlem_dict.get(rest) or glossary.get(rest) or rest) if rest else ""
                if sp_zh != sp or rest_zh != rest: changed = True
                new_parts.append("＠" + sp_zh + ("\n" + rest_zh if rest else ""))
            else:
                bz = harlem_dict.get(blk) or glossary.get(blk) or blk
                if bz != blk: changed = True
                new_parts.append(bz)
        if not changed:
            skipped_unchanged.append((fname, txt[:60]))
            continue
        new_txt = "".join(new_parts)
        nb = (b"\xef\xbb\xbf" if has_bom else b"") + new_txt.encode("utf-8")
        if not ia4 and len(nb) > fsz:
            shrunk = new_txt.replace("\u3000", "").replace("  ", " ")
            nb2 = (b"\xef\xbb\xbf" if has_bom else b"") + shrunk.encode("utf-8")
            if len(nb2) > fsz:
                skipped_oversize.append((fname, fsz, len(nb2), ia4))
        elif ia4:
            try:
                af.compress_all4(nb, target_size=fsz)
            except Exception:
                skipped_oversize.append((fname, fsz, len(nb), ia4))
    print(f"=== {hfn}: unchanged={len(skipped_unchanged)}, oversize={len(skipped_oversize)} ===")
    for fn, s in skipped_unchanged[:5]:
        print(f"  UNCHANGED: {fn} | {s!r}")
    for fn, fsz, zb, ia4 in skipped_oversize[:10]:
        print(f"  OVERSIZE : {fn} fsz={fsz} vs zh={zb} (diff={zb-fsz}, a4={ia4})")
