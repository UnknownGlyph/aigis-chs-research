"""
Fill the remaining untranslated story/UI text with the local Tencent Hy-MT2-1.8B engine.

Same engine / batching / checkpointing as `local_hymt2_translate.py` (the pipeline Gemini4 Neon
used for the 45 whitelisted tables), plus two safeguards that mattered for in-game rendering:

1. Per-line splitting.  The model happily merges two source lines into one sentence, which
   breaks the fixed-height text boxes.  Every string is split on "\\n", each segment is
   translated on its own and the result is rejoined with the original separators.
2. Term masking.  Proper nouns are replaced with 〔n〕 markers before inference and restored
   afterwards, so a character name can never be re-invented per line.  The model keeps these
   markers (occasionally normalising 〔〕 to []), so restoration accepts every bracket shape.

Usage:
    python mt_fill.py --test 200
    python mt_fill.py --batch-size 48
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

EXT_DIR = os.path.join(BASE_DIR, "extracted")
TRANS_DIR = os.path.join(BASE_DIR, "translations")
OUT_PATH = os.path.join(TRANS_DIR, "batch_13_mt_story.json")

TOKEN_RE = re.compile(r"[〔\[【（(［]\s*(\d+)\s*[〕\]】）)］]")
PLACEHOLDER_RE = re.compile(r"(%[0-9.]*[dfsx]|%c\[[0-9a-fA-F]+\]|<[A-Z0-9_]+>|\[[A-Z0-9_]+\])")
KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
KATA_NAME = re.compile(r"^[\u30a1-\u30fa\u30fc・]{2,10}$")


def load_glossary() -> Dict[str, str]:
    g: Dict[str, str] = {}
    for fn in sorted(os.listdir(TRANS_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(TRANS_DIR, fn), encoding="utf-8"))
            if isinstance(d, dict):
                g.update({k: v for k, v in d.items() if isinstance(v, str) and v})
        except Exception:
            pass
    return g


def build_terms(glossary: Dict[str, str]) -> List[Tuple[str, str]]:
    """Longest-first term list used for masking."""
    terms = {k: v for k, v in glossary.items() if KATA_NAME.match(k) and len(v) <= 12}
    # 常见种族/职业术语（不放进批次词典，靠这里强制统一）
    extra = {
        "要塞宮殿": "要塞宫殿", "塔の守護者": "塔的守护者", "英傑の幻影": "英杰的幻影",
        "編成内での同ユニット禁止": "编队内禁止同一单位", "ドロップなし": "无掉落",
        "出撃コスト": "出击费用", "カリスマ": "魅力", "スタミナ": "体力",
        "アンデッド": "不死者", "アーマー": "重甲", "ステルス": "潜行",
        "ブロック不可": "不可阻挡", "置物": "摆件", "眷属": "眷属",
        "神獣": "神兽", "魔神": "魔神", "英傑": "英杰", "亜神": "亚神",
        "獣人": "兽人", "竜族": "龙族", "妖精": "精灵", "巨人": "巨人",
        "天界人": "天界人", "冥界人": "冥界人", "深海": "深海", "魔界": "魔界",
    }
    for k, v in extra.items():
        terms.setdefault(k, v)
    return sorted(terms.items(), key=lambda kv: -len(kv[0]))


def mask(text: str, terms: List[Tuple[str, str]]) -> Tuple[str, Dict[str, str]]:
    used: Dict[str, str] = {}
    for jp, zh in terms:
        if jp in text:
            token = f"〔{len(used)}〕"
            text = text.replace(jp, token)
            used[str(len(used))] = zh
    return text, used


def unmask(text: str, used: Dict[str, str]) -> str:
    def rep(m: "re.Match") -> str:
        return used.get(m.group(1), m.group(0))
    return TOKEN_RE.sub(rep, text)


def clean(zh: str) -> str:
    for stop in ("<｜hy_", "<|hy_"):
        i = zh.find(stop)
        if i != -1:
            zh = zh[:i]
    return zh.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=48)
    ap.add_argument("--test", type=int, default=0, help="only translate N segments (smoke test)")
    ap.add_argument("--model-dir", default=r"D:\models\Hy-MT2-1.8B")
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--tables", nargs="*", default=None)
    args = ap.parse_args()

    from local_hymt2_translate import HyMT2LocalEngine

    glossary = load_glossary()
    terms = build_terms(glossary)

    tables = args.tables or ["BattleTalkEvent.atb", "MessageText.atb", "QuestNameText.atb",
                             "RewardText.atb", "UiText.atb"]

    # 1) 收集待译整串，并拆成"行"级去重队列
    strings: List[str] = []
    seen_str = set()
    for t in tables:
        p = os.path.join(EXT_DIR, f"{t}.json")
        if not os.path.exists(p):
            continue
        for e in json.load(open(p, encoding="utf-8"))["entries"]:
            jp = e["jp"]
            if jp in glossary or jp in seen_str:
                continue
            seen_str.add(jp)
            strings.append(jp)

    seg_queue: List[str] = []
    seen_seg = set()
    for s in strings:
        for seg in s.split("\n"):
            seg = seg.strip()
            if not seg or seg in seen_seg:
                continue
            seen_seg.add(seg)
            seg_queue.append(seg)
    seg_queue.sort(key=len)
    print(f"[scan] strings={len(strings)}  unique lines={len(seg_queue)}  chars={sum(map(len, seg_queue))}")

    done: Dict[str, str] = {}
    if os.path.exists(args.out):
        done = json.load(open(args.out, encoding="utf-8"))
        print(f"[resume] cached segments: {len(done)}")

    todo = [s for s in seg_queue if s not in done]
    if args.test:
        todo = todo[: args.test]
    if todo:
        engine = HyMT2LocalEngine(model_dir=args.model_dir)
        bs = args.batch_size
        t0 = time.time()
        for i in range(0, len(todo), bs):
            chunk = todo[i : i + bs]
            masked, maps = [], []
            for seg in chunk:
                m, used = mask(seg, terms)
                masked.append(m)
                maps.append(used)
            zh_list = engine.translate_batch(masked, temperature=0.0)
            for seg, zh, used in zip(chunk, zh_list, maps):
                zh = clean(zh)
                zh = unmask(zh, used)
                done[seg] = zh or seg
            if (i // bs) % 10 == 0:
                tmp = args.out + ".tmp"
                json.dump(done, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                os.replace(tmp, args.out)
                el = time.time() - t0
                rate = (i + len(chunk)) / max(0.01, el)
                print(f"  [{i+len(chunk):6d}/{len(todo):6d}] {rate:5.1f} lines/s  "
                      f"ETA={(len(todo)-i-len(chunk))/max(0.01,rate)/60:4.1f}m", flush=True)
        json.dump(done, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[done] segments={len(done)} in {(time.time()-t0)/60:.1f} min -> {args.out}")
    else:
        print("[done] nothing to translate")

    # 3) 复核：整串行数是否一致
    bad = 0
    for s in strings:
        if not all(seg.strip() in done for seg in s.split("\n") if seg.strip()):
            bad += 1
    print(f"[check] strings still missing segments: {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
