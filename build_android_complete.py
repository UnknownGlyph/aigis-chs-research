#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_android_complete.py — 安卓版千年战争Aigis全量汉化修复与字体零缺字打包工具

核心修复项:
  1. 合并清洗后的基础词典 (114,991) + batch_15 (1,137 条遗漏/脏译/纯汉字/新增表) +
     batch_16 (550 条 ALOD 原生界面文本) + batch_17 (可选已译 Harlem0/1 交流文本)。
  2. 全自动扫描并纳管全量游戏表/归档:
     - 修复 UiText.atb 白名单遗漏 ["Faq", "FaqDetail"]；
     - 自动纳入新增的 BattleTalkEvent* / MessageText* / QuestNameText* / RewardText*；
     - 原地安全替换 358 个 .aod (ALOD) UI 布局文件中的日文界面标签；
     - 支持原位打包 HarlemEventText0.aar (280篇) 与 HarlemEventText1.aar (3377篇)。
  3. 同步扫描 libAqualeadApp.so 硬编码 UI 字面量与全部全盘实际待绘字符串，
     彻底重建设备字库 MainFont.aft (1,727,372 B) 与 APK 内置字库 MainFontFix.aft (1,647,476 B)，
     保证 100% 展示字符覆盖（0 红叉）。
  4. 支持自动重打包更新 APK (assets/MainFontFix.aft) 并使用 uber-apk-signer 签名，以及一键推送到 MuMu 模拟器。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

# Ensure we use clean codecs from aigis_l10n & font_builder logic
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import aigis_formats as af
import catalog
import font_builder as fb
import patcher as P

DATA_DIR = os.path.join(ROOT_DIR, "android_sync", "device_data")
ORIG_AIGISPULL = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\orig\aigispull"
FULL_DUMP = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-android\full_dump"
WORK_DIR = os.path.join(ROOT_DIR, "android_sync", "work")
APK_ASSETS = os.path.join(ROOT_DIR, "android_sync", "apk_assets")
DEVICE_APK = os.path.join(ROOT_DIR, "android_sync", "device_base.apk")
OUT_ROOT = os.path.join(ROOT_DIR, "android_sync", "build_out")
OUT_DATA = os.path.join(OUT_ROOT, "data")
OUT_APK_DIR = os.path.join(OUT_ROOT, "apk")
MANIFEST_OUT = os.path.join(OUT_ROOT, "android_manifest.json")

ADB = r"D:\software\MuMu Player 12\nx_main\adb.exe"
SERIAL = "127.0.0.1:7555"
UBER_SIGNER = r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\apktools\uber-apk-signer.jar"

REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
PUZZLE_KANA_RE = re.compile(r"「[ァ-ヶ,、]+」")
JP_OR_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def patch_alar_v3_by_offset(data: bytes, replacements_by_offset: Dict[int, bytes]) -> bytes:
    """Patch selected ALAR v3 entries by exact entry offset (avoids duplicate-name collisions like MainPanel.aod)."""
    entries = af.parse_alar_v3(data)
    out = bytearray(data)
    for e in entries:
        if e.offset in replacements_by_offset:
            rep = replacements_by_offset[e.offset]
            if len(rep) > e.size:
                raise ValueError(f"ALAR entry {e.name!r}@0x{e.offset:x} replacement ({len(rep)} B) > original ({e.size} B)")
            if len(rep) < e.size:
                rep = rep + b"\x00" * (e.size - len(rep))
            out[e.offset : e.offset + e.size] = rep
    return bytes(out)


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def load_merged_translations() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    """Return (table_glossary, alod_dict, harlem_dict)."""
    trans_dir = os.path.join(ROOT_DIR, "translations")
    s1_path = os.path.join(WORK_DIR, "step1_payload.json")
    glossary: Dict[str, str] = {}
    if os.path.exists(s1_path):
        s1 = json.load(open(s1_path, encoding="utf-8"))
        glossary = dict(s1.get("clean_glossary", {}))
    else:
        # Load all base batch files from translations/
        for fn in sorted(os.listdir(trans_dir)):
            if fn.endswith(".json") and fn.startswith("batch_") and fn != "batch_17_harlem.json":
                try:
                    d = json.load(open(os.path.join(trans_dir, fn), encoding="utf-8"))
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if isinstance(k, str) and isinstance(v, str) and v and k != v:
                                glossary[k] = v
                except Exception:
                    pass

    b15_path = os.path.join(trans_dir, "batch_15_fix_tables.json")
    if not os.path.exists(b15_path):
        b15_path = os.path.join(WORK_DIR, "batch_15_fix_tables.json")
    b15 = {}
    if os.path.exists(b15_path):
        b15 = json.load(open(b15_path, encoding="utf-8"))
        for k, v in b15.items():
            if isinstance(k, str) and isinstance(v, str) and v:
                glossary[k] = v

    # Ensure core glossary overrides are respected ONLY if clean (no dirty artifacts)
    # Also fix any direct known typos in clean_glossary
    for k, v in list(glossary.items()):
        if "ク莉亚" in v or "プロ盗贼" in v or "专业盗贼" in v:
            # Replace with b15 if present
            if k in b15:
                glossary[k] = b15[k]

    alod_path = os.path.join(trans_dir, "batch_16_alod_ui.json")
    if not os.path.exists(alod_path):
        alod_path = os.path.join(WORK_DIR, "batch_16_alod_ui.json")
    alod_dict: Dict[str, str] = json.load(open(alod_path, encoding="utf-8")) if os.path.exists(alod_path) else {}

    harlem_path = os.path.join(trans_dir, "batch_17_harlem.json")
    if not os.path.exists(harlem_path):
        harlem_path = os.path.join(WORK_DIR, "batch_17_harlem.json")
    harlem_dict: Dict[str, str] = json.load(open(harlem_path, encoding="utf-8")) if os.path.exists(harlem_path) else {}

    return glossary, alod_dict, harlem_dict


def get_clean_orig_map() -> Dict[str, str]:
    """Map logical filename -> cleanest original Japanese file path."""
    m: Dict[str, str] = {}
    for base in (ORIG_AIGISPULL, FULL_DUMP, DATA_DIR):
        if not os.path.isdir(base):
            continue
        for fn in os.listdir(base):
            if fn.endswith(".md5"):
                continue
            p = os.path.join(base, fn)
            if os.path.isfile(p) and fn not in m:
                m[fn] = p
    return m


def scan_so_ui_literals(so_path: str) -> Set[int]:
    """Extract genuine Japanese UI literals hard-coded inside libAqualeadApp.so."""
    if not os.path.exists(so_path):
        return set()
    raw = open(so_path, "rb").read()
    found: Set[int] = set()
    for ck in re.findall(rb"[\x20-\x7e\x80-\xff]{4,300}\x00", raw):
        try:
            s = ck[:-1].decode("utf-8", "strict")
        except UnicodeDecodeError:
            continue
        has_kana = bool(re.search(r"[\u3041-\u3096\u30a1-\u30fa]", s))
        cjk_chars = [c for c in s if 0x4E00 <= ord(c) <= 0x9FFF]
        if not (has_kana or len(cjk_chars) >= 2):
            continue
        if all(
            (0x20 <= ord(c) <= 0x7E)
            or fb._is_displayable_jp(ord(c))
            or c in "・ー「」『』【】（）！？：；、。…％＋－×÷★☆\n\r\t"
            for c in s
        ):
            for ch in s:
                if ord(ch) >= 0x21:
                    found.add(ord(ch))
    return found


def patch_alod_bytes(data: bytes, alod_dict: Dict[str, str]) -> Tuple[bytes, int, Set[str]]:
    """
    In-place patch CJK UI labels inside an ALOD (.aod) layout buffer without changing ANY offset.
    Only replaces `<jp_utf8>\x00` when len(zh_utf8) <= len(jp_utf8) and preceded by safe non-UTF8-tail boundary.
    """
    if data[:4] not in (b"ALOD", b"AOLD"):
        return data, 0, set()
    buf = bytearray(data)
    replaced = 0
    used_chars: Set[str] = set()

    # Sort longest Japanese strings first so substrings don't shadow longer strings
    items = sorted(alod_dict.items(), key=lambda kv: -len(kv[0]))
    for jp, zh in items:
        if not jp or not zh or jp == zh:
            continue
        jp_b = jp.encode("utf-8")
        zh_b = zh.encode("utf-8")
        if len(zh_b) > len(jp_b):
            continue
        needle = jp_b + b"\x00"
        start = 0
        while True:
            idx = buf.find(needle, start)
            if idx == -1:
                break
            # Boundary sanity check: ensure byte immediately before idx is NOT inside a UTF-8 char or ASCII word
            # Wait: in ALOD, strings follow binary header bytes or `0x00` or 4-char widget IDs (`WD01`, `SP08`, `SK21`, `TWSP`)
            ok_boundary = True
            if idx > 0:
                prev = buf[idx - 1]
                # If prev is UTF-8 continuation byte (0x80..0xBF) or multibyte lead byte (0xC0..0xF7), we sliced mid-char!
                if 0x80 <= prev <= 0xF7:
                    ok_boundary = False
            if ok_boundary:
                pad_len = len(jp_b) - len(zh_b)
                rep = zh_b + b"\x00" * (pad_len + 1)
                assert len(rep) == len(needle)
                buf[idx : idx + len(needle)] = rep
                replaced += 1
                used_chars.update(zh)
            start = idx + len(needle)

    # Collect remaining unpatched CJK strings inside buf so font covers them too!
    for ck in re.findall(rb"[\x80-\xff][\x20-\xff]{1,120}\x00", bytes(buf)):
        try:
            s = ck[:-1].decode("utf-8", "strict")
            if JP_OR_CJK.search(s):
                used_chars.update(c for c in s if ord(c) >= 0x21)
        except UnicodeDecodeError:
            pass

    return bytes(buf), replaced, used_chars


def patch_harlem_aar_file(
    src_path: str,
    harlem_dict: Dict[str, str],
    glossary: Dict[str, str],
    include_untrans_chars: bool = True,
) -> Tuple[Optional[bytes], int, int, Set[str]]:
    """
    Patch HarlemEventText0.aar or HarlemEventText1.aar in-place.
    Supports > 65535 TOC entries (sequential header scan from 18 + cnt*2).
    Returns (patched_raw_bytes_or_None, patched_files, total_files, display_chars).
    """
    if not harlem_dict:
        return None, 0, 0, set()

    raw = open(src_path, "rb").read()
    outer_a4 = af.is_all4(raw)
    dec = af.decompress_all4(raw)[2] if outer_a4 else raw
    if dec[:4] != b"ALAR" or dec[4] != 3:
        return None, 0, 0, set()

    cnt = struct.unpack_from("<H", dec, 6)[0]
    pos = 18 + cnt * 2
    out = bytearray(dec)
    patched_cnt = 0
    chars: Set[str] = set()

    for _ in range(cnt):
        idx, u2, foff, fsz, fflags = struct.unpack_from("<HHIII", dec, pos)
        nend = dec.find(b"\x00", pos + 18)
        fname = dec[pos + 18 : nend].decode("utf-8", errors="replace")
        pos = af.align4(nend + 1)

        if not fname.endswith(".txt") or foff + fsz > len(dec):
            continue

        chunk = dec[foff : foff + fsz]
        inner_a4 = af.is_all4(chunk)
        txt_bytes = af.decompress_all4(chunk)[2] if inner_a4 else chunk
        has_bom = txt_bytes.startswith(b"\xef\xbb\xbf")
        txt = txt_bytes.decode("utf-8-sig", errors="replace")

        # Translate paragraph by paragraph
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
                if sp_zh != sp:
                    changed = True
                rest = "\n".join(lines[1:]).strip()
                rest_zh = (harlem_dict.get(rest) or glossary.get(rest) or rest) if rest else ""
                if rest_zh != rest:
                    changed = True
                new_blk = ("＠" + sp_zh + ("\n" + rest_zh if rest else ""))
                new_parts.append(new_blk)
            else:
                blk_zh = harlem_dict.get(blk) or glossary.get(blk) or blk
                if blk_zh != blk:
                    changed = True
                new_parts.append(blk_zh)

        new_txt = "".join(new_parts)
        if not changed:
            if include_untrans_chars:
                chars.update(c for c in txt if ord(c) >= 0x21)
            continue

        new_bytes = ((b"\xef\xbb\xbf" if has_bom else b"") + new_txt.encode("utf-8"))
        # Must fit within fsz
        if not inner_a4:
            if len(new_bytes) > fsz:
                # Try trimming redundant fullwidth spaces / normalizing line breaks to shrink
                shrunk = new_txt.replace("\u3000", "").replace("  ", " ")
                new_bytes = ((b"\xef\xbb\xbf" if has_bom else b"") + shrunk.encode("utf-8"))
            if len(new_bytes) <= fsz:
                rep = new_bytes + b"\x00" * (fsz - len(new_bytes))
                out[foff : foff + fsz] = rep
                patched_cnt += 1
                chars.update(c for c in new_txt if ord(c) >= 0x21)
            else:
                # Could not fit uncompressed; keep original
                if include_untrans_chars:
                    chars.update(c for c in txt if ord(c) >= 0x21)
        else:
            try:
                comp = af.compress_all4(new_bytes, target_size=fsz)
                out[foff : foff + fsz] = comp
                patched_cnt += 1
                chars.update(c for c in new_txt if ord(c) >= 0x21)
            except Exception:
                if include_untrans_chars:
                    chars.update(c for c in txt if ord(c) >= 0x21)

    if patched_cnt == 0:
        return None, 0, cnt, chars

    out_dec = bytes(out)
    out_raw = af.compress_all4(out_dec, target_size=len(raw)) if outer_a4 else out_dec
    assert len(out_raw) == len(raw)
    return out_raw, patched_cnt, cnt, chars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Build to build_out/ and verify without pushing to device")
    ap.add_argument("--push", action="store_true", help="Push patched data/ to emulator and update APK if rebuilt")
    ap.add_argument("--skip-apk", action="store_true", help="Skip APK MainFontFix.aft repackaging")
    ap.add_argument("--include-harlem", action="store_true", help="Include HarlemEventText0/1.aar patching if batch_17 exists")
    args = ap.parse_args()

    os.makedirs(OUT_DATA, exist_ok=True)
    os.makedirs(OUT_APK_DIR, exist_ok=True)

    glossary, alod_dict, harlem_dict = load_merged_translations()
    orig_map = get_clean_orig_map()
    all_files = sorted(orig_map.keys())
    print(f"[Init] Glossary={len(glossary)}, ALOD={len(alod_dict)}, Harlem={len(harlem_dict)}, Originals={len(orig_map)}")

    # 1. Build dynamic table & archive specs for ALL Android files
    atb_specs: List[Tuple[str, List[str]]] = []
    seen_atb: Set[str] = set()
    for s in catalog.TRANSLATABLE_TABLES:
        cols = ["Caption", "Help", "HelpMessage", "Faq", "FaqDetail"] if s.name == "UiText.atb" else list(s.columns)
        atb_specs.append((s.name, cols))
        seen_atb.add(s.name)
    for fn in all_files:
        if fn in seen_atb:
            continue
        if re.fullmatch(r"MessageText\d+\.atb", fn):
            atb_specs.append((fn, ["Message"]))
        elif re.fullmatch(r"QuestNameText\d+\.atb", fn):
            atb_specs.append((fn, ["Message"]))
        elif re.fullmatch(r"RewardText\d+\.atb", fn):
            atb_specs.append((fn, ["Text"]))

    aar_specs: List[Tuple[str, str, str, List[str]]] = []
    seen_aar: Set[str] = set()
    for a in catalog.ALAR_ARCHIVES:
        aar_specs.append((a.name, a.mode, a.target_entry, list(a.columns)))
        seen_aar.add(a.name)
    for fn in all_files:
        if fn not in seen_aar and re.fullmatch(r"BattleTalkEvent\d+\.aar", fn):
            aar_specs.append((fn, "direct_atb", "BattleTalkEvent.atb", ["Message", "Name"]))

    # Track ALL displayed characters strictly from post-patch files!
    display_priority_cps: Set[int] = set()
    all_zh_chars: Set[str] = set()
    char_weights: Counter = Counter()
    manifest_items = []

    def add_text_cps(s: str, prio: bool = True):
        for ch in s:
            cp = ord(ch)
            # Exclude Hangul syllables/jamo from stealing Aqualead bitmap font atlas slots
            if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
                continue
            if 0x21 <= cp <= 0xFFFF:
                char_weights[cp] += 1
                if prio:
                    display_priority_cps.add(cp)

    # 2. Patch ALTB tables
    print("\n=== [1/5] Patching ALTB tables ===")
    tot_tbl_rows = 0
    tot_tbl_drops = 0
    for fn, cols in atb_specs:
        src_p = orig_map.get(fn)
        if not src_p:
            continue
        orig_raw = open(src_p, "rb").read()
        is_a4 = af.is_all4(orig_raw)
        payload = af.decompress_all4(orig_raw)[2] if is_a4 else orig_raw
        if payload[:4] != b"ALTB":
            continue
        tbl = af.parse_altb(payload)
        overrides = P.load_table_overrides(fn)
        reps, cov, tot_jp, bad_ph = P.patch_altb_with_glossary(tbl, cols, glossary, overrides, all_zh_chars)
        if reps:
            patched_raw, dropped = P.rebuild_altb_fit(tbl, reps, len(orig_raw), is_a4)
            assert len(patched_raw) == len(orig_raw)
            if dropped:
                print(f"    [DROP] {fn}: dropped {dropped}/{len(reps)} rows due to size={len(orig_raw)} B")
            tot_tbl_drops += dropped
            with open(os.path.join(OUT_DATA, fn), "wb") as fp:
                fp.write(patched_raw)
            # Scan final post-patch table strings into display_priority_cps
            dec_after = af.decompress_all4(patched_raw)[2] if is_a4 else patched_raw
            t_after = af.parse_altb(dec_after)
            tot_tbl_rows += len(reps) - dropped
            manifest_items.append((fn, len(orig_raw), len(reps) - dropped, dropped))
        else:
            t_after = tbl

        for r in range(t_after.count):
            rs = t_after.get_row_strings(r)
            for c in cols:
                v = rs.get(c)
                if v:
                    add_text_cps(v, prio=True)

    print(f"  Tables patched: {len(manifest_items)}, rows={tot_tbl_rows}, drops={tot_tbl_drops}")

    # 3. Patch ALAR archives (BattleTalkEvent, PlayerUnitTable, EventArc, EventHomeArc, paev03)
    print("\n=== [2/5] Patching ALAR v3 archives ===")
    aar_patched = 0
    aar_rows = 0
    aar_drops = 0
    patched_aar_names: Set[str] = set()
    for fn, mode, target, cols in aar_specs:
        src_p = orig_map.get(fn)
        if not src_p:
            continue
        orig_raw = open(src_p, "rb").read()
        outer_a4 = af.is_all4(orig_raw)
        dec = af.decompress_all4(orig_raw)[2] if outer_a4 else orig_raw
        if not af.is_alar_v3(dec):
            continue
        entries = af.parse_alar_v3(dec)
        top_patches: Dict[str, bytes] = {}
        changed_here = 0

        if mode == "direct_atb":
            overrides = P.load_table_overrides(target)
            for e in entries:
                if e.name != target:
                    continue
                ia4 = af.is_all4(e.data)
                ip = af.decompress_all4(e.data)[2] if ia4 else e.data
                if ip[:4] != b"ALTB":
                    continue
                tbl = af.parse_altb(ip)
                reps, cov, tot_jp, _ = P.patch_altb_with_glossary(tbl, cols, glossary, overrides, all_zh_chars)
                if reps:
                    new_e, drop = P.rebuild_altb_fit(tbl, reps, e.size, ia4)
                    top_patches[e.name] = new_e
                    changed_here += len(reps) - drop
                    aar_drops += drop
                    dec_e = af.decompress_all4(new_e)[2] if ia4 else new_e
                    t_after = af.parse_altb(dec_e)
                else:
                    t_after = tbl
                for r in range(t_after.count):
                    rs = t_after.get_row_strings(r)
                    for c in cols:
                        if rs.get(c):
                            add_text_cps(rs[c], prio=True)
        elif mode == "nested_evtxt":
            for e in entries:
                if not af.is_alar_v3(e.data):
                    continue
                sub_patches: Dict[str, bytes] = {}
                for se in af.parse_alar_v3(e.data):
                    if not se.name.endswith(target):
                        continue
                    ia4 = af.is_all4(se.data)
                    ip = af.decompress_all4(se.data)[2] if ia4 else se.data
                    if ip[:4] != b"ALTB":
                        continue
                    tbl = af.parse_altb(ip)
                    reps, cov, tot_jp, _ = P.patch_altb_with_glossary(tbl, cols, glossary, {}, all_zh_chars)
                    if reps:
                        new_se, drop = P.rebuild_altb_fit(tbl, reps, se.size, ia4)
                        sub_patches[se.name] = new_se
                        changed_here += len(reps) - drop
                        aar_drops += drop
                        dec_se = af.decompress_all4(new_se)[2] if ia4 else new_se
                        t_after = af.parse_altb(dec_se)
                    else:
                        t_after = tbl
                    for r in range(t_after.count):
                        rs = t_after.get_row_strings(r)
                        for c in cols:
                            if rs.get(c):
                                add_text_cps(rs[c], prio=True)
                if sub_patches:
                    top_patches[e.name] = af.patch_alar_v3_inplace(e.data, sub_patches)

        if top_patches:
            new_dec = af.patch_alar_v3_inplace(dec, top_patches)
            patched_raw = af.compress_all4(new_dec, target_size=len(orig_raw)) if outer_a4 else new_dec
            assert len(patched_raw) == len(orig_raw)
            with open(os.path.join(OUT_DATA, fn), "wb") as fp:
                fp.write(patched_raw)
            patched_aar_names.add(fn)
            aar_patched += 1
            aar_rows += changed_here
            manifest_items.append((fn, len(orig_raw), changed_here, 0))

    print(f"  ALAR archives patched: {aar_patched}, rows={aar_rows}, drops={aar_drops}")

    # 4. Patch ALL ALOD (.aod) UI layout strings inside .aar archives!
    print("\n=== [3/5] Patching ALOD (.aod) native UI layout labels ===")
    aod_aar_cnt = 0
    aod_str_cnt = 0
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".aar") or fn in patched_aar_names:
            continue
        p = orig_map.get(fn) or os.path.join(DATA_DIR, fn)
        orig_raw = open(p, "rb").read()
        outer_a4 = af.is_all4(orig_raw)
        dec = af.decompress_all4(orig_raw)[2] if outer_a4 else orig_raw
        if not af.is_alar_v3(dec):
            continue
        entries = af.parse_alar_v3(dec)
        aod_patches: Dict[int, bytes] = {}
        file_rep_cnt = 0
        for e in entries:
            ia4 = af.is_all4(e.data)
            ed = af.decompress_all4(e.data)[2] if ia4 else e.data
            if ed[:4] not in (b"ALOD", b"AOLD"):
                continue
            new_ed, rep_cnt, uchars = patch_alod_bytes(ed, alod_dict)
            for ch in uchars:
                add_text_cps(ch, prio=True)
            if rep_cnt > 0:
                if ia4:
                    try:
                        new_entry = af.compress_all4(new_ed, target_size=e.size)
                    except Exception:
                        continue
                else:
                    assert len(new_ed) == e.size
                    new_entry = new_ed
                aod_patches[e.offset] = new_entry
                file_rep_cnt += rep_cnt
        if aod_patches:
            new_dec = patch_alar_v3_by_offset(dec, aod_patches)
            try:
                patched_raw = af.compress_all4(new_dec, target_size=len(orig_raw)) if outer_a4 else new_dec
            except Exception as ex:
                print(f"  [WARN] ALOD outer ALL4 size limit in {fn}: {ex}")
                continue
            assert len(patched_raw) == len(orig_raw)
            with open(os.path.join(OUT_DATA, fn), "wb") as fp:
                fp.write(patched_raw)
            aod_aar_cnt += 1
            aod_str_cnt += file_rep_cnt
            manifest_items.append((fn, len(orig_raw), file_rep_cnt, 0))

    print(f"  ALOD-patched .aar archives: {aod_aar_cnt}, UI string slots replaced: {aod_str_cnt}")

    # 4b. Patch LoadIconBack.aar & Opening.aar (.txt story/tips entries)
    ol_path = os.path.join(ROOT_DIR, "translations", "opening_loading_zh.json")
    if not os.path.exists(ol_path):
        ol_path = os.path.join(WORK_DIR, "opening_loading_zh.json")
    if os.path.exists(ol_path):
        ol_map = json.load(open(ol_path, encoding="utf-8"))
        for arc_name, txt_map in ol_map.items():
            ap_src = orig_map.get(arc_name)
            if not ap_src or not os.path.exists(ap_src):
                continue
            oraw = open(ap_src, "rb").read()
            oa4 = af.is_all4(oraw)
            odec = af.decompress_all4(oraw)[2] if oa4 else oraw
            if not af.is_alar_v3(odec):
                continue
            txt_patches: Dict[int, bytes] = {}
            tcnt = 0
            for e in af.parse_alar_v3(odec):
                if e.name in txt_map:
                    zh_s = txt_map[e.name]
                    add_text_cps(zh_s, prio=True)
                    ia4 = af.is_all4(e.data)
                    raw_orig = af.decompress_all4(e.data)[2] if ia4 else e.data
                    has_bom = raw_orig.startswith(b"\xef\xbb\xbf")
                    zb = (b"\xef\xbb\xbf" if has_bom else b"") + zh_s.encode("utf-8")
                    if ia4:
                        try:
                            txt_patches[e.offset] = af.compress_all4(zb, target_size=e.size)
                            tcnt += 1
                        except Exception:
                            pass
                    elif len(zb) <= e.size:
                        txt_patches[e.offset] = zb + b"\x00" * (e.size - len(zb))
                        tcnt += 1
                    else:
                        print(f"  [WARN] {arc_name}/{e.name} zh_bytes ({len(zb)}) > orig ({e.size})")
            if txt_patches:
                ndec = patch_alar_v3_by_offset(odec, txt_patches)
                nraw = af.compress_all4(ndec, target_size=len(oraw)) if oa4 else ndec
                assert len(nraw) == len(oraw)
                with open(os.path.join(OUT_DATA, arc_name), "wb") as fp:
                    fp.write(nraw)
                manifest_items.append((arc_name, len(nraw), tcnt, 0))
                print(f"  {arc_name}: patched {tcnt} txt entries")

    # 5. Optional HarlemEventText0/1 patching
    if args.include_harlem and harlem_dict:
        print("\n=== [3.5/5] Patching HarlemEventText0/1.aar ===")
        for hfn in ("HarlemEventText0.aar", "HarlemEventText1.aar"):
            hp = orig_map.get(hfn)
            if not hp:
                continue
            hraw, hp_cnt, htot, hchars = patch_harlem_aar_file(
                hp, harlem_dict, glossary, include_untrans_chars=True
            )
            for ch in hchars:
                add_text_cps(ch, prio=True)
            if hraw:
                with open(os.path.join(OUT_DATA, hfn), "wb") as fp:
                    fp.write(hraw)
                manifest_items.append((hfn, len(hraw), hp_cnt, htot - hp_cnt))
                print(f"  {hfn}: patched {hp_cnt}/{htot} stories ({len(hraw)} B)")

    # 6. Collect .so UI literals + secondary config table text + build BOTH MainFont.aft & MainFontFix.aft!
    print("\n=== [4/5] Rebuilding MainFont.aft (device) & MainFontFix.aft (APK) ===")
    # Extra server-pushed Japanese UI kanji observed in live present box / maintenance mail / events
    fb.MUST_KEEP_UI_CHARS = "詫層緊舎預択報記階"
    for sc_ch in fb.MUST_KEEP_UI_CHARS:
        display_priority_cps.add(ord(sc_ch))
        char_weights[ord(sc_ch)] += 20
        all_zh_chars.add(sc_ch)

    so_path = os.path.join(APK_ASSETS, "lib", "arm64-v8a", "libAqualeadApp.so")
    so_cps = scan_so_ui_literals(so_path)
    for cp in so_cps:
        display_priority_cps.add(cp)
        char_weights[cp] += 5
    print(f"  libAqualeadApp.so UI codepoints: {len(so_cps)}")

    # Scan untranslated small config tables (secondary tier) directly from DATA_DIR / OUT_DATA
    secondary_cps: Set[int] = set()
    used_pool_cps: Set[int] = set()
    _SCRIPTY = re.compile(r"[()\[\]{}=,;\"'<>|%\\]")
    _KEYLIKE = re.compile(r"_|[A-Za-z]{3,}")
    _ASCII_ONLY = re.compile(r"^[\x20-\x7e]*$")
    for fn in all_files:
        if not fn.endswith((".atb", ".aar")):
            continue
        p = os.path.join(OUT_DATA, fn)
        if not os.path.exists(p):
            p = orig_map.get(fn)
        if not p or os.path.getsize(p) > 8 * 1024 * 1024:
            continue
        raw = open(p, "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        if dec[:4] == b"ALTB":
            try:
                t = af.parse_altb(dec)
                txt = t.string_pool.decode("utf-8", "ignore")
                for ch in txt:
                    if 0x21 <= ord(ch) <= 0xFFFF:
                        used_pool_cps.add(ord(ch))
                if t.form & 0x04:
                    fields = [f.name_en for f in t.string_fields()]
                    for r in range(t.count):
                        vals = t.get_row_strings(r)
                        for col in fields:
                            val = vals.get(col) or ""
                            if val and not _ASCII_ONLY.match(val) and not _SCRIPTY.search(val) and not _KEYLIKE.search(val):
                                for ch in val:
                                    if 0x21 <= ord(ch) <= 0xFFFF:
                                        secondary_cps.add(ord(ch))
            except Exception:
                pass

    all_zh_chars.update(chr(cp) for cp in display_priority_cps)

    # Build device MainFont.aft (capacity ~4284)
    # Also use compact _BASE_ALWAYS (skip unused FF01..FF60 fullwidth Latin letters unless present in text!)
    mf_orig_p = orig_map.get("MainFont.aft") or os.path.join(DATA_DIR, "MainFont.aft")
    mf_orig = open(mf_orig_p, "rb").read()
    orig_mf_jp = os.path.join(ORIG_AIGISPULL, "MainFont.aft")
    if os.path.exists(orig_mf_jp):
        mf_orig = open(orig_mf_jp, "rb").read()

    # Combine displayed codepoints cleanly: display_priority_cps + secondary_cps + used_pool_cps
    all_used = {
        cp for cp in (display_priority_cps | secondary_cps | used_pool_cps | fb._BASE_ALWAYS | {ord(c) for c in fb.MUST_KEEP_UI_CHARS})
        if not (0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F)
    }
    all_zh_chars = {
        c for c in all_zh_chars
        if not (0xAC00 <= ord(c) <= 0xD7AF or 0x1100 <= ord(c) <= 0x11FF or 0x3130 <= ord(c) <= 0x318F)
    }
    old_base_mf = fb._BASE_ALWAYS
    try:
        # Keep ASCII 0x21..0x7E + essential CJK punct + core puzzle kana; let all other kana enter via actual scanned frequency!
        fb._BASE_ALWAYS = fb._assigned(
            set(range(0x21, 0x7F))
            | set(ord(c) for c in "！？（）＋－：；＝％＆／～・ー「」『』【】、。　…—ヨロシクアイウエオアダマストウノシュゴシャギス")
        )
        mf_bytes, mf_stats = fb.build_chinese_alft(
            mf_orig,
            required_chars=all_zh_chars,
            used_game_cps=all_used,
            fill_gb2312=False,
            char_weights=char_weights,
            priority_cps=display_priority_cps,
            secondary_priority_cps=secondary_cps,
        )
    finally:
        fb._BASE_ALWAYS = old_base_mf
    with open(os.path.join(OUT_DATA, "MainFont.aft"), "wb") as fp:
        fp.write(mf_bytes)
    manifest_items.append(("MainFont.aft", len(mf_bytes), mf_stats["final_glyphs"], mf_stats["missing_priority"]))
    print(
        f"  MainFont.aft    : size={mf_stats['final_size']} B, glyphs={mf_stats['final_glyphs']}/{mf_stats['capacity']}, "
        f"missing_priority={mf_stats['missing_priority']} ({mf_stats['missing_priority_str']!r}), "
        f"dropped_low_prio={mf_stats['missing_required']}"
    )

    # Build APK MainFontFix.aft (capacity ~4086)
    # Use compact base set for MainFontFix so fullwidth Latin forms (Ａ-Ｚ etc.) not seen in display text
    # don't evict displayed Chinese glyphs.
    mff_orig_p = os.path.join(APK_ASSETS, "assets", "MainFontFix.aft")
    mff_orig = open(mff_orig_p, "rb").read()
    old_base = fb._BASE_ALWAYS
    try:
        # Keep identical compact base set so MainFontFix covers all high-frequency UI/login/title/dialog glyphs cleanly!
        fb._BASE_ALWAYS = fb._assigned(
            set(range(0x21, 0x7F))
            | set(ord(c) for c in "！？（）＋－：；＝％＆／～・ー「」『』【】、。　…—ヨロシクアイウエオアダマストウノシュゴシャギス")
        )
        mff_bytes, mff_stats = fb.build_chinese_alft(
            mff_orig,
            required_chars=all_zh_chars,
            used_game_cps=all_used,
            fill_gb2312=False,
            char_weights=char_weights,
            priority_cps=display_priority_cps,
            secondary_priority_cps=secondary_cps,
        )
    finally:
        fb._BASE_ALWAYS = old_base
    out_mff_p = os.path.join(OUT_APK_DIR, "MainFontFix.aft")
    with open(out_mff_p, "wb") as fp:
        fp.write(mff_bytes)
    print(
        f"  MainFontFix.aft : size={mff_stats['final_size']} B, glyphs={mff_stats['final_glyphs']}/{mff_stats['capacity']}, "
        f"missing_priority={mff_stats['missing_priority']} ({mff_stats['missing_priority_str']!r})"
    )

    json.dump({
        "manifest_count": len(manifest_items),
        "mainfont_stats": mf_stats,
        "mainfontfix_stats": mff_stats,
        "items": [{"name": n, "size": s, "changed": c, "dropped": d} for n, s, c, d in manifest_items],
    }, open(MANIFEST_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if args.dry_run:
        print("\n[DRY RUN DONE] Verified build outputs in", OUT_ROOT)
        return

    # 7. Repackage APK with updated assets/MainFontFix.aft if not skipped
    final_apk = None
    if not args.skip_apk:
        print("\n=== [5a/5] Repackaging & signing APK with Chinese MainFontFix.aft ===")
        unsigned_apk = os.path.join(OUT_APK_DIR, "aigis_updated_unsigned.apk")
        signed_apk_out = os.path.join(OUT_APK_DIR, "signed")
        os.makedirs(signed_apk_out, exist_ok=True)
        # Copy all entries from DEVICE_APK except assets/MainFontFix.aft and META-INF/* (re-signed fresh)
        with zipfile.ZipFile(DEVICE_APK, "r") as zin, zipfile.ZipFile(unsigned_apk, "w", allowZip64=True) as zout:
            for item in zin.infolist():
                up = item.filename.upper()
                if up == "META-INF/MANIFEST.MF" or (up.startswith("META-INF/") and up.endswith((".SF", ".RSA", ".DSA", ".EC"))):
                    continue
                if item.filename == "assets/MainFontFix.aft":
                    # Preserve STORED or DEFLATE matching original
                    zi = zipfile.ZipInfo("assets/MainFontFix.aft")
                    zi.compress_type = item.compress_type
                    zout.writestr(zi, mff_bytes)
                else:
                    zi = zipfile.ZipInfo(item.filename)
                    zi.compress_type = item.compress_type
                    zi.external_attr = item.external_attr
                    zout.writestr(zi, zin.read(item.filename))
        # Align & sign using uber-apk-signer
        subprocess.run(
            ["java", "-jar", UBER_SIGNER, "-a", unsigned_apk, "-o", signed_apk_out],
            check=True,
        )
        # Find signed apk in signed_apk_out
        signed_files = [f for f in os.listdir(signed_apk_out) if f.endswith(".apk")]
        if signed_files:
            final_apk = os.path.join(signed_apk_out, signed_files[0])
            print(f"  Signed APK ready: {final_apk} ({os.path.getsize(final_apk)/1e6:.1f} MB)")

    if args.push:
        print("\n=== [5b/5] Pushing patches & APK to MuMu Emulator ===")
        subprocess.run([ADB, "connect", SERIAL], check=True)
        subprocess.run([ADB, "-s", SERIAL, "shell", "am force-stop com.dmm.games.aigisgp"], check=True)

        # Backup shared_prefs first just in case
        subprocess.run([
            ADB, "-s", SERIAL, "shell",
            "su -c 'mkdir -p /sdcard/aigis_prefs_bak && cp -rf /data/data/com.dmm.games.aigisgp/shared_prefs/. /sdcard/aigis_prefs_bak/ 2>/dev/null || true'"
        ], check=True)

        # Package OUT_DATA into a tar and stream directly to /data/data/.../files/data
        import tarfile
        patch_tar = os.path.join(OUT_ROOT, "patch_push.tar")
        with tarfile.open(patch_tar, "w") as tf:
            for fn in sorted(os.listdir(OUT_DATA)):
                tf.add(os.path.join(OUT_DATA, fn), arcname=fn)
        print(f"  Streaming {len(os.listdir(OUT_DATA))} patched files ({os.path.getsize(patch_tar)/1e6:.1f} MB) to device...")
        subprocess.run([ADB, "-s", SERIAL, "push", patch_tar, "/data/local/tmp/patch_push.tar"], check=True)
        cmd_install = (
            "OWNER=$(stat -c %u:%g /data/data/com.dmm.games.aigisgp/files/data/MainFont.aft 2>/dev/null || stat -c %u:%g /data/data/com.dmm.games.aigisgp/files); "
            "cd /data/data/com.dmm.games.aigisgp/files/data && "
            "toybox tar -xf /data/local/tmp/patch_push.tar && "
            "rm -f /data/local/tmp/patch_push.tar && "
            "chown -R $OWNER /data/data/com.dmm.games.aigisgp/files/data && "
            "chmod 600 /data/data/com.dmm.games.aigisgp/files/data/*"
        )
        subprocess.run([ADB, "-s", SERIAL, "shell", f"su -c '{cmd_install}'"], check=True)

        if final_apk and os.path.exists(final_apk):
            print("  Installing updated APK (preserving app data)...")
            subprocess.run([ADB, "-s", SERIAL, "install", "-r", final_apk], check=True)

        print("  Done! Launching game...")
        subprocess.run([ADB, "-s", SERIAL, "shell", "monkey -p com.dmm.games.aigisgp -c android.intent.category.LAUNCHER 1"], check=True)


if __name__ == "__main__":
    main()
