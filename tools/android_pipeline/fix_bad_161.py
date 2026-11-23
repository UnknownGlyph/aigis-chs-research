import os, sys, json, re, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
BAD_PATH = os.path.join(WORK_DIR, "bad_clear_fix_todo.json")
FIX_PATH = os.path.join(WORK_DIR, "batch_15_fix_tables.json")
HARLEM_PATH = os.path.join(WORK_DIR, "batch_17_harlem.json")
MODEL_DIR = r"D:\models\Hy-MT2-1.8B"

REAL_KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
HANGUL = re.compile(r"[\uAC00-\uD7AF]")
PUZZLE_KANA = re.compile(r"「[ァ-ヶ,、]+」")
TOKEN_RE = re.compile(r"[〔\[【（(［]\s*(\d+)\s*[〕\]】）)］]")

FORCE_TERMS = [
    ("コンプリートボーナス", "全收集奖励"),
    ("コンプリート", "全收集"),
    ("ハイドース", "海多斯"),
    ("ヤマタノオロチ", "八岐大蛇"),
    ("クロコ", "克罗科"),
    ("ウェーブ", "波次"),
    ("オーブ", "宝珠"),
    ("ミッション", "任务"),
    ("クエスト", "关卡"),
    ("ランク", "等级"),
    ("クリア", "通关"),
    ("出撃コスト", "出击费用"),
    ("カリスマ", "魅力"),
    ("スタミナ", "体力"),
    ("ドロップ", "掉落"),
    ("ユニット", "单位"),
    ("ギブアップ", "放弃"),
    ("プロローグ", "序章"),
    ("他の形式", "其他形式"),
    ("神聖結晶", "神圣结晶"),
    ("委任チケット", "委任券"),
]
FORCE_TERMS.sort(key=lambda kv: -len(kv[0]))

def mask(text: str):
    used = {}
    for jp, zh in FORCE_TERMS:
        if jp in text:
            tok = f"〔{len(used)}〕"
            text = text.replace(jp, tok)
            used[str(len(used))] = zh
    return text, used

def unmask(text: str, used: dict) -> str:
    return TOKEN_RE.sub(lambda m: used.get(m.group(1), m.group(0)), text)

def sanitize_zh(zh: str) -> str:
    for stop in ("<｜hy_", "<|hy_"):
        i = zh.find(stop)
        if i != -1:
            zh = zh[:i]
    zh = zh.strip()
    zh = HANGUL.sub("", zh)
    zh = zh.replace("玩家等级(Rank)", "玩家等级").replace("等级(Rank)", "等级")
    zh = zh.replace("糖醇", "海多斯").replace("山田野大蛇", "八岐大蛇").replace("山田野魔神", "八岐大蛇")
    zh = zh.replace("他的形式", "其他形式").replace("波状结构", "波次").replace("波浪会切换", "波次会切换").replace("波峰与波谷切换", "波次切换")
    zh = zh.replace("完整奖励", "全收集奖励").replace("任务个席位。", "战斗。")
    zh = re.sub(r"([\u4e00-\u9fffA-Za-z])さん(?=$|[^ぁ-んァ-ヶ])", r"\1", zh)
    zh = re.sub(r"([\u4e00-\u9fffA-Za-z])ちゃん(?=$|[^ぁ-んァ-ヶ])", r"\1", zh)
    zh = re.sub(r"([\u4e00-\u9fff])の([\u4e00-\u9fff])", r"\1的\2", zh)
    return zh

def main():
    bad_dict = json.load(open(BAD_PATH, encoding="utf-8"))
    fix_d = json.load(open(FIX_PATH, encoding="utf-8"))

    # Also check batch_17_harlem for any Hangul or stray kana!
    harlem = json.load(open(HARLEM_PATH, encoding="utf-8")) if os.path.exists(HARLEM_PATH) else {}
    h_dirty_keys = [
        k for k, v in harlem.items()
        if HANGUL.search(v) or (REAL_KANA.search(PUZZLE_KANA.sub("", v)) and not re.fullmatch(r"[…・。、！？!?「」『』（）()\-\s―─♪★☆♥♡～〜0-9A-Za-z]+", k))
    ]
    print(f"Found bad_161={len(bad_dict)}, harlem dirty/kana/hangul={len(h_dirty_keys)}")

    # Split bad_dict by lines for clean line-by-line inference with FORCE_TERMS masking
    seg_set = set()
    for jp in bad_dict.keys():
        for ln in jp.split("\n"):
            st = ln.strip()
            if st and REAL_KANA.search(st):
                seg_set.add(st)
    for k in h_dirty_keys:
        for ln in k.split("\n"):
            st = ln.strip()
            if st:
                seg_set.add(st)

    segs = sorted(seg_set, key=len)
    print(f"Total unique segments to clean/retranslate: {len(segs)}")

    tok = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token_id = 120002
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16, device_map="cuda", trust_remote_code=True, attn_implementation="sdpa")
    model.eval()

    seg_out = {}
    with torch.inference_mode():
        for i in range(0, len(segs), 64):
            chunk = segs[i:i+64]
            masked, maps = [], []
            for s in chunk:
                m, u = mask(s)
                masked.append(f"<｜hy_begin▁of▁sentence｜><｜hy_User｜>将以下文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释：\n\n{m}<｜hy_Assistant｜>")
                maps.append((s, u))
            enc = tok(masked, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
            in_len = enc["input_ids"].shape[1]
            out_ids = model.generate(
                **enc, max_new_tokens=min(320, max(24, int(max(len(x) for x in chunk)*1.15)+16)),
                pad_token_id=120002, eos_token_id=[120020, 120008], do_sample=False, repetition_penalty=1.05
            )
            dec = tok.batch_decode(out_ids[:, in_len:], skip_special_tokens=True)
            for (orig_s, u), raw_z in zip(maps, dec):
                z = sanitize_zh(unmask(raw_z, u))
                seg_out[orig_s] = z or orig_s

    for jp in bad_dict.keys():
        out_lns = []
        for ln in jp.split("\n"):
            lead = ln[:len(ln)-len(ln.lstrip())]
            trail = ln[len(ln.rstrip()):]
            st = ln.strip()
            if not st:
                out_lns.append(ln)
            else:
                out_lns.append(lead + seg_out.get(st, sanitize_zh(st)) + trail)
        fix_d[jp] = sanitize_zh("\n".join(out_lns))

    for k in h_dirty_keys:
        out_lns = []
        for ln in k.split("\n"):
            st = ln.strip()
            if not st:
                out_lns.append(ln)
            else:
                out_lns.append(seg_out.get(st, sanitize_zh(st)))
        z_new = sanitize_zh("\n".join(out_lns))
        # Ensure we never leave Hangul
        z_new = HANGUL.sub("", z_new)
        if not REAL_KANA.search(PUZZLE_KANA.sub("", z_new)):
            harlem[k] = z_new

    json.dump(fix_d, open(FIX_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if harlem:
        json.dump(harlem, open(HARLEM_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"Updated batch_15 ({len(fix_d)}) and cleaned batch_17 ({len(harlem)}).")

if __name__ == "__main__":
    main()
