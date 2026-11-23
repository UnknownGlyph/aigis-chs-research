import os, sys, re, json, time
from typing import Dict, List, Tuple

sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
from local_hymt2_translate import HyMT2LocalEngine

WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
STEP1_PATH = os.path.join(WORK_DIR, "step1_payload.json")
OUT_FIX_TRANS = os.path.join(WORK_DIR, "batch_15_fix_tables.json")
OUT_ALOD_TRANS = os.path.join(WORK_DIR, "batch_16_alod_ui.json")

TOKEN_RE = re.compile(r"[〔\[【（(［]\s*(\d+)\s*[〕\]】）)］]")
REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
KATA_NAME = re.compile(r"^[\u30a1-\u30fa\u30fc・]{2,12}$")
PUZZLE_KANA_RE = re.compile(r"「[ァ-ヶ,、]+」")

data = json.load(open(STEP1_PATH, encoding="utf-8"))
clean_glossary: Dict[str, str] = data["clean_glossary"]
todo_kana: List[str] = data["todo_kana"]
todo_nokana: List[str] = data["todo_nokana"]
aod_clean: Dict[str, dict] = data["aod_clean"]

# Filter out strings in todo_nokana that are already valid Chinese templates (like "出现敌数：100", "第100阶层", "★3")
filtered_nokana = []
for s in todo_nokana:
    if re.fullmatch(r"出现敌数：\d+|第\d+阶层|魅力\d+|第\d+届人气投票任务|第\d+年之战", s):
        continue
    filtered_nokana.append(s)

# Build high-quality masking glossary
terms_dict = {k: v for k, v in clean_glossary.items() if KATA_NAME.match(k) and len(v) <= 14 and not REAL_KANA_RE.search(v)}
FORCE_TERMS = {
    "プロローグ": "序章",
    "これまでのお話": "前情提要",
    "★3クリア": "★3通关",
    "初★3クリア": "首次★3通关",
    "初クリア": "首次通关",
    "クリア": "通关",
    "ミッション": "任务",
    "カリスマ": "魅力",
    "スタミナ": "体力",
    "出撃コスト": "出击费用",
    "コスト": "费用",
    "ドロップ": "掉落",
    "ゴールド": "金币",
    "ユニット": "单位",
    "トークン": "分身",
    "ブロック": "阻挡",
    "スキル": "技能",
    "アビリティ": "被动",
    "アンデッド": "不死者",
    "アーマー": "重甲",
    "ステルス": "潜行",
    "ブロック不可": "不可阻挡",
    "メンテ": "维护",
    "メンテナンス": "维护",
    "プレゼントボックス": "礼物箱",
    "プレゼント": "礼物",
    "神聖結晶": "神圣结晶",
    "英傑": "英杰",
    "魔神": "魔神",
    "神獣": "神兽",
    "大総力戦": "大总力战",
    "戦神コロッセウム": "战神斗技场",
    "統帥の塔": "统帅之塔",
    "英傑の塔": "英杰之塔",
    "悪霊の塔": "恶灵之塔",
    "王子": "王子",
    "アンナ": "安娜",
    "フンババ": "芬巴巴",
    "チャムチャム": "恰姆恰姆",
    "チェルシー": "切尔西",
    "虚空の花": "虚空之花",
    "雪枝の里": "雪枝之里",
    "オオワタツミ": "大绵津见",
    "アトランティス": "亚特兰蒂斯",
    "ゴブリン博士": "哥布林博士",
    "オルカ科学ラボ": "奥尔卡科学实验室",
    "ポイント": "点数",
    "オーブ": "宝珠",
    "チケット": "券",
    "パスワード": "密码",
    "データ連動": "数据联动",
    "機種変更": "更换设备",
}
terms_dict.update(FORCE_TERMS)
terms_list = sorted(terms_dict.items(), key=lambda kv: -len(kv[0]))

def mask(text: str) -> Tuple[str, Dict[str, str]]:
    used: Dict[str, str] = {}
    # Protect puzzle kana like 「ヨ,ロ,シ,ク」 verbatim
    for m in PUZZLE_KANA_RE.finditer(text):
        puz = m.group(0)
        if puz not in text: continue
        tok = f"〔{len(used)}〕"
        text = text.replace(puz, tok, 1)
        used[str(len(used))] = puz
    for jp, zh in terms_list:
        if jp in text:
            tok = f"〔{len(used)}〕"
            text = text.replace(jp, tok)
            used[str(len(used))] = zh
    return text, used

def unmask(text: str, used: Dict[str, str]) -> str:
    return TOKEN_RE.sub(lambda m: used.get(m.group(1), m.group(0)), text)

def clean_zh(zh: str) -> str:
    for stop in ("<｜hy_", "<|hy_"):
        i = zh.find(stop)
        if i != -1: zh = zh[:i]
    zh = zh.strip()
    # Fix stray polite Japanese suffixes if model missed translating them
    zh = re.sub(r"([\u4e00-\u9fffA-Za-z])さん(?=$|[^ぁ-んァ-ヶ])", r"\1", zh)
    zh = re.sub(r"([\u4e00-\u9fffA-Za-z])ちゃん(?=$|[^ぁ-んァ-ヶ])", r"\1", zh)
    zh = re.sub(r"([\u4e00-\u9fff])の([\u4e00-\u9fff])", r"\1的\2", zh)
    zh = re.sub(r"([\u4e00-\u9fff])から(?=\n|$)", r"\1处", zh)
    return zh

all_table_todo = sorted(set(todo_kana + filtered_nokana), key=len)
all_aod_todo = sorted(aod_clean.keys(), key=len)

print(f"To translate -> table items: {len(all_table_todo)}, ALOD UI items: {len(all_aod_todo)}")

# Split all items by newline for faithful line-by-line translation
seg_set = set()
for s in all_table_todo + all_aod_todo:
    for ln in s.split("\n"):
        st = ln.strip()
        if st:
            seg_set.add(st)

seg_list = sorted(seg_set, key=len)
print(f"Unique segments to translate: {len(seg_list)}")

engine = HyMT2LocalEngine(model_dir=r"D:\models\Hy-MT2-1.8B")
t0 = time.time()
bs = 64
seg_trans: Dict[str, str] = {}
for i in range(0, len(seg_list), bs):
    chunk = seg_list[i:i+bs]
    masked, maps = [], []
    for seg in chunk:
        # Preserve already clean segments that are in clean_glossary
        if seg in clean_glossary:
            seg_trans[seg] = clean_glossary[seg]
            continue
        m, u = mask(seg)
        masked.append(m)
        maps.append((seg, u))
    if not masked:
        continue
    outs = engine.translate_batch(masked, temperature=0.0)
    for (orig_seg, u), out in zip(maps, outs):
        zh = unmask(clean_zh(out), u)
        seg_trans[orig_seg] = zh or orig_seg

el = time.time() - t0
print(f"Translated {len(seg_list)} segments in {el:.1f}s ({len(seg_list)/max(0.01,el):.1f} seg/s)")

# Second pass: retry any segment that still contains stray kana (excluding puzzle kana)
retry = [s for s, z in seg_trans.items() if REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", z))]
print(f"Segments still containing kana after pass 1: {len(retry)}")
if retry:
    for i in range(0, len(retry), bs):
        chunk = retry[i:i+bs]
        # Translate WITHOUT masking so model sees full context if masking confused it
        outs = engine.translate_batch(chunk, temperature=0.3)
        for seg, out in zip(chunk, outs):
            z = clean_zh(out)
            if not REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", z)) and z != seg:
                seg_trans[seg] = z

# Reconstruct full table strings
fix_tables_dict: Dict[str, str] = {}
for s in all_table_todo:
    lines = s.split("\n")
    out_lines = []
    for ln in lines:
        lead = ln[:len(ln)-len(ln.lstrip())]
        trail = ln[len(ln.rstrip()):]
        st = ln.strip()
        if not st:
            out_lines.append(ln)
        else:
            out_lines.append(lead + seg_trans.get(st, st) + trail)
    zh_full = "\n".join(out_lines)
    # Apply final safe fixes for common JP words
    zh_full = zh_full.replace("ク莉亚", "通关").replace("专业盗贼", "序章").replace("プロ盗贼", "序章")
    fix_tables_dict[s] = zh_full

# Reconstruct ALOD strings and verify byte length <= orig_bytes!
alod_dict: Dict[str, str] = {}
aod_too_long = []
for s in all_aod_todo:
    orig_b = aod_clean[s]["bytes"]
    lines = s.split("\n")
    out_lines = []
    for ln in lines:
        lead = ln[:len(ln)-len(ln.lstrip())]
        trail = ln[len(ln.rstrip()):]
        st = ln.strip()
        if not st:
            out_lines.append(ln)
        else:
            out_lines.append(lead + seg_trans.get(st, st) + trail)
    zh_full = "\n".join(out_lines)
    zh_full = zh_full.replace(" ", " ")
    # Shrink common bloated phrasing if > orig_b
    if len(zh_full.encode("utf-8")) > orig_b:
        # Try shrinking spaces, fullwidth->halfwidth, removing polite filler
        zh_try = zh_full.replace("：", ":").replace("！", "!").replace("？", "?").replace("（", "(").replace("）", ")")
        zh_try = zh_try.replace("的", "").replace("了", "").replace("请", "")
        if len(zh_try.encode("utf-8")) <= orig_b:
            zh_full = zh_try
    if len(zh_full.encode("utf-8")) <= orig_b:
        alod_dict[s] = zh_full
    else:
        aod_too_long.append((orig_b, len(zh_full.encode("utf-8")), s, zh_full))

json.dump(fix_tables_dict, open(OUT_FIX_TRANS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(alod_dict, open(OUT_ALOD_TRANS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

still_kana_tbl = [k for k, v in fix_tables_dict.items() if REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", v))]
print(f"\nDone tables fix: {len(fix_tables_dict)} saved to {OUT_FIX_TRANS} (still_has_kana={len(still_kana_tbl)})")
for k in still_kana_tbl[:20]:
    print(f"  STILL_KANA: {k[:40]!r} -> {fix_tables_dict[k][:50]!r}")
print(f"Done ALOD UI: {len(alod_dict)}/{len(all_aod_todo)} fit within original bytes -> {OUT_ALOD_TRANS}")
print(f"ALOD strings slightly over byte budget ({len(aod_too_long)}):")
for ob, zb, jp, zh in aod_too_long[:30]:
    print(f"  [{ob}B -> {zb}B] {jp!r} -> {zh!r}")
