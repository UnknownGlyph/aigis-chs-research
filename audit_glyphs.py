#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_glyphs.py — 字库缺字（游戏内红叉方框）体检工具

扫描已打补丁的表 / 嵌套剧情归档 / Aigis.exe 内硬编码的 UTF-8 UI 文本，逐个核对
MainFont.aft / MainFontFix.aft 是否真的含有对应字形，并给出缺失字符、出现次数与上下文，
用于在装补丁之前发现「☒」红叉。

用法:
    python audit_glyphs.py                        # 用默认路径体检 patch_out/ 中已构建的字库
    python audit_glyphs.py --game-dir "d:\\game\\DMM\\aigis_exe"
    python audit_glyphs.py --show 60              # 列出前 60 个缺字（含上下文）
    python audit_glyphs.py --strict               # 有任何缺字即以退出码 1 结束（可接入 CI）

退出码: 0 = 全部可显示字符都有字形; 1 = 存在缺字
"""

import argparse
import os
import sys
from typing import Dict, List, Set

import aigis_formats as af
import font_builder as fb

DEFAULT_GAME_DIR = r"d:\game\DMM\aigis_exe"
PATCH_OUT_DIR = "patch_out"
CACHE_FONT_SHA256 = "cd4215ec2d8f4371a4698dd539267a07593aae7bd0ffb48d036a30c33b4b3648"
ROOT_FONT_SHA256 = "f00e83cfe03f32520fe10f877129ee6fc3eeb9b6bdd2790ec9403f1e380c59bb"


def locate_fonts(game_dir: str, patch_out: str) -> Dict[str, str]:
    """Return {font_name: path} preferring built fonts in patch_out over live game files."""
    jobs = {
        "MainFont.aft": os.path.join(".cache", CACHE_FONT_SHA256),
        "MainFontFix.aft": ROOT_FONT_SHA256,
    }
    found: Dict[str, str] = {}
    for name, rel in jobs.items():
        for base in (patch_out, game_dir):
            p = os.path.join(base, rel)
            if os.path.exists(p):
                found[name] = p
                break
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit Aigis ALFT bitmap font glyph coverage")
    ap.add_argument("--game-dir", default=DEFAULT_GAME_DIR, help="游戏目录（含 Aigis.exe 与 .cache）")
    ap.add_argument("--patch-out", default=PATCH_OUT_DIR, help="已构建补丁目录（优先使用其中的字库）")
    ap.add_argument("--show", type=int, default=40, help="每个字库最多列出多少个缺字（0 = 不列明细）")
    ap.add_argument("--strict", action="store_true", help="存在缺字时以退出码 1 结束")
    args = ap.parse_args()

    game_dir = args.game_dir
    if not os.path.isdir(game_dir):
        print(f"[ERROR] 游戏目录不存在: {game_dir}")
        return 2

    print("=== 扫描可显示文本 ===")
    examples: Dict[int, List[str]] = {}
    cps, weights = fb.collect_displayed_text(game_dir, patch_out_dir=args.patch_out or None, examples=examples)
    stats = getattr(fb.collect_displayed_text, "last_stats", {})
    print(
        f"  读取 {stats.get('files', 0)} 个缓存文件: "
        f"{stats.get('altb', 0)} 张 ALTB 文本表 / {stats.get('alar', 0)} 个 ALAR 归档 / "
        f"{stats.get('fail', 0)} 个无法解析"
    )
    print(f"  可显示字符总数: {len(cps)}")

    mandatory: Set[int] = {ord(c) for c in fb.MUST_KEEP_UI_CHARS}
    priority: Set[int] = fb.collect_display_priority_codepoints(game_dir, patch_out_dir=args.patch_out or None)
    required = cps | mandatory
    display_required = priority | mandatory
    print(f"  展示列（真正会被渲染的）字符: {len(display_required)} / 全部池内字符: {len(required)}")

    fonts = locate_fonts(game_dir, args.patch_out)
    if not fonts:
        print("[ERROR] 未找到 MainFont.aft / MainFontFix.aft")
        return 2

    total_missing = 0
    total_pool_only = 0
    for name, path in fonts.items():
        font = af.parse_alft(open(path, "rb").read())
        have = set(font.glyphs.keys())
        missing = sorted(display_required - have)
        pool_missing = sorted((required - display_required) - have)
        total_missing += len(missing)
        total_pool_only += len(pool_missing)
        src = "patch_out" if os.path.abspath(args.patch_out) in os.path.abspath(path) else "游戏目录"
        print(f"\n=== {name} ({src}) : 字形 {len(have)} ===")
        if not missing:
            print(f"  [OK] 展示字符全覆盖（{len(display_required)} 个）")
            if pool_missing:
                print(
                    f"  [INFO] {len(pool_missing)} 个仅存在于字符串池的字符没有字形"
                    f"（资源键名 / 内部 ID / 无引用字符串，不会被渲染）"
                )
            continue
        print(f"  [FAIL] 有 {len(missing)} 个展示字符缺字，游戏内会显示为红叉方框:")
        if args.show:
            ordered = sorted(missing, key=lambda cp: (-weights[cp], cp))
            for cp in ordered[: args.show]:
                ch = chr(cp)
                tag = " [服务器/界面必备]" if cp in mandatory else ""
                ctx = " | ".join(examples.get(cp, [])[:2]) or "（本地文本未出现，可能由服务器下发）"
                print(f"    {ch}  U+{cp:04X}  x{weights[cp]}{tag}  例: {ctx}")
            if len(ordered) > args.show:
                print(f"    ... 其余 {len(ordered) - args.show} 个省略")

    print("\n=== 结论 ===")
    if total_missing == 0:
        print("  两个字库均覆盖全部展示字符，界面不会出现红叉方框。")
        if total_pool_only:
            print(f"  （另有 {total_pool_only} 个池内字符未进入字库，均为不参与渲染的资源键名。）")
        return 0
    print(f"  共 {total_missing} 处展示字符缺字（多字库合计）。修复: python patcher.py build && python patcher.py apply")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
