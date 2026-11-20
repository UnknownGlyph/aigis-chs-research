"""
Smart post-maintenance / game-update handler for Millennium War Aigis (aigis_exe).

When the official DMM game updates on Thursdays:
  1. Checks each file in patch_manifest.json against the live game directory:
     - If the live file still has `patched_sha256` (not updated by server), restores the clean
       original from `backup/` before re-extracting.
     - If the live file has a NEW hash (updated by server!), replaces `backup/` with the newly
       downloaded official file so the old backup never overwrites a new game update.
  2. Runs `extract.py` to extract all latest tables.
  3. If `--translate-new` is passed (or local Hy-MT2-1.8B is available), translates any newly
     added untranslated strings into `translations/batch_99_incremental.json`.
  4. Runs `patcher.py build` and `patcher.py apply` to re-apply the localization patch matching
     the updated file sizes.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

import extract
import patcher

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
MANIFEST_PATH = os.path.join(BASE_DIR, "patch_out", "patch_manifest.json")
DEFAULT_MODEL_DIR = r"D:\models\Hy-MT2-1.8B"
MV_ENV_PYTHON = r"D:\software\mv-env\Scripts\python.exe"


def sync_backups_with_game_updates(game_dir: str) -> None:
    if not os.path.exists(MANIFEST_PATH):
        print("[Update] No previous patch_manifest.json found; skipping backup sync.")
        return

    manifest = json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    restored_unmodified = 0
    updated_from_server = 0

    for item in manifest.get("files", []):
        rel = item["rel_path"].replace("/", os.sep)
        p_live = os.path.join(game_dir, rel)
        p_bak = os.path.join(BACKUP_DIR, rel)
        if not os.path.exists(p_live):
            continue

        live_hash = patcher.sha256_bytes(open(p_live, "rb").read())
        if live_hash == item["patched_sha256"]:
            # Not updated by game server; restore clean original from backup before re-building
            if os.path.exists(p_bak):
                shutil.copy2(p_bak, p_live)
                restored_unmodified += 1
        elif live_hash == item["orig_sha256"]:
            # Already clean original
            if not os.path.exists(p_bak):
                os.makedirs(os.path.dirname(p_bak), exist_ok=True)
                shutil.copy2(p_live, p_bak)
        else:
            # Game server downloaded a NEW version of this file! Update our backup to the new official file!
            print(f"  [Server Update Detected] {item['name']} ({rel}) -> updating clean backup")
            os.makedirs(os.path.dirname(p_bak), exist_ok=True)
            shutil.copy2(p_live, p_bak)
            updated_from_server += 1

    print(
        f"[Update] Sync complete: {updated_from_server} file(s) updated by game server, "
        f"{restored_unmodified} unchanged patched file(s) restored to clean original."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Update Aigis Chinese patch after official game maintenance")
    ap.add_argument("--game-dir", default=r"d:\game\DMM\aigis_exe")
    ap.add_argument("--translate-new", action="store_true", help="Auto-translate newly added strings via local Hy-MT2-1.8B")
    args = ap.parse_args()

    print("=== Step 1: Syncing backups & detecting official server updates ===")
    sync_backups_with_game_updates(args.game_dir)

    print("\n=== Step 2: Re-extracting latest text tables from game directory ===")
    ext_dir = os.path.join(BASE_DIR, "extracted")
    extract.extract_all(args.game_dir, ext_dir)

    if args.translate_new:
        print("\n=== Step 3: Translating newly added strings with local Hy-MT2-1.8B ===")
        py_exe = MV_ENV_PYTHON if os.path.exists(MV_ENV_PYTHON) else sys.executable
        all_tables = [f[:-5] for f in sorted(os.listdir(ext_dir)) if f.endswith(".json")]
        cmd = [
            py_exe,
            os.path.join(BASE_DIR, "local_hymt2_translate.py"),
            "--tables",
            *all_tables,
            "--batch-file",
            "batch_99_incremental.json",
            "--batch-size",
            "48",
        ]
        subprocess.check_call(cmd)

    print("\n=== Step 4: Rebuilding & verifying patch for updated game files ===")
    patcher.cmd_build(args.game_dir)

    print("\n=== Step 5: Applying updated patch ===")
    patcher.cmd_apply(args.game_dir)
    patcher.cmd_status(args.game_dir)


if __name__ == "__main__":
    main()
