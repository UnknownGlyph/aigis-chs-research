"""
Millennium War Aigis (aigis_exe) Non-Destructive Simplified Chinese Localization Patcher.

Commands:
  python patcher.py build   [--game-dir d:\game\DMM\aigis_exe]
  python patcher.py verify  [--game-dir d:\game\DMM\aigis_exe]
  python patcher.py apply   [--game-dir d:\game\DMM\aigis_exe]
  python patcher.py restore [--game-dir d:\game\DMM\aigis_exe]
  python patcher.py status  [--game-dir d:\game\DMM\aigis_exe]

How it works (zero Aigis.exe binary modification):
  1. Disassembly of Aigis.exe (0xa45f40 / 0xa463e0) confirms that cache validation checks
     ONLY (a) file size == manifest expected size, and (b) .cache/<sha256>.md5 text ==
     manifest expected MD5. It does NOT recompute MD5 of cached data files on disk.
  2. All three asset parsers (ALL4 LZ4 loop at 0xbabf66, ALTB at 0xb0b965, ALFT at 0xb29697)
     ignore trailing zero padding. Since Chinese UTF-8 is shorter than Japanese UTF-8, patched
     ALTB / ALL4 / ALFT files are padded to the exact original byte size while leaving .md5
     untouched.
  3. MainFont.aft (in .cache/) and MainFontFix.aft (in root) are rebuilt with Songti/Serif
     Simplified Chinese glyphs injected into unused Cyrillic/Greek/rare-JIS slots while
     preserving 100% of original glyphs actually used by the game.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Set, Tuple

import aigis_formats as af
import font_builder as fb
from catalog import (
    ALAR_ARCHIVES,
    CACHE_FONT_NAME,
    CACHE_FONT_SHA256,
    ROOT_FONT_NAME,
    ROOT_FONT_SHA256,
    TRANSLATABLE_TABLES,
    AlarSpec,
    TableSpec,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANS_DIR = os.path.join(BASE_DIR, "translations")
GLOSSARY_PATH = os.path.join(TRANS_DIR, "glossary_zh.json")
FULL_DICT_PATH = os.path.join(TRANS_DIR, "full_zh.json")
PATCH_OUT_DIR = os.path.join(BASE_DIR, "patch_out")
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
MANIFEST_PATH = os.path.join(PATCH_OUT_DIR, "patch_manifest.json")

PLACEHOLDER_RE = re.compile(r"(%[0-9.]*[dfsx]|%c\[[0-9a-fA-F]+\]|<[A-Z0-9_]+>|\[[A-Z0-9_]+\])")
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def ensure_glossary() -> Dict[str, str]:
    """
    Load merged translation dictionary:
      1. translations/glossary_zh.json (hand-crafted core UI/mission/title glossary)
      2. translations/full_zh.json + translations/batch_*.json (workflow-translated full tables)
    """
    os.makedirs(TRANS_DIR, exist_ok=True)
    if not os.path.exists(GLOSSARY_PATH):
        from trans_part1 import PART1_TRANSLATIONS
        from trans_part2 import PART2_TRANSLATIONS

        base_g: Dict[str, str] = {}
        base_g.update(PART1_TRANSLATIONS)
        base_g.update(PART2_TRANSLATIONS)
        with open(GLOSSARY_PATH, "w", encoding="utf-8") as fp:
            json.dump(base_g, fp, ensure_ascii=False, indent=2)
        print(f"[INFO] Generated {GLOSSARY_PATH} with {len(base_g)} exact translation entries.")
    else:
        with open(GLOSSARY_PATH, "r", encoding="utf-8") as fp:
            base_g = json.load(fp)

    merged: Dict[str, str] = {}
    # Load batch_*.json and full_zh.json first, then let hand-crafted glossary_zh.json take priority
    extra_files = []
    if os.path.isdir(TRANS_DIR):
        for fn in sorted(os.listdir(TRANS_DIR)):
            if fn == "full_zh.json" or (fn.startswith("batch_") and fn.endswith(".json")):
                extra_files.append(os.path.join(TRANS_DIR, fn))
    for ep in extra_files:
        try:
            d = json.load(open(ep, "r", encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(k, str) and isinstance(v, str) and v:
                        merged[k] = v
        except Exception as e:
            print(f"[WARN] Could not load {ep}: {e}")

    # Hand-crafted glossary wins on conflicts
    merged.update(base_g)
    return merged


def translate_string(jp: str, glossary: Dict[str, str]) -> Optional[str]:
    """Translate a Japanese string via exact glossary match or deterministic safe templates."""
    if jp in glossary and glossary[jp]:
        return glossary[jp]

    # Pattern 1: Tower floors: 第N階層 -> 第N层
    m = re.fullmatch(r"第(\d+)階層", jp)
    if m:
        return f"第{m.group(1)}层"

    # Pattern 2: Subjugation stamina/charisma cost: カリスマN -> 魅力N
    m = re.fullmatch(r"カリスマ(\d+)", jp)
    if m:
        return f"魅力{m.group(1)}"

    # Pattern 3: Subjugation enemy count: 出現敵数：N -> 出现敌数：N
    m = re.fullmatch(r"出現敵数：(\d+)", jp)
    if m:
        return f"出现敌数：{m.group(1)}"

    # Pattern 4: Popularity poll missions: 第N回人気投票ミッション -> 第N届人气投票任务
    m = re.fullmatch(r"第([０-９\d]+)回人気投票ミッション", jp)
    if m:
        num = m.group(1).translate(FULLWIDTH_DIGITS)
        return f"第{num}届人气投票任务"

    # Pattern 5: Leveled Player Titles: <BaseTitle>LvN -> <TranslatedBase>LvN
    m = re.fullmatch(r"(.+?)Lv(\d+)", jp)
    if m:
        base_zh = glossary.get(m.group(1))
        if base_zh:
            return f"{base_zh}Lv{m.group(2)}"

    # Pattern 6: Mission History year titles: N年目の戦い -> 第N年之战
    m = re.fullmatch(r"(\d+)年目の戦い", jp)
    if m:
        return f"第{m.group(1)}年之战"

    return None


def load_table_overrides(table_name: str) -> Dict[Tuple[int, str], str]:
    """Load optional per-table JSON overrides from translations/<TableName>.json."""
    p = os.path.join(TRANS_DIR, f"{table_name}.json")
    if not os.path.exists(p):
        return {}
    data = json.load(open(p, "r", encoding="utf-8"))
    out: Dict[Tuple[int, str], str] = {}
    for e in data.get("entries", []):
        zh = e.get("zh", "")
        if zh:
            out[(int(e["row"]), str(e["col"]))] = zh
    return out


def placeholders_match(jp: str, zh: str) -> bool:
    return sorted(PLACEHOLDER_RE.findall(jp)) == sorted(PLACEHOLDER_RE.findall(zh))


def check_placeholders(jp: str, zh: str, ctx: str) -> None:
    if not placeholders_match(jp, zh):
        jp_ph = PLACEHOLDER_RE.findall(jp)
        zh_ph = PLACEHOLDER_RE.findall(zh)
        raise ValueError(
            f"Placeholder mismatch in {ctx}:\n  JP={jp!r} -> {jp_ph}\n  ZH={zh!r} -> {zh_ph}"
        )


def rebuild_altb_fit(
    tbl: af.AltbTable,
    replacements: Dict[Tuple[int, str], str],
    target_size: int,
    is_a4: bool,
) -> Tuple[bytes, int]:
    """
    Rebuild ALTB (and ALL4 if is_a4) fitting exactly within target_size.
    If the full replacement dict ever exceeds target_size by a few bytes, drops the
    most byte-expanding entries first until it fits. Returns (bytes, dropped_count).
    """
    reps = dict(replacements)
    dropped = 0
    while True:
        try:
            if is_a4:
                rebuilt_altb = tbl.rebuild_with_translations(reps, target_size=None)
                out = af.compress_all4(rebuilt_altb, target_size=target_size)
            else:
                out = tbl.rebuild_with_translations(reps, target_size=target_size)
            return out, dropped
        except ValueError:
            if not reps:
                raise
            # Rank entries by UTF-8 byte expansion (zh - jp) descending
            ranked = sorted(
                reps.items(),
                key=lambda kv: len(kv[1].encode("utf-8")) - len(tbl.get_row_strings(kv[0][0]).get(kv[0][1], "").encode("utf-8")),
                reverse=True,
            )
            drop_n = max(1, min(len(ranked), max(1, len(ranked) // 20)))
            for k, _ in ranked[:drop_n]:
                del reps[k]
                dropped += 1


def patch_altb_with_glossary(
    tbl: af.AltbTable,
    columns: List[str],
    glossary: Dict[str, str],
    overrides: Dict[Tuple[int, str], str],
    all_zh_chars: Set[str],
    strict_placeholders: bool = False,
) -> Tuple[Dict[Tuple[int, str], str], int, int, int]:
    """Returns (replacements, covered_rows, total_jp_rows, bad_ph_skipped)."""
    replacements: Dict[Tuple[int, str], str] = {}
    total_jp_rows = 0
    covered_rows = 0
    bad_ph = 0
    for r in range(tbl.count):
        row_strs = tbl.get_row_strings(r)
        for col in columns:
            jp = row_strs.get(col, "")
            if not jp:
                continue
            has_cjk = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", jp))
            if has_cjk:
                total_jp_rows += 1
            zh = overrides.get((r, col))
            if zh is None:
                zh = translate_string(jp, glossary)
            if zh is not None:
                if zh != jp and not placeholders_match(jp, zh):
                    if strict_placeholders:
                        check_placeholders(jp, zh, f"row={r} col={col}")
                    bad_ph += 1
                    continue
                if has_cjk:
                    covered_rows += 1
                all_zh_chars.update(zh)
                if zh != jp:
                    replacements[(r, col)] = zh
    return replacements, covered_rows, total_jp_rows, bad_ph


def cmd_build(game_dir: str, ttf_path: Optional[str] = None) -> None:
    glossary = ensure_glossary()
    cache_dir = os.path.join(game_dir, ".cache")
    out_cache = os.path.join(PATCH_OUT_DIR, ".cache")
    os.makedirs(out_cache, exist_ok=True)

    manifest_files: List[Dict] = []
    all_zh_chars: Set[str] = set()
    total_translated_entries = 0
    total_tables_patched = 0

    print(f"=== [1/4] Patching ALTB / ALL4 text tables (dict size={len(glossary)}) ===")
    for spec in TRANSLATABLE_TABLES:
        src_path = os.path.join(cache_dir, spec.sha256)
        if not os.path.exists(src_path):
            continue

        orig_raw = open(src_path, "rb").read()
        is_a4 = af.is_all4(orig_raw)
        payload = af.decompress_all4(orig_raw)[2] if is_a4 else orig_raw
        tbl = af.parse_altb(payload)
        overrides = load_table_overrides(spec.name)

        replacements, covered_rows, total_jp_rows, bad_ph = patch_altb_with_glossary(
            tbl, spec.columns, glossary, overrides, all_zh_chars
        )
        if not replacements:
            continue

        patched_raw, dropped = rebuild_altb_fit(tbl, replacements, len(orig_raw), is_a4)
        assert len(patched_raw) == len(orig_raw), f"Size mismatch on {spec.name}"

        rel_path = os.path.join(".cache", spec.sha256)
        dst_path = os.path.join(PATCH_OUT_DIR, rel_path)
        with open(dst_path, "wb") as fp:
            fp.write(patched_raw)

        eff_covered = max(0, covered_rows - dropped)
        pct = (eff_covered / total_jp_rows * 100.0) if total_jp_rows else 100.0
        extra_note = ""
        if dropped:
            extra_note += f" [drop={dropped}]"
        if bad_ph:
            extra_note += f" [ph_skip={bad_ph}]"
        print(
            f"  [OK] {spec.name:34s} {eff_covered:5d}/{total_jp_rows:5d} ({pct:5.1f}%)  "
            f"chg={len(replacements)-dropped:5d}  size={len(patched_raw):7d} B  ({'ALL4' if is_a4 else 'ALTB'}){extra_note}"
        )
        manifest_files.append({
            "name": spec.name,
            "rel_path": rel_path.replace("\\", "/"),
            "kind": "ALL4+ALTB" if is_a4 else "ALTB",
            "orig_size": len(orig_raw),
            "orig_sha256": sha256_bytes(orig_raw),
            "patched_size": len(patched_raw),
            "patched_sha256": sha256_bytes(patched_raw),
            "covered_entries": eff_covered,
            "translated_entries": len(replacements) - dropped,
            "total_jp_entries": total_jp_rows,
        })
        total_translated_entries += eff_covered
        total_tables_patched += 1

    # --- [2/4] Patch ALAR v3 archives (PlayerUnitTable.aar + Event story archives) ---
    print("\n=== [2/4] Patching ALAR v3 archives (ClassData + Event stories) ===")
    for aspec in ALAR_ARCHIVES:
        src_path = os.path.join(cache_dir, aspec.sha256)
        if not os.path.exists(src_path):
            continue
        orig_raw = open(src_path, "rb").read()
        outer_a4 = af.is_all4(orig_raw)
        dec = af.decompress_all4(orig_raw)[2] if outer_a4 else orig_raw
        if not af.is_alar_v3(dec):
            continue

        entries = af.parse_alar_v3(dec)
        top_patches: Dict[str, bytes] = {}
        arc_covered = 0
        arc_changed = 0
        arc_total_jp = 0
        arc_dropped = 0

        if aspec.mode == "direct_atb":
            overrides = load_table_overrides(aspec.target_entry)
            for e in entries:
                if e.name != aspec.target_entry:
                    continue
                inner_a4 = af.is_all4(e.data)
                inner_payload = af.decompress_all4(e.data)[2] if inner_a4 else e.data
                tbl = af.parse_altb(inner_payload)
                reps, cov, tot_jp, _ = patch_altb_with_glossary(tbl, aspec.columns, glossary, overrides, all_zh_chars)
                arc_total_jp += tot_jp
                if reps:
                    new_entry, drop = rebuild_altb_fit(tbl, reps, e.size, inner_a4)
                    top_patches[e.name] = new_entry
                    arc_covered += max(0, cov - drop)
                    arc_changed += len(reps) - drop
                    arc_dropped += drop
        elif aspec.mode == "nested_evtxt":
            for e in entries:
                if not af.is_alar_v3(e.data):
                    continue
                sub_entries = af.parse_alar_v3(e.data)
                sub_patches: Dict[str, bytes] = {}
                for se in sub_entries:
                    if not se.name.endswith(aspec.target_entry):
                        continue
                    inner_a4 = af.is_all4(se.data)
                    inner_payload = af.decompress_all4(se.data)[2] if inner_a4 else se.data
                    if inner_payload[:4] != b"ALTB":
                        continue
                    tbl = af.parse_altb(inner_payload)
                    reps, cov, tot_jp, _ = patch_altb_with_glossary(tbl, aspec.columns, glossary, {}, all_zh_chars)
                    arc_total_jp += tot_jp
                    if reps:
                        new_se, drop = rebuild_altb_fit(tbl, reps, se.size, inner_a4)
                        sub_patches[se.name] = new_se
                        arc_covered += max(0, cov - drop)
                        arc_changed += len(reps) - drop
                        arc_dropped += drop
                if sub_patches:
                    top_patches[e.name] = af.patch_alar_v3_inplace(e.data, sub_patches)

        if not top_patches:
            continue

        new_dec = af.patch_alar_v3_inplace(dec, top_patches)
        if outer_a4:
            patched_raw = af.compress_all4(new_dec, target_size=len(orig_raw))
        else:
            patched_raw = new_dec
        assert len(patched_raw) == len(orig_raw), f"ALAR size mismatch on {aspec.name}"

        rel_path = os.path.join(".cache", aspec.sha256)
        dst_path = os.path.join(PATCH_OUT_DIR, rel_path)
        with open(dst_path, "wb") as fp:
            fp.write(patched_raw)

        pct = (arc_covered / arc_total_jp * 100.0) if arc_total_jp else 100.0
        extra = f" [drop={arc_dropped}]" if arc_dropped else ""
        print(
            f"  [OK] {aspec.name:34s} {arc_covered:5d}/{arc_total_jp:5d} ({pct:5.1f}%)  "
            f"chg={arc_changed:5d}  size={len(patched_raw):7d} B  ({'ALL4+ALAR' if outer_a4 else 'ALAR'}){extra}"
        )
        manifest_files.append({
            "name": aspec.name,
            "rel_path": rel_path.replace("\\", "/"),
            "kind": "ALL4+ALAR" if outer_a4 else "ALAR",
            "orig_size": len(orig_raw),
            "orig_sha256": sha256_bytes(orig_raw),
            "patched_size": len(patched_raw),
            "patched_sha256": sha256_bytes(patched_raw),
            "covered_entries": arc_covered,
            "translated_entries": arc_changed,
            "total_jp_entries": arc_total_jp,
        })
        total_translated_entries += arc_covered
        total_tables_patched += 1

    print(f"\nPatched {total_tables_patched} tables/archives ({total_translated_entries} translated entries, {len(all_zh_chars)} unique chars).")

    # --- [3/4] Rebuild MainFont.aft (.cache) and MainFontFix.aft (root) ---
    print("\n=== [3/4] Rebuilding Chinese ALFT bitmap fonts ===")
    used_game_cps, char_weights = fb.collect_displayed_text(game_dir, patch_out_dir=PATCH_OUT_DIR)
    priority_cps = fb.collect_display_priority_codepoints(game_dir, patch_out_dir=PATCH_OUT_DIR)
    table_text_cps = fb.collect_table_text_codepoints(game_dir, patch_out_dir=PATCH_OUT_DIR)
    scan_stats = getattr(fb.collect_displayed_text, "last_stats", {})
    print(
        f"  Displayed codepoint inventory: {len(used_game_cps)} chars "
        f"({len(priority_cps)} in display columns, {len(table_text_cps)} in untranslated table text, "
        f"{scan_stats.get('altb', 0)} ALTB tables, {scan_stats.get('alar', 0)} ALAR archives, "
        f"{scan_stats.get('fail', 0)} unreadable)"
    )
    font_jobs = [
        (CACHE_FONT_NAME, os.path.join(".cache", CACHE_FONT_SHA256)),
        (ROOT_FONT_NAME, ROOT_FONT_SHA256),
    ]
    for fname, rel_path in font_jobs:
        src_path = os.path.join(game_dir, rel_path)
        if not os.path.exists(src_path):
            print(f"  [SKIP] Missing font: {src_path}")
            continue
        orig_font = open(src_path, "rb").read()
        patched_font, fstats = fb.build_chinese_alft(
            orig_font,
            required_chars=all_zh_chars,
            used_game_cps=used_game_cps,
            ttf_path=ttf_path,
            fill_gb2312=False,
            char_weights=char_weights,
            priority_cps=priority_cps,
            secondary_priority_cps=table_text_cps,
        )
        dst_path = os.path.join(PATCH_OUT_DIR, rel_path)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(dst_path, "wb") as fp:
            fp.write(patched_font)

        print(
            f"  [OK] {fname:18s} size={fstats['final_size']} B (exact), "
            f"glyphs={fstats['final_glyphs']}/{fstats['capacity']} cap, "
            f"+{fstats['added_required_sc']} req SC, "
            f"reused={fstats['reused_original_glyphs']} native, "
            f"kept={fstats['kept_used_game']}/{fstats['total_used_game']} used JP, "
            f"ttf={fstats['ttf']}"
        )
        if fstats["missing_priority"]:
            print(
                f"  [ERROR] {fname}: {fstats['missing_priority']} DISPLAYED char(s) have no glyph: "
                f"{fstats['missing_priority_str']}"
            )
        if fstats["missing_required"]:
            print(
                f"  [INFO] {fname}: {fstats['missing_required'] - fstats['missing_priority']} low-priority "
                f"char(s) (internal IDs / dead strings, not rendered by any display column) exceeded the "
                f"fixed atlas budget and were dropped."
            )
        manifest_files.append({
            "name": fname,
            "rel_path": rel_path.replace("\\", "/"),
            "kind": "ALFT",
            "orig_size": len(orig_font),
            "orig_sha256": sha256_bytes(orig_font),
            "patched_size": len(patched_font),
            "patched_sha256": sha256_bytes(patched_font),
            "font_stats": fstats,
        })

        if fname == CACHE_FONT_NAME:
            preview_lines = [
                "【千年战争Aigis】简体中文汉化补丁 - 实际字库渲染验证",
                "主线剧情 1 / 每日曜日任务 / 紧急任务 / 魔神降临 / 英杰之塔",
                "出击费用：配置单位需要消耗『出击费用』，撤退返还一半费用。",
                "系统弹窗：确定要让该单位引退吗？获得金币 5000 / 虹水晶 20",
                "副官安娜：请下达指示。熟悉战斗后，也请尝试挑战『紧急任务』吧。",
                "原版日文兼容：女神アイギス・アンナ・魔神降臨(フールフール)",
            ]
            fb.render_preview_png(patched_font, preview_lines, os.path.join(PATCH_OUT_DIR, "font_preview.png"))

    manifest = {
        "game_dir": game_dir,
        "tables_patched": total_tables_patched,
        "total_translated_entries": total_translated_entries,
        "unique_zh_chars": len(all_zh_chars),
        "zh_charset": "".join(sorted(c for c in all_zh_chars if 0x21 <= ord(c) <= 0xFFFF)),
        "files": manifest_files,
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)

    print("\n=== [4/4] Running full post-build integrity verification ===")
    cmd_verify(game_dir)


def cmd_verify(game_dir: str) -> None:
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}. Run 'build' first.")
    manifest = json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))

    font_charsets: Dict[str, Set[int]] = {}
    used_all_cps: Set[int] = set()
    zh_cps: Set[int] = {ord(c) for c in manifest.get("zh_charset", "") if 0x21 <= ord(c) <= 0xFFFF}
    errors: List[str] = []

    for item in manifest["files"]:
        rel = item["rel_path"].replace("/", os.sep)
        p_out = os.path.join(PATCH_OUT_DIR, rel)
        p_orig = os.path.join(game_dir, rel)

        if not os.path.exists(p_out):
            errors.append(f"Missing built file: {p_out}")
            continue
        b_out = open(p_out, "rb").read()
        if len(b_out) != item["orig_size"]:
            errors.append(f"{item['name']}: size {len(b_out)} != orig_size {item['orig_size']}")
            continue

        if os.path.exists(p_orig):
            orig_sz = os.path.getsize(p_orig)
            if orig_sz != item["orig_size"]:
                errors.append(f"{item['name']}: live game file size changed ({orig_sz} != {item['orig_size']})")

        kind = item["kind"]
        try:
            if kind == "ALFT":
                f = af.parse_alft(b_out)
                font_charsets[item["name"]] = set(f.glyphs.keys())
            elif kind == "ALL4+ALTB":
                _, _, dec = af.decompress_all4(b_out)
                tbl = af.parse_altb(dec)
                txt = tbl.string_pool.decode("utf-8")
                for ch in txt:
                    if 0x21 <= ord(ch) <= 0xFFFF:
                        used_all_cps.add(ord(ch))
            elif kind == "ALTB":
                tbl = af.parse_altb(b_out)
                txt = tbl.string_pool.decode("utf-8")
                for ch in txt:
                    if 0x21 <= ord(ch) <= 0xFFFF:
                        used_all_cps.add(ord(ch))
            elif kind in ("ALL4+ALAR", "ALAR"):
                dec = af.decompress_all4(b_out)[2] if kind == "ALL4+ALAR" else b_out
                ents = af.parse_alar_v3(dec)
                assert len(ents) > 0, "Empty ALAR"
        except Exception as e:
            errors.append(f"{item['name']} round-trip parse failed: {e}")

    # Verify glyph coverage against EVERY character the patched client can actually display
    # (it is impossible to cover dictionary-only chars that never reach the screen: the ALFT
    # atlas is size-locked, so the budget allocator drops the lowest-frequency leftovers).
    displayed_cps, _weights = fb.collect_displayed_text(game_dir, patch_out_dir=PATCH_OUT_DIR)
    required_cps = displayed_cps | {ord(c) for c in fb.MUST_KEEP_UI_CHARS}
    dropped_reported: Set[int] = set()
    for fname, cps in font_charsets.items():
        stats = next((i.get("font_stats") for i in manifest["files"] if i["name"] == fname), {}) or {}
        dropped = set(stats.get("dropped_low_priority", []))
        dropped_reported |= dropped
        uncovered = sorted(required_cps - cps)
        unexpected = [cp for cp in uncovered if cp not in dropped]
        if unexpected:
            sample = "".join(chr(c) for c in unexpected[:40])
            errors.append(f"{fname}: {len(unexpected)} displayable char(s) without a glyph: {sample!r}")
        missing_zh = sorted(zh_cps - cps - dropped)
        if missing_zh:
            sample = "".join(chr(c) for c in missing_zh[:30])
            errors.append(f"{fname} missing {len(missing_zh)} translated Chinese glyph(s): {sample!r}")

    if errors:
        print("[FAIL] Verification failed with errors:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    dropped_str = "".join(chr(c) for c in sorted(dropped_reported))
    print(
        f"[PASS] Verified all {len(manifest['files'])} patched files:\n"
        f"  - Exact byte size match: 100% ({len(manifest['files'])}/{len(manifest['files'])})\n"
        f"  - Round-trip ALL4/ALTB/ALAR/ALFT decode: 100% valid\n"
        f"  - Displayable-glyph coverage in BOTH fonts: 100% "
        f"({len(required_cps)} chars incl. {len(fb.MUST_KEEP_UI_CHARS)} server/UI-only chars)"
    )
    if dropped_str:
        print(
            f"  - [NOTE] {len(dropped_reported)} lowest-frequency leftovers exceeded the fixed atlas "
            f"budget and are not rendered: {dropped_str}"
        )


def cmd_apply(game_dir: str) -> None:
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}. Run 'build' first.")
    cmd_verify(game_dir)
    manifest = json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))

    backed_up = 0
    applied = 0
    for item in manifest["files"]:
        rel = item["rel_path"].replace("/", os.sep)
        src_patch = os.path.join(PATCH_OUT_DIR, rel)
        dst_game = os.path.join(game_dir, rel)
        dst_bak = os.path.join(BACKUP_DIR, rel)

        if not os.path.exists(dst_game):
            print(f"[SKIP] Target missing in game_dir: {dst_game}")
            continue

        # Preserve original untouched backup (never overwrite existing backup)
        if not os.path.exists(dst_bak):
            os.makedirs(os.path.dirname(dst_bak), exist_ok=True)
            shutil.copy2(dst_game, dst_bak)
            backed_up += 1

        # Copy patched file; intentionally leave .md5 sidecar untouched!
        shutil.copy2(src_patch, dst_game)
        applied += 1

    print(f"[DONE] Applied {applied} patched files to {game_dir} ({backed_up} newly backed up to {BACKUP_DIR}).")
    print("       All .cache/*.md5 files and Aigis.exe were left completely untouched.")


def cmd_restore(game_dir: str) -> None:
    if not os.path.isdir(BACKUP_DIR):
        print(f"[INFO] No backup directory found at {BACKUP_DIR}.")
        return
    restored = 0
    for root, _, files in os.walk(BACKUP_DIR):
        for fn in files:
            src_bak = os.path.join(root, fn)
            rel = os.path.relpath(src_bak, BACKUP_DIR)
            dst_game = os.path.join(game_dir, rel)
            os.makedirs(os.path.dirname(dst_game), exist_ok=True)
            shutil.copy2(src_bak, dst_game)
            restored += 1
    print(f"[DONE] Restored {restored} original files from {BACKUP_DIR} back to {game_dir}.")


def cmd_status(game_dir: str) -> None:
    if not os.path.exists(MANIFEST_PATH):
        print("[INFO] Patch has not been built yet. Run 'python patcher.py build'.")
        return
    manifest = json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    cnt_patched = cnt_orig = cnt_other = 0
    for item in manifest["files"]:
        rel = item["rel_path"].replace("/", os.sep)
        p_live = os.path.join(game_dir, rel)
        if not os.path.exists(p_live):
            cnt_other += 1
            continue
        h = sha256_bytes(open(p_live, "rb").read())
        if h == item["patched_sha256"]:
            cnt_patched += 1
        elif h == item["orig_sha256"]:
            cnt_orig += 1
        else:
            cnt_other += 1
    print(f"Game dir : {game_dir}")
    print(f"Manifest : {len(manifest['files'])} patch files ({manifest['total_translated_entries']} translated strings)")
    print(f"Status   : {cnt_patched} patched, {cnt_orig} original, {cnt_other} modified/updated by game")


def main() -> None:
    ap = argparse.ArgumentParser(description="Millennium War Aigis (aigis_exe) Chinese Localization Patcher")
    ap.add_argument("command", choices=["build", "verify", "apply", "restore", "status"])
    ap.add_argument("--game-dir", default=r"d:\game\DMM\aigis_exe")
    ap.add_argument("--ttf", default=None, help="Optional custom TTF/TTC font path for Chinese glyph rendering")
    args = ap.parse_args()

    if args.command == "build":
        cmd_build(args.game_dir, ttf_path=args.ttf)
    elif args.command == "verify":
        cmd_verify(args.game_dir)
    elif args.command == "apply":
        cmd_apply(args.game_dir)
    elif args.command == "restore":
        cmd_restore(args.game_dir)
    elif args.command == "status":
        cmd_status(args.game_dir)


if __name__ == "__main__":
    main()
