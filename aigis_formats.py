"""
Aqualead / Millennium War Aigis (aigis_exe) binary format codecs:
  - ALL4: Aqualead LZ4 Frame wrapper
  - ALTB / ALRD: Aqualead structured data table with UTF-8 string pool
  - ALFT / ALIG: Aqualead PAL4 bitmap font atlas
  - ALAR: Aqualead resource archive (read-only inspector)
"""

import os
import struct
import lz4.frame
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def align4(x: int) -> int:
    return (x + 3) & ~3


# ---------------------------------------------------------------------------
# ALL4 (Aqualead LZ4 Frame wrapper)
# ---------------------------------------------------------------------------

def is_all4(data: bytes) -> bool:
    return len(data) >= 16 and data[:4] == b"ALL4"


def decompress_all4(data: bytes) -> Tuple[int, int, bytes]:
    """Returns (version, declared_uncompressed_size, raw_bytes)."""
    if not is_all4(data):
        raise ValueError("Not an ALL4 buffer")
    ver, usize = struct.unpack_from("<II", data, 4)
    if data[12:16] != b"\x04\x22\x4d\x18":
        raise ValueError(f"Unexpected LZ4 frame magic at offset 12: {data[12:16].hex()}")
    # Aigis.exe stops at LZ4 frame EndMark and ignores trailing padding bytes.
    # Strip any trailing bytes safely via lz4.frame.decompress (which handles single frame
    # only if no junk follows; we strip trailing zeros if needed via streaming context).
    dctx = lz4.frame.create_decompression_context()
    out_chunks = []
    pos = 12
    total = len(data)
    while pos < total:
        chunk, bytes_read, eof = lz4.frame.decompress_chunk(dctx, data[pos:])
        if chunk:
            out_chunks.append(chunk)
        pos += bytes_read
        if eof:
            break
        if bytes_read == 0:
            break
    dec = b"".join(out_chunks)
    if len(dec) != usize:
        raise ValueError(f"ALL4 size mismatch: header={usize}, actual={len(dec)}")
    return ver, usize, dec


def compress_all4(
    payload: bytes,
    target_size: Optional[int] = None,
    block_size: int = lz4.frame.BLOCKSIZE_MAX1MB,
    compression_level: int = 0,
) -> bytes:
    """
    Compress payload into Aigis ALL4 format:
      [0..4]  b'ALL4'
      [4..8]  uint32 version = 1
      [8..12] uint32 len(payload)
      [12..]  standard LZ4 frame (block_linked=False, content_checksum=True, store_size=False)
    If target_size is given, pads trailing zeros (ignored by Aigis.exe's LZ4F loop) to hit
    target_size exactly. If initial level is too large, retries up to HC max level 12.
    """
    header = struct.pack("<4sII", b"ALL4", 1, len(payload))
    levels = [compression_level] if target_size is None else [compression_level, 9, 12]
    best = None
    for lvl in levels:
        frame = lz4.frame.compress(
            payload,
            compression_level=lvl,
            block_size=block_size,
            block_linked=False,
            content_checksum=True,
            block_checksum=False,
            store_size=False,
        )
        out = header + frame
        best = out
        if target_size is None or len(out) <= target_size:
            break

    if target_size is not None:
        if len(best) > target_size:
            raise ValueError(
                f"Compressed ALL4 ({len(best)} B) exceeds target_size ({target_size} B) by {len(best) - target_size} B"
            )
        if len(best) < target_size:
            best = best + b"\x00" * (target_size - len(best))
    return best


# ---------------------------------------------------------------------------
# ALTB / ALRD (Aqualead Table)
# ---------------------------------------------------------------------------

@dataclass
class AlrdField:
    offset: int
    ftype: int
    fempty: int
    name_en: str
    name_jp: str
    raw_extra: bytes  # align4(fempty) trailing bytes preserved verbatim


@dataclass
class AltbTable:
    ver: int
    form: int
    count: int
    alrd_off: int
    entry_off: int
    entry_size: int
    label: bytes               # 4 bytes if form & 0x10 else b""
    alrd_raw: bytes            # exact original ALRD chunk bytes
    fields: List[AlrdField]
    records: bytearray         # count * entry_size bytes
    string_pool: bytes         # raw string pool bytes
    tail_data: bytes           # form & 0x08 trailing chunk (e.g. external table refs)
    extra_header_u32s: List[int] = field(default_factory=list)

    def string_fields(self) -> List[AlrdField]:
        return [f for f in self.fields if f.ftype == 0x20]

    def get_string_at(self, soff: int) -> str:
        if not (self.form & 0x04) or soff >= len(self.string_pool):
            return ""
        end = self.string_pool.find(b"\x00", soff)
        raw = self.string_pool[soff : end if end != -1 else len(self.string_pool)]
        return raw.decode("utf-8", errors="replace")

    def get_row_strings(self, row_idx: int) -> Dict[str, str]:
        base = row_idx * self.entry_size
        out = {}
        for f in self.string_fields():
            soff = struct.unpack_from("<I", self.records, base + f.offset)[0]
            out[f.name_en] = self.get_string_at(soff)
        return out

    def get_all_rows_strings(self) -> List[Dict[str, str]]:
        return [self.get_row_strings(i) for i in range(self.count)]

    def rebuild_with_translations(
        self,
        replacements: Dict[Tuple[int, str], str],
        target_size: Optional[int] = None,
    ) -> bytes:
        """
        Rebuild ALTB binary, replacing strings for specified (row_idx, col_name) entries.
        All other columns, row integers, ALRD metadata, and form=0x1e tails are preserved verbatim.
        Deduplicates identical strings in the new string pool to save space.
        If target_size is given, pads the end (after string pool / tail) with zeros to exact size.
        """
        if not (self.form & 0x04):
            raise ValueError("ALTB table has no string pool (form & 0x04 == 0)")

        new_records = bytearray(self.records)
        str_fields = self.string_fields()

        # Build deduplicated string pool starting with b"\x00" (empty string at offset 0)
        pool = bytearray(b"\x00")
        pool_map: Dict[bytes, int] = {b"": 0}

        def intern(s: str) -> int:
            b = s.encode("utf-8")
            off = pool_map.get(b)
            if off is not None:
                return off
            off = len(pool)
            pool_map[b] = off
            pool.extend(b)
            pool.append(0)
            return off

        for r in range(self.count):
            base = r * self.entry_size
            for f in str_fields:
                orig_off = struct.unpack_from("<I", self.records, base + f.offset)[0]
                key = (r, f.name_en)
                if key in replacements:
                    val = replacements[key]
                else:
                    val = self.get_string_at(orig_off)
                new_off = intern(val)
                struct.pack_into("<I", new_records, base + f.offset, new_off)

        # Pad pool to 4-byte boundary for clean alignment before tail_data (if any)
        while len(pool) % 4 != 0:
            pool.append(0)

        # Reconstruct header
        # Base header: 16 bytes
        hdr = bytearray()
        hdr.extend(struct.pack("<4sBBHHHI", b"ALTB", self.ver, self.form, self.count, self.alrd_off, self.entry_off, self.entry_size))

        new_str_off = self.entry_off + len(new_records)
        new_str_sz = len(pool)
        new_tail_off = new_str_off + new_str_sz

        if self.form & 0x04:
            hdr.extend(struct.pack("<II", new_str_sz, new_str_off))
        if self.form & 0x08:
            hdr.extend(struct.pack("<I", new_tail_off))
        if self.form & 0x10:
            hdr.extend(self.label)

        if len(hdr) != self.alrd_off:
            raise ValueError(f"Rebuilt header len {len(hdr)} != alrd_off {self.alrd_off}")

        out = bytearray()
        out.extend(hdr)
        out.extend(self.alrd_raw)
        if len(out) != self.entry_off:
            raise ValueError(f"Offset after ALRD {len(out)} != entry_off {self.entry_off}")
        out.extend(new_records)
        out.extend(pool)
        if self.form & 0x08:
            out.extend(self.tail_data)

        if target_size is not None:
            if len(out) > target_size:
                raise ValueError(
                    f"Rebuilt ALTB ({len(out)} B) exceeds target_size ({target_size} B) by {len(out) - target_size} B"
                )
            if len(out) < target_size:
                out.extend(b"\x00" * (target_size - len(out)))

        return bytes(out)


def parse_altb(data: bytes) -> AltbTable:
    if data[:4] != b"ALTB":
        raise ValueError(f"Not an ALTB buffer: {data[:4]!r}")
    ver, form, count, alrd_off, entry_off, entry_size = struct.unpack_from("<BBHHHI", data, 4)
    pos = 16
    str_sz = str_off = tail_off = 0
    if form & 0x04:
        str_sz, str_off = struct.unpack_from("<II", data, pos)
        pos += 8
    if form & 0x08:
        tail_off = struct.unpack_from("<I", data, pos)[0]
        pos += 4
    label = b""
    if form & 0x10:
        label = data[pos : pos + 4]
        pos += 4
    if pos != alrd_off:
        raise ValueError(f"ALTB header parse ended at {pos}, expected alrd_off={alrd_off} (form=0x{form:02x})")

    alrd_raw = data[alrd_off:entry_off]
    if alrd_raw[:4] != b"ALRD":
        raise ValueError(f"Expected ALRD at 0x{alrd_off:x}")
    _, fcnt, rec_sz = struct.unpack_from("<HHH", alrd_raw, 4)
    fpos = 10
    fields: List[AlrdField] = []
    for _ in range(fcnt):
        foff = struct.unpack_from("<H", alrd_raw, fpos)[0]
        ftype = alrd_raw[fpos + 2]
        fempty = alrd_raw[fpos + 3]
        len_en = alrd_raw[fpos + 4]
        len_jp = alrd_raw[fpos + 5]
        fpos += 6
        name_en = alrd_raw[fpos : fpos + len_en].decode("utf-8", errors="replace")
        fpos += len_en + 1
        name_jp = alrd_raw[fpos : fpos + len_jp].decode("utf-8", errors="replace")
        fpos += len_jp + 1
        fpos = align4(fpos)
        extra_len = align4(fempty)
        raw_extra = alrd_raw[fpos : fpos + extra_len]
        fpos += extra_len
        fields.append(AlrdField(foff, ftype, fempty, name_en, name_jp, raw_extra))

    rec_end = entry_off + count * entry_size
    records = bytearray(data[entry_off:rec_end])
    string_pool = data[str_off : str_off + str_sz] if (form & 0x04) else b""
    tail_data = b""
    if form & 0x08 and tail_off > 0:
        # Read exact tail length (count u32 + count length-prefixed cstrings)
        tpos = tail_off
        tcnt = struct.unpack_from("<I", data, tpos)[0]
        tpos += 4
        for _ in range(tcnt):
            slen = data[tpos]
            tpos += 1 + slen + 1
        tail_data = data[tail_off:tpos]

    return AltbTable(
        ver=ver,
        form=form,
        count=count,
        alrd_off=alrd_off,
        entry_off=entry_off,
        entry_size=entry_size,
        label=label,
        alrd_raw=alrd_raw,
        fields=fields,
        records=records,
        string_pool=string_pool,
        tail_data=tail_data,
    )


# ---------------------------------------------------------------------------
# ALFT / ALIG (Aqualead PAL4 Bitmap Font)
# ---------------------------------------------------------------------------

@dataclass
class AlftFont:
    ver: int
    form: int
    tag: bytes
    gw: int
    gh: int
    cols: int
    img_w: int
    palette: bytes  # 64 bytes (16 RGBA entries)
    alig_meta: Tuple[int, int, int, int, int]  # (alig_ver, alig_form, pal_cnt, u1, u2)
    glyphs: Dict[int, Tuple[int, bytes]]  # codepoint -> (advance_width, 28*28 grayscale 0..15 bytes)

    def get_glyph_grid(self, cp: int) -> Optional[Tuple[int, bytes]]:
        return self.glyphs.get(cp)


def parse_alft(data: bytes) -> AlftFont:
    if data[:4] != b"ALFT":
        raise ValueError("Not an ALFT file")
    ver, form = data[4], data[5]
    tag = data[6:8]
    gw, gh, cols, rcnt = struct.unpack_from("<BBHH", data, 8)
    pos = 14
    ranges = [struct.unpack_from("<HHH", data, pos + i * 6) for i in range(rcnt)]
    pos += rcnt * 6

    wcnt = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    widths = data[pos : pos + wcnt]
    pos += wcnt
    pos = align4(pos)

    if data[pos : pos + 4] != b"ALIG":
        raise ValueError(f"Expected ALIG at 0x{pos:x}, got {data[pos:pos+4]!r}")
    alig_ver, alig_form, pal_cnt = struct.unpack_from("<BBH", data, pos + 4)
    img_fmt = data[pos + 8 : pos + 12]
    pal_fmt = data[pos + 12 : pos + 16]
    if img_fmt != b"PAL4" or pal_fmt != b"RGBA":
        raise ValueError(f"Unsupported ALIG format {img_fmt}/{pal_fmt}")
    img_w, img_h = struct.unpack_from("<II", data, pos + 16)
    u1, u2, pix_off = struct.unpack_from("<HHI", data, pos + 24)
    palette = data[pos + 32 : pos + 32 + pal_cnt * 4]
    pix = data[pos + pix_off : pos + pix_off + (img_w * img_h) // 2]

    # Decode each glyph into gw*gh bytes (values 0..15)
    # High nibble = left pixel (even x), low nibble = right pixel (odd x)!
    glyphs: Dict[int, Tuple[int, bytes]] = {}
    for start_cp, end_cp, base_idx in ranges:
        for cp in range(start_cp, end_cp + 1):
            gidx = base_idx + (cp - start_cp)
            adv = widths[gidx] if gidx < len(widths) else gw
            row = gidx // cols
            col = gidx % cols
            x0 = col * gw
            y0 = row * gh
            buf = bytearray(gw * gh)
            for y in range(gh):
                row_base = (y0 + y) * img_w + x0
                out_base = y * gw
                for x in range(gw):
                    px_i = row_base + x
                    byte = pix[px_i >> 1]
                    buf[out_base + x] = (byte >> 4) if ((px_i & 1) == 0) else (byte & 0x0F)
            glyphs[cp] = (adv, bytes(buf))

    return AlftFont(
        ver=ver,
        form=form,
        tag=tag,
        gw=gw,
        gh=gh,
        cols=cols,
        img_w=img_w,
        palette=palette,
        alig_meta=(alig_ver, alig_form, pal_cnt, u1, u2),
        glyphs=glyphs,
    )


def build_alft(font: AlftFont, target_size: Optional[int] = None) -> bytes:
    """
    Serialize AlftFont back to exact Aigis ALFT + ALIG PAL4 binary format.
    If target_size is given, verifies output <= target_size and pads trailing zeros.
    """
    sorted_cps = sorted(font.glyphs.keys())
    # Coalesce contiguous codepoints into (start, end, base_idx) range entries
    ranges: List[Tuple[int, int, int]] = []
    if sorted_cps:
        r_start = sorted_cps[0]
        r_prev = sorted_cps[0]
        r_base = 0
        for idx, cp in enumerate(sorted_cps[1:], start=1):
            if cp == r_prev + 1:
                r_prev = cp
            else:
                ranges.append((r_start, r_prev, r_base))
                r_start = cp
                r_prev = cp
                r_base = idx
        ranges.append((r_start, r_prev, r_base))

    rcnt = len(ranges)
    gcnt = len(sorted_cps)
    widths = bytes(font.glyphs[cp][0] for cp in sorted_cps)

    # Build ALFT header + range table + width table + 4-byte alignment
    out = bytearray()
    out.extend(struct.pack("<4sBB2sBBHH", b"ALFT", font.ver, font.form, font.tag, font.gw, font.gh, font.cols, rcnt))
    for s, e, bidx in ranges:
        out.extend(struct.pack("<HHH", s, e, bidx))
    out.extend(struct.pack("<H", gcnt))
    out.extend(widths)
    while len(out) % 4 != 0:
        out.append(0)

    # Build ALIG PAL4 image
    rows = (gcnt + font.cols - 1) // font.cols
    img_w = font.img_w
    img_h = rows * font.gh
    pix = bytearray((img_w * img_h) // 2)

    gw, gh, cols = font.gw, font.gh, font.cols
    for gidx, cp in enumerate(sorted_cps):
        _, buf = font.glyphs[cp]
        row = gidx // cols
        col = gidx % cols
        x0 = col * gw
        y0 = row * gh
        for y in range(gh):
            row_base = (y0 + y) * img_w + x0
            in_base = y * gw
            for x in range(0, gw, 2):
                px_i = row_base + x
                hi = buf[in_base + x] & 0x0F
                lo = buf[in_base + x + 1] & 0x0F
                pix[px_i >> 1] = (hi << 4) | lo

    alig_ver, alig_form, pal_cnt, u1, u2 = font.alig_meta
    pix_off = 32 + len(font.palette)
    out.extend(struct.pack("<4sBBH4s4sIIHHI", b"ALIG", alig_ver, alig_form, pal_cnt, b"PAL4", b"RGBA", img_w, img_h, u1, u2, pix_off))
    out.extend(font.palette)
    out.extend(pix)

    if target_size is not None:
        if len(out) > target_size:
            raise ValueError(
                f"Rebuilt ALFT ({len(out)} B, glyphs={gcnt}, ranges={rcnt}, rows={rows}) exceeds target_size ({target_size} B) by {len(out) - target_size} B"
            )
        if len(out) < target_size:
            out.extend(b"\x00" * (target_size - len(out)))

    return bytes(out)


# ---------------------------------------------------------------------------
# ALAR v3 (Aqualead Resource Archive — in-place exact-size patcher)
# ---------------------------------------------------------------------------

@dataclass
class AlarEntry:
    idx: int
    offset: int
    size: int
    flags: int
    name: str
    data: bytes


def is_alar_v3(data: bytes) -> bool:
    return len(data) >= 20 and data[:4] == b"ALAR" and data[4] == 3


def parse_alar_v3(data: bytes) -> List[AlarEntry]:
    if not is_alar_v3(data):
        raise ValueError(f"Not an ALAR v3 buffer: {data[:6]!r}")
    cnt = struct.unpack_from("<H", data, 6)[0]
    hdr_offs = struct.unpack_from(f"<{cnt}H", data, 18)
    entries: List[AlarEntry] = []
    for eh in hdr_offs:
        idx, _unk2, foff, fsz, fflags = struct.unpack_from("<HHIII", data, eh)
        nend = data.find(b"\x00", eh + 18)
        fname = data[eh + 18 : nend].decode("utf-8", errors="replace")
        entries.append(AlarEntry(idx=idx, offset=foff, size=fsz, flags=fflags, name=fname, data=data[foff : foff + fsz]))
    return entries


def patch_alar_v3_inplace(data: bytes, replacements: Dict[str, bytes]) -> bytes:
    """
    Patch selected entries inside an ALAR v3 archive in-place without shifting offsets.
    Each replacement buffer must have exact length == original entry size (or shorter,
    in which case trailing zeros are padded). Preserves exact original archive size.
    """
    entries = parse_alar_v3(data)
    out = bytearray(data)
    for e in entries:
        if e.name in replacements:
            rep = replacements[e.name]
            if len(rep) > e.size:
                raise ValueError(f"ALAR entry {e.name!r} replacement ({len(rep)} B) > original ({e.size} B)")
            if len(rep) < e.size:
                rep = rep + b"\x00" * (e.size - len(rep))
            out[e.offset : e.offset + e.size] = rep
    return bytes(out)

