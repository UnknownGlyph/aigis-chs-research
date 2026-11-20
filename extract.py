"""
Extract all whitelisted translatable Japanese strings from Millennium War Aigis .cache/
ALTB tables AND ALAR v3 archives (ClassData.atb + Event stories) into structured JSON files.
"""

import argparse
import json
import os
import re
from typing import Dict, List

import aigis_formats as af
from catalog import ALAR_ARCHIVES, TRANSLATABLE_TABLES

JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def extract_all(game_dir: str, out_dir: str) -> None:
    cache_dir = os.path.join(game_dir, ".cache")
    os.makedirs(out_dir, exist_ok=True)
    summary = []

    for spec in TRANSLATABLE_TABLES:
        src_path = os.path.join(cache_dir, spec.sha256)
        if not os.path.exists(src_path):
            print(f"[SKIP] Missing in .cache: {spec.name} ({spec.sha256[:12]})")
            continue

        raw = open(src_path, "rb").read()
        is_a4 = af.is_all4(raw)
        payload = af.decompress_all4(raw)[2] if is_a4 else raw
        tbl = af.parse_altb(payload)

        entries: List[Dict] = []
        for r in range(tbl.count):
            row_strs = tbl.get_row_strings(r)
            for col in spec.columns:
                val = row_strs.get(col, "")
                if val and JP_RE.search(val):
                    entries.append({"row": r, "col": col, "jp": val, "zh": ""})

        out_path = os.path.join(out_dir, f"{spec.name}.json")
        with open(out_path, "w", encoding="utf-8") as fp:
            json.dump(
                {
                    "table": spec.name,
                    "sha256": spec.sha256,
                    "category": spec.category,
                    "description": spec.description,
                    "compressed": is_a4,
                    "orig_size": len(raw),
                    "columns": spec.columns,
                    "count": len(entries),
                    "entries": entries,
                },
                fp,
                ensure_ascii=False,
                indent=2,
            )
        summary.append((spec.category, spec.name, len(entries), len(set(e["jp"] for e in entries))))

    # Extract ALAR archives (ClassData.atb + nested Event dialogue archives)
    for aspec in ALAR_ARCHIVES:
        src_path = os.path.join(cache_dir, aspec.sha256)
        if not os.path.exists(src_path):
            continue
        raw = open(src_path, "rb").read()
        dec = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
        if not af.is_alar_v3(dec):
            continue

        entries = []
        top_entries = af.parse_alar_v3(dec)
        if aspec.mode == "direct_atb":
            for e in top_entries:
                if e.name != aspec.target_entry:
                    continue
                inner = af.decompress_all4(e.data)[2] if af.is_all4(e.data) else e.data
                tbl = af.parse_altb(inner)
                for r in range(tbl.count):
                    rs = tbl.get_row_strings(r)
                    for col in aspec.columns:
                        val = rs.get(col, "")
                        if val and JP_RE.search(val):
                            entries.append({"sub": e.name, "row": r, "col": col, "jp": val, "zh": ""})
            out_name = aspec.target_entry
        else:
            for e in top_entries:
                if not af.is_alar_v3(e.data):
                    continue
                for se in af.parse_alar_v3(e.data):
                    if not se.name.endswith(aspec.target_entry):
                        continue
                    inner = af.decompress_all4(se.data)[2] if af.is_all4(se.data) else se.data
                    if inner[:4] != b"ALTB":
                        continue
                    tbl = af.parse_altb(inner)
                    for r in range(tbl.count):
                        rs = tbl.get_row_strings(r)
                        for col in aspec.columns:
                            val = rs.get(col, "")
                            if val and JP_RE.search(val):
                                entries.append({"sub": f"{e.name}/{se.name}", "row": r, "col": col, "jp": val, "zh": ""})
            out_name = aspec.name

        out_path = os.path.join(out_dir, f"{out_name}.json")
        with open(out_path, "w", encoding="utf-8") as fp:
            json.dump(
                {
                    "table": out_name,
                    "archive": aspec.name,
                    "sha256": aspec.sha256,
                    "category": aspec.category,
                    "description": aspec.description,
                    "orig_size": len(raw),
                    "columns": aspec.columns,
                    "count": len(entries),
                    "entries": entries,
                },
                fp,
                ensure_ascii=False,
                indent=2,
            )
        summary.append((aspec.category, out_name, len(entries), len(set(e["jp"] for e in entries))))

    print(f"\nExtracted {len(summary)} tables/archives to {out_dir}:")
    for cat, name, cnt, ucnt in summary:
        print(f"  [{cat:8s}] {name:35s} entries={cnt:6d}  unique={ucnt:6d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", default=r"d:\game\DMM\aigis_exe")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "extracted"))
    args = ap.parse_args()
    extract_all(args.game_dir, args.out_dir)
