#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retranslate_installed.py — 把 translations/*.json 里的译文修正，直接同步进“已经打过补丁”的游戏表

典型用途：
  * `backup/` 里的官方原始文件已经丢失（被官方更新覆盖 / 未保留），无法再执行
    `patcher.py build` 从日文原位重建；
  * 只修改了若干条译文（补翻残留日文、替换生僻字），希望原地生效而不动其它内容。

原理：
  以 git 中 `HEAD` 版本的 `translations/*.json` 为“旧译文”，工作区文件为“新译文”，
  得到「旧译文 → 新译文」映射；再扫描游戏目录里白名单表中的字符串，命中旧译文的行
  原地改写为新译文，按原文件字节数回封（不足补零），从而保持客户端缓存校验通过。

用法：
  python retranslate_installed.py                            # 仅输出到 patch_out/（默认，安全）
  python retranslate_installed.py --write                    # 直接写入游戏目录（自动备份）
  python retranslate_installed.py --old-map map.json         # 不用 git，直接给 {旧译文: 新译文}
  python retranslate_installed.py --game-dir "d:\\game\\DMM\\aigis_exe"

退出码：0 = 成功（或有修改但全部回封成功）；1 = 存在回封失败
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Set, Tuple

import aigis_formats as af
import patcher as P
from catalog import ALAR_ARCHIVES, TRANSLATABLE_TABLES

DEFAULT_GAME_DIR = r"d:\game\DMM\aigis_exe"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANS_DIR = os.path.join(BASE_DIR, "translations")
PATCH_OUT_DIR = os.path.join(BASE_DIR, "patch_out")
BACKUP_DIR = os.path.join(BASE_DIR, "backup_retranslate")


def collect_value_map(repo_dir: str, map_path: Optional[str] = None) -> Dict[str, str]:
    """Build {old_translation: new_translation} from git HEAD vs working tree (or a JSON file)."""
    if map_path:
        with open(map_path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str) and k != v}

    mapping: Dict[str, str] = {}
    conflicts: Set[str] = set()
    for fn in sorted(os.listdir(TRANS_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(TRANS_DIR, fn)
        rel = os.path.relpath(path, repo_dir).replace(os.sep, "/")
        try:
            old_raw = subprocess.check_output(
                ["git", "-C", repo_dir, "show", f"HEAD:{rel}"], stderr=subprocess.DEVNULL
            ).decode("utf-8")
            old = json.loads(old_raw)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        new = json.load(open(path, "r", encoding="utf-8"))
        for k, old_v in old.items():
            new_v = new.get(k)
            if not isinstance(old_v, str) or not isinstance(new_v, str) or old_v == new_v:
                continue
            prev = mapping.get(old_v)
            if prev is not None and prev != new_v:
                conflicts.add(old_v)
                continue
            mapping[old_v] = new_v
    for c in conflicts:
        mapping.pop(c, None)
    if conflicts:
        print(f"[WARN] {len(conflicts)} old translation(s) map to several new values, skipped (ambiguous).")
    return mapping


def _row_replacements(tbl: af.AltbTable, columns: List[str], vmap: Dict[str, str]) -> Dict[Tuple[int, str], str]:
    reps: Dict[Tuple[int, str], str] = {}
    for r in range(tbl.count):
        strs = tbl.get_row_strings(r)
        for col in columns:
            cur = strs.get(col)
            if cur and cur in vmap and vmap[cur] != cur:
                reps[(r, col)] = vmap[cur]
    return reps


def retranslate(game_dir: str, vmap: Dict[str, str], write_back: bool) -> int:
    cache_dir = os.path.join(game_dir, ".cache")
    os.makedirs(PATCH_OUT_DIR, exist_ok=True)
    total_rows = 0
    failed = 0

    def emit(rel_path: str, data: bytes) -> None:
        dst = os.path.join(PATCH_OUT_DIR, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fp:
            fp.write(data)
        if write_back:
            live = os.path.join(game_dir, rel_path)
            bak = os.path.join(BACKUP_DIR, rel_path)
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            if os.path.exists(live) and not os.path.exists(bak):
                open(bak, "wb").write(open(live, "rb").read())
            with open(live, "wb") as fp:
                fp.write(data)

    # --- plain tables ---
    for spec in TRANSLATABLE_TABLES:
        src = os.path.join(cache_dir, spec.sha256)
        if not os.path.exists(src):
            continue
        raw = open(src, "rb").read()
        outer_a4 = af.is_all4(raw)
        payload = af.decompress_all4(raw)[2] if outer_a4 else raw
        if payload[:4] != b"ALTB":
            continue
        tbl = af.parse_altb(payload)
        reps = _row_replacements(tbl, spec.columns, vmap)
        if not reps:
            continue
        try:
            new_payload = tbl.rebuild_with_translations(reps, target_size=len(payload))
            new_raw = af.compress_all4(new_payload, target_size=len(raw)) if outer_a4 else new_payload
            assert len(new_raw) == len(raw)
        except Exception as e:
            print(f"  [FAIL] {spec.name}: {e}")
            failed += 1
            continue
        emit(os.path.join(".cache", spec.sha256), new_raw)
        total_rows += len(reps)
        print(f"  [OK] {spec.name:32s} {len(reps):4d} row(s) re-translated")

    # --- ALAR v3 archives ---
    for aspec in ALAR_ARCHIVES:
        src = os.path.join(cache_dir, aspec.sha256)
        if not os.path.exists(src):
            continue
        raw = open(src, "rb").read()
        outer_a4 = af.is_all4(raw)
        dec = af.decompress_all4(raw)[2] if outer_a4 else raw
        if not af.is_alar_v3(dec):
            continue
        entries = af.parse_alar_v3(dec)
        top_patches: Dict[str, bytes] = {}
        changed = 0

        if aspec.mode == "direct_atb":
            for e in entries:
                if e.name != aspec.target_entry:
                    continue
                inner_a4 = af.is_all4(e.data)
                inner = af.decompress_all4(e.data)[2] if inner_a4 else e.data
                if inner[:4] != b"ALTB":
                    continue
                tbl = af.parse_altb(inner)
                reps = _row_replacements(tbl, aspec.columns, vmap)
                if not reps:
                    continue
                new_entry, drop = P.rebuild_altb_fit(tbl, reps, e.size, inner_a4)
                if drop:
                    print(f"  [WARN] {aspec.name}/{e.name}: {drop} row(s) dropped (size limit)")
                top_patches[e.name] = new_entry
                changed += len(reps) - drop
        elif aspec.mode == "nested_evtxt":
            for e in entries:
                if not af.is_alar_v3(e.data):
                    continue
                sub_patches: Dict[str, bytes] = {}
                for se in af.parse_alar_v3(e.data):
                    if not se.name.endswith(aspec.target_entry):
                        continue
                    inner_a4 = af.is_all4(se.data)
                    inner = af.decompress_all4(se.data)[2] if inner_a4 else se.data
                    if inner[:4] != b"ALTB":
                        continue
                    tbl = af.parse_altb(inner)
                    reps = _row_replacements(tbl, aspec.columns, vmap)
                    if not reps:
                        continue
                    new_se, drop = P.rebuild_altb_fit(tbl, reps, se.size, inner_a4)
                    sub_patches[se.name] = new_se
                    changed += len(reps) - drop
                if sub_patches:
                    top_patches[e.name] = af.patch_alar_v3_inplace(e.data, sub_patches)

        if not top_patches:
            continue
        try:
            new_dec = af.patch_alar_v3_inplace(dec, top_patches)
            new_raw = af.compress_all4(new_dec, target_size=len(raw)) if outer_a4 else new_dec
            assert len(new_raw) == len(raw)
        except Exception as e:
            print(f"  [FAIL] {aspec.name}: {e}")
            failed += 1
            continue
        emit(os.path.join(".cache", aspec.sha256), new_raw)
        total_rows += changed
        print(f"  [OK] {aspec.name:32s} {changed:4d} line(s) re-translated")

    print(f"\n[DONE] {total_rows} string(s) re-translated into {PATCH_OUT_DIR}"
          + (" and the live game directory (originals in backup_retranslate/)" if write_back else " (dry output)"))
    if not write_back:
        print("       加入 --write 可直接写入游戏目录，或随后执行 python patcher.py apply")
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync translation fixes into an already-patched install")
    ap.add_argument("--game-dir", default=DEFAULT_GAME_DIR)
    ap.add_argument("--write", action="store_true", help="同时写回游戏目录（自动备份到 backup_retranslate/）")
    ap.add_argument("--old-map", default=None, help="可选：直接提供 {旧译文: 新译文} JSON，而不使用 git 比对")
    args = ap.parse_args()

    if not os.path.isdir(args.game_dir):
        print(f"[ERROR] 游戏目录不存在: {args.game_dir}")
        return 2

    vmap = collect_value_map(BASE_DIR, args.old_map)
    print(f"=== 待同步译文: {len(vmap)} 条旧译文 → 新译文 ===")
    if not vmap:
        print("没有检测到译文改动（translations/*.json 与 git HEAD 一致）。")
        return 0
    failed = retranslate(args.game_dir, vmap, args.write)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
