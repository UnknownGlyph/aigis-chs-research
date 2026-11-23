import os, sys, re, json, time
import torch

sys.path.insert(0, r"C:\Users\19409\WorkBuddy\2026-11-20-18-06-35\aigis-chs-research")
from local_hymt2_translate import HyMT2LocalEngine

WORK_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work"
DATA_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\device_data"
STEP1_PATH = os.path.join(WORK_DIR, "step1_payload.json")
FIX_PATH = os.path.join(WORK_DIR, "batch_15_fix_tables.json")
ALOD_PATH = os.path.join(WORK_DIR, "batch_16_alod_ui.json")

s1 = json.load(open(STEP1_PATH, encoding="utf-8"))
fix_d = json.load(open(FIX_PATH, encoding="utf-8"))
alod_d = json.load(open(ALOD_PATH, encoding="utf-8"))
aod_clean = s1["aod_clean"]

REAL_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30f6\u30fd-\u30ff]")
PUZZLE_KANA_RE = re.compile(r"「[ァ-ヶ,、]+」")

# 1. Inspect all remaining still_kana keys & fix manually / via full glossary + regex + GPU
still_kana = [(k, v) for k, v in fix_d.items() if REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", v))]
print(f"Checking {len(still_kana)} still_kana entries in batch_15...")

MANUAL_FIX_TABLE = {
    "ひゅー♪": "咻~♪",
    "ひゅー♪\u3000": "咻~♪",
    "ドウマン": "道满",
    "見守り隊A": "守护队A",
    "見守り隊B": "守护队B",
    "不要、ダ。": "不要，不行。",
    "普基ュ！？": "噗啾！？",
    "ぷきゅ！？": "噗啾！？",
    "ヨ伊予イ♪": "哟呼伊~♪",
    "何、僕らには": "哎，对我们而言",
    "────っ。": "────唔。",
    "アメノタヂカラ？": "天手力男？",
    "推奨端末について": "关于推荐设备",
    "とくべつよさん！": "特别预算！",
    "▼神級EXについて": "▼关于神级EX",
    "ひーん！！(号泣)": "呜——！！(号啕大哭)",
    "真不错啊，桃ちー！": "真不错啊，小桃！",
    "嘻ーン！！（哭泣）": "呜——！！(哭泣)",
    "なにが峰打ちだよ！？": "什么刀背击打啊！？",
    "敵の種族と属性について": "关于敌人的种族与属性",
    "マサカ、異世界のトモを": "难道说，要把异界的朋友",
    "せんぱ――こほん、王子！": "前辈——咳哼，王子！",
    "本当にありがとう、ぺこり。": "真是非常感谢，鞠躬。",
    "そして英雄王的继承人，王子。": "以及英雄王的继承人，王子。",
    "「三明剣の長持」ですぽん！！": "是“三明剑的长持”哦！",
    "落ち武者\u3000＜属性：アンデッド＞": "落难武士\u3000＜属性：不死者＞",
    "真不愧是桃ちー！ 强大又厉害啊！": "真不愧是小桃！又强又厉害！",
    "していると暴走したおもちゃが現れて！？": "就在这时，失控的玩具出现了！？",
    "呐，喂！\n听说フツヌシ大人来过这里！？": "呐，喂！\n听说经津主大人来过这里！？",
    "是オオワ辰巳大人的化身！！\n不是鲑鱼！": "是大绵津见大人的化身！！\n不是鲑鱼！",
    "落ち武者大将(弓)\u3000＜属性：アンデッド＞": "落难武士大将(弓)\u3000＜属性：不死者＞",
    "せんぱ——好了，王子！\n让您久等了——！": "前辈——咳哼，王子！\n让您久等了——！",
    "不要、ダ。\n在龙的世界里，无需怜悯……。": "不要，不行。\n在龙的世界里，无需怜悯……。",
    "天界の民は、ツクヨミ殿の結界に守られている。": "天界之民受到月读大人的结界保护。",
    "『王国ナナイロ文化祭』獲得★数19以上で開放": "《王国七彩文化祭》获得★数19以上即可开放",
    "什么峰打ち啊！？\n我的身体被分成了两半了！？": "什么刀背击打啊！？\n我的身体要被劈成两半了！？",
    "不要、ダ。\n竜の世に、情けナド必要ナイ……。": "不要，不行。\n在龙的世界里，无需怜悯……。",
    "せんぱ――こほん、王子！\nお待たせしましたー！": "前辈——咳哼，王子！\n让您久等了——！",
    "そしてリヴァイアサンの能力を無効化した者……）": "以及将利维坦的能力无效化之人……）",
    "フツヌシ様がここに来てたって聞いたんだけど！？": "听说经津主大人来过这里！？",
    "“王国ナナイロ文化节”获得★数19以上即可开放": "“王国七彩文化节”获得★数19以上即可开放",
    "ねっ、ねぇ！\nフツヌシ様がここに来てたって聞いたんだけど！？": "呐，喂！\n听说经津主大人来过这里！？",
}
fix_d.update(MANUAL_FIX_TABLE)

# Regex cleanup pass across ALL batch_15 values
def sanitize_val(k: str, v: str) -> str:
    v = v.replace("任务莉亚", "任务通关").replace("ク莉亚", "通关")
    v = v.replace("について", "") if k.endswith("について") and not v.startswith("关于") else v
    # Targeted replacements for leftover Japanese katakana terms in mixed outputs
    rep_pairs = [
        ("フツヌシ", "经津主"), ("ツクヨミ", "月读"), ("ナナイロ", "七彩"),
        ("オオワ辰巳", "大绵津见"), ("オオワタツミ", "大绵津见"),
        ("リヴァイアサン", "利维坦"), ("桃ちー", "小桃"), ("峰打ち", "刀背击打"),
        ("ですぽん", "的说"), ("落ち武者", "落难武士"), ("見守り隊", "守护队"),
        ("せんぱ——", "前辈——"), ("せんぱ――", "前辈——"), ("せんぱ", "前辈"),
        ("ぺこり", "鞠躬"), ("ペコリ", "鞠躬"), ("どう曼", "道满"),
        ("マサカ、", "难道，"), ("のトモ", "的朋友"), ("トモ", "朋友"),
        ("するのと", "于是"), ("すると，", "于是，"), ("すると、", "于是，"),
        ("そして，", "而且，"), ("そして、", "而且，"), ("そして", "而且"),
        ("には", "而言"), ("、ダ。", "，不行。"), ("の無", "的无"),
        ("の无", "的无"), ("▼神级EXについて", "▼关于神级EX"),
        ("から\n", "发起\n"), ("プロローグ", "序章"),
    ]
    for a, b in rep_pairs:
        v = v.replace(a, b)
    # Fix `任务通关で` or trailing `で`
    v = re.sub(r"([\u4e00-\u9fff])の([\u4e00-\u9fff])", r"\1的\2", v)
    v = re.sub(r"について$", "", v)
    return v

for k in list(fix_d.keys()):
    fix_d[k] = sanitize_val(k, fix_d[k])

# Check remaining still_kana after sanitize
rem_kana = [(k, v) for k, v in fix_d.items() if REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", v))]
print(f"Remaining batch_15 still_kana after regex fixes: {len(rem_kana)}")
for k, v in rem_kana:
    print(f"  REM: {k[:45]!r} -> {v[:55]!r}")

# 2. Manual curated fixes for the 23 over-budget + 1 bad-placeholder ALOD UI strings!
ALOD_MANUAL = {
    "[MM]/[DD]\n開催": "[MM]/[DD]\n开放",
    "称号": "称号",
    "ランク": "等级",
    "古い順": "按旧序",
    "残時間": "剩时",
    "必要Ｇ": "所需G",
    "あと0分": "剩0分",
    "次の報酬": "下次报酬",
    "王子ランク": "王子等级",
    "@@次の報酬": "@@下次报酬",
    "あと   個": "剩   个",
    "[DAY]日目": "第[DAY]天",
    "大総力戦編成へ": "大总力战编队",
    "ランクアップまで": "距升级还需",
    "終了まで23時間": "距结束剩23小时",
    "投票で次の挑戦権!": "投票获下次挑战权!",
    "必要ランク：999": "所需等级：999",
    "あと(999pt)": "剩(999pt)",
    "王子ランク 000 → 000": "王子等级 000 → 000",
    "[Month]月[Day]日 [Hour]まで": "至[Month]月[Day]日 [Hour]",
    "獲得★が１以上で交換所に\n「○○○」\n「△△△」追加\n": "获★1以上时交换所追加\n「○○○」\n「△△△」\n",
    "ミッション/クエストでの\n入手ランクEXPが1.2倍！\n": "任务/关卡获得的\n等级EXP变为1.2倍!\n",
    "獲得★が１以上で交換所に\n          「○○○」\n          「△△△」追加\n": "获★1以上时交换所追加\n          「○○○」\n          「△△△」\n",
    "ID:[ID]\n\nランク:[RANK]\n\n神聖結晶所持数\n\u3000購入分：[NUM_PAY]\n\u3000無料分：[NUM_FREE]": "ID:[ID]\n\n等级:[RANK]\n\n神圣结晶持有数\n\u3000付费：[NUM_PAY]\n\u3000免费：[NUM_FREE]",
}

for jp, zh in ALOD_MANUAL.items():
    if jp in aod_clean:
        ob = aod_clean[jp]["bytes"]
        zb = len(zh.encode("utf-8"))
        assert zb <= ob, f"Manual ALOD {jp!r} -> {zh!r} too long: {zb} > {ob}"
        alod_d[jp] = zh

# Double check ALL 550 ALOD items for placeholders & byte bounds
PH_RE = re.compile(r"\[[A-Za-z0-9_]+\]")
for k, v in list(alod_d.items()):
    ob = aod_clean[k]["bytes"]
    if len(v.encode("utf-8")) > ob:
        raise ValueError(f"ALOD overflow {k!r}")
    if sorted(PH_RE.findall(k)) != sorted(PH_RE.findall(v)):
        print(f"  WARN ALOD placeholder diff: {k!r} -> {v!r}")

print(f"ALOD total clean covered: {len(alod_d)} / {len(aod_clean)}")

# 3. Load Hy-MT2-1.8B to clean remaining `rem_kana` (if any) AND benchmark Harlem0+1 throughput!
# 4. Benchmark Harlem0+1 paragraph translation throughput with batch_size=128 & length sorting!
engine = HyMT2LocalEngine(model_dir=r"D:\models\Hy-MT2-1.8B")

if rem_kana:
    rem_segs = []
    for k, v in rem_kana:
        for ln in k.split("\n"):
            st = ln.strip()
            if st and REAL_KANA_RE.search(PUZZLE_KANA_RE.sub("", st)):
                rem_segs.append(st)
    rem_segs = sorted(set(rem_segs))
    outs = engine.translate_batch(rem_segs, temperature=0.0) if len(rem_segs) <= 64 else [o for i in range(0, len(rem_segs), 64) for o in engine.translate_batch(rem_segs[i:i+64], temperature=0.0)]
    rmap = {s: sanitize_val(s, o) for s, o in zip(rem_segs, outs)}
    for k, v in rem_kana:
        new_lines = [rmap.get(ln.strip(), ln) if ln.strip() in rmap else ln for ln in k.split("\n")]
        fix_d[k] = sanitize_val(k, "\n".join(new_lines))

json.dump(fix_d, open(FIX_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(alod_d, open(ALOD_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

hq = json.load(open(os.path.join(WORK_DIR, "harlem_queue.json"), encoding="utf-8"))
all_blks = [b for b in hq["blocks"] if 10 <= len(b) <= 180]
step = max(1, len(all_blks) // 1024)
sample_blocks = sorted(all_blks[::step][:1024], key=len)
t0 = time.time()
tot_ok = 0
for i in range(0, len(sample_blocks), 128):
    outs = engine.translate_batch(sample_blocks[i:i+128], temperature=0.0)
    tot_ok += len(outs)
el = time.time() - t0
print(f"\n[BENCHMARK Harlem blocks] batch_size=128: {tot_ok} blocks in {el:.2f}s => {tot_ok/el:.1f} blocks/s")
print(f"Estimated time for {len(hq['blocks'])} unique Harlem blocks: {len(hq['blocks']) / (tot_ok/el) / 60:.1f} minutes!")
print("Sample Harlem translations:")
for src, dst in list(zip(sample_blocks[:3] + sample_blocks[-3:], engine.translate_batch(sample_blocks[:3] + sample_blocks[-3:], temperature=0.0))):
    print(f"  JP: {src.replace(chr(10),' ')[:60]!r}")
    print(f"  ZH: {dst.replace(chr(10),' ')[:60]!r}")
