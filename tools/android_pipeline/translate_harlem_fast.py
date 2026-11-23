import argparse, json, os, re, sys, time
from typing import Dict, List, Tuple
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

torch.backends.cuda.matmul.allow_tf32 = True

WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
QUEUE_PATH = os.path.join(WORK_DIR, "harlem_queue.json")
OUT_PATH = os.path.join(WORK_DIR, "batch_17_harlem.json")
MODEL_DIR = r"D:\models\Hy-MT2-1.8B"

REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
PURE_PUNCT_RE = re.compile(r"^[…・。、！？!?「」『』（）()\-\s―─♪★☆♥♡～〜0-9A-Za-z０-９Ａ-Ｚａ-ｚ]+$")

def load_fast_terms() -> Dict[str, str]:
    # Build fast name dict from cleaned step1 glossary + common Aigis names
    terms = {
        "アンナ": "安娜", "アイギス": "艾吉斯", "ケイティ": "凯蒂", "シビラ": "希比拉",
        "ソーマ": "索玛", "ヴァレリー": "瓦莱丽", "カリオペ": "卡莉奥佩", "エレイン": "伊莱恩",
        "アリサ": "亚莉莎", "レアン": "雷安", "ダニエラ": "丹妮拉", "クロエ": "克洛伊",
        "メーリス": "梅莉丝", "キャリー": "凯莉", "クレア": "克蕾雅", "フェイ": "菲",
        "ロゼット": "罗洁特", "ベルニス": "贝尔尼斯", "フィリス": "菲莉丝", "ユリアン": "尤里安",
        "ベラ": "贝拉", "モーティマ": "莫蒂玛", "コンラッド": "康拉德", "ロイ": "罗伊",
        "ヘクター": "赫克托", "バーニス": "巴妮丝", "ミランダ": "米兰达", "リアナ": "莉安娜",
        "ゴブリン": "哥布林", "オーク": "兽人", "リッチ": "巫妖", "ドラゴン": "巨龙",
        "ヴァンパイア": "吸血鬼", "エルフ": "精灵", "ドワーフ": "矮人", "デーモン": "恶魔",
        "エンジェル": "天使", "ワルキューレ": "女武神", "ネクロマンサー": "死灵法师",
    }
    try:
        s1 = json.load(open(os.path.join(WORK_DIR, "step1_payload.json"), encoding="utf-8"))
        cg = s1["clean_glossary"]
        kata = re.compile(r"^[\u30a1-\u30fa\u30fc]{3,9}$")
        for k, v in cg.items():
            if kata.match(k) and 1 <= len(v) <= 8 and not REAL_KANA_RE.search(v) and k not in terms:
                terms[k] = v
    except Exception:
        pass
    return terms

def clean_zh(jp: str, raw: str) -> str:
    for stop in ("<｜hy_", "<|hy_"):
        i = raw.find(stop)
        if i != -1: raw = raw[:i]
    zh = raw.strip()
    if jp.startswith("「") and jp.endswith("」"):
        if (zh.startswith("“") and zh.endswith("”")) or (zh.startswith('"') and zh.endswith('"')):
            zh = "「" + zh[1:-1] + "」"
    zh = re.sub(r"([\u4e00-\u9fffA-Za-z])さん(?=$|[^ぁ-んァ-ヶ])", r"\1", zh)
    zh = re.sub(r"([\u4e00-\u9fffA-Za-z])ちゃん(?=$|[^ぁ-んァ-ヶ])", r"\1", zh)
    zh = re.sub(r"([\u4e00-\u9fff])の([\u4e00-\u9fff])", r"\1的\2", zh)
    return zh

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--save-every", type=int, default=20)
    args = ap.parse_args()

    hq = json.load(open(QUEUE_PATH, encoding="utf-8"))
    speakers: List[str] = hq["speakers"]
    blocks: List[str] = hq["blocks"]

    done: Dict[str, str] = {}
    if os.path.exists(OUT_PATH):
        done = json.load(open(OUT_PATH, encoding="utf-8"))
        print(f"[Resume] Loaded {len(done)} cached translations from {OUT_PATH}", flush=True)

    # Instant skip for pure punctuation/ASCII lines AND exact glossary matches inside 「...」
    cg = {}
    try:
        s1 = json.load(open(os.path.join(WORK_DIR, "step1_payload.json"), encoding="utf-8"))
        cg = s1["clean_glossary"]
    except Exception:
        pass
    instant_added = 0
    for b in blocks:
        if b in done:
            continue
        if PURE_PUNCT_RE.match(b):
            done[b] = b
            instant_added += 1
        elif b.startswith("「") and b.endswith("」") and b[1:-1] in cg:
            zh_in = cg[b[1:-1]]
            done[b] = "「" + zh_in.strip("「」") + "」"
            instant_added += 1
    if instant_added:
        print(f"[Instant] Fast-matched {instant_added} punctuation/quoted-glossary blocks", flush=True)

    todo = [s for s in speakers + blocks if s not in done]
    # Sort strictly by length so padding inside dynamic batches is near-zero
    todo.sort(key=len)
    if args.limit > 0:
        todo = todo[:args.limit]

    print(f"[Queue] Total todo={len(todo)}, total chars={sum(map(len, todo))}", flush=True)
    if not todo:
        return

    terms = load_fast_terms()
    # Pre-compile fast Aho-style regex for top ~400 katakana names to avoid linear scanning 2000 keys!
    # Sort longest first, take top 500 most standard names
    sorted_names = sorted(terms.items(), key=lambda kv: -len(kv[0]))[:600]
    name_pat = re.compile("|".join(re.escape(k) for k, _ in sorted_names))
    name_map = dict(sorted_names)

    print(f"[Model] Loading Hy-MT2-1.8B (bfloat16, SDPA)...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = 120002
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR, torch_dtype=torch.bfloat16, device_map="cuda", trust_remote_code=True, attn_implementation="sdpa"
    )
    model.eval()

    # Build dynamic batches grouped by character-length budget
    batches: List[List[str]] = []
    idx = 0
    n = len(todo)
    while idx < n:
        L = len(todo[idx])
        if L <= 22:
            bs = 256
        elif L <= 42:
            bs = 192
        elif L <= 70:
            bs = 128
        else:
            bs = 64
        batches.append(todo[idx : idx + bs])
        idx += bs

    print(f"[Start] Built {len(batches)} length-bucketed batches (bs 64..256)", flush=True)
    t0 = time.time()
    processed = 0
    total = len(todo)

    with torch.inference_mode():
        for bi, chunk in enumerate(batches, 1):
            prompts = []
            for s in chunk:
                # Only scan katakana names if katakana exists
                hits = []
                if re.search(r"[\u30a1-\u30fa]", s):
                    seen_h = set()
                    for m in name_pat.finditer(s):
                        k = m.group(0)
                        if k not in seen_h:
                            seen_h.add(k)
                            hits.append(f"{k} 翻译成 {name_map[k]}")
                            if len(hits) >= 4: break
                ref = ("参考下面的翻译：\n" + "\n".join(hits) + "\n") if hits else ""
                um = f"{ref}将以下文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释：\n\n{s}"
                prompts.append(f"<｜hy_begin▁of▁sentence｜><｜hy_User｜>{um}<｜hy_Assistant｜>")

            enc = tokenizer(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
            in_len = enc["input_ids"].shape[1]
            max_chars = max(len(s) for s in chunk)
            max_new = min(320, max(20, int(max_chars * 1.08) + 12))

            out_ids = model.generate(
                **enc,
                max_new_tokens=max_new,
                pad_token_id=120002,
                eos_token_id=[120020, 120008],
                do_sample=False,
                repetition_penalty=1.05,
                use_cache=True,
            )
            gen_ids = out_ids[:, in_len:]
            decoded = tokenizer.batch_decode(gen_ids, skip_special_tokens=True)
            for jp, raw_z in zip(chunk, decoded):
                done[jp] = clean_zh(jp, raw_z) or jp
            processed += len(chunk)

            if bi % args.save_every == 0 or bi == len(batches):
                tmp = OUT_PATH + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(done, fp, ensure_ascii=False)
                os.replace(tmp, OUT_PATH)
                el = time.time() - t0
                rate = processed / max(0.01, el)
                eta_m = (total - processed) / max(0.01, rate) / 60
                print(
                    f"  [{processed:6d}/{total:6d}] ({processed/total*100:5.1f}%) "
                    f"{rate:5.1f} blk/s  ETA={eta_m:4.1f}m | {chunk[-1][:25]!r} => {done[chunk[-1]][:25]!r}",
                    flush=True,
                )

    print(f"[ALL DONE] Translated {processed} items in {(time.time()-t0)/60:.1f} min -> {OUT_PATH}", flush=True)

if __name__ == "__main__":
    main()
