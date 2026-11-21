"""按"展示列"把仍未翻译的文本抽到 extracted/<表>.json（供 mt_fill.py 批量翻译）。

只收会真正绘制到屏幕上的列；Enemy._Attribute 这类逗号拼接的属性 ID 属于逻辑键，
改动会破坏敌人特性，因此显式排除。
"""
import os, sys, re, json, glob
sys.path.insert(0, r"C:/Users/19409/WorkBuddy/2026-11-20-18-06-35/aigis-chs-research")
import aigis_formats as af

D = r"C:/Users/19409/WorkBuddy/2026-11-20-18-06-35/aigis-android/full_dump"
OUT = r"C:/Users/19409/WorkBuddy/2026-11-20-18-06-35/aigis-chs-research/extracted"
TRANS = r"C:/Users/19409/WorkBuddy/2026-11-20-18-06-35/aigis-chs-research/translations"
os.makedirs(OUT, exist_ok=True)
KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
ASCII_ONLY = re.compile(r"^[\x20-\x7e]*$")

# 只收"会被绘制到屏幕上"的列；脚本/配置列一律不碰
RULES = [
    (r"BattleTalkEvent\d+\.aar$",      "BattleTalkEvent.atb", ["Message", "Name"]),
    (r"MessageText\d+\.atb$",          "MessageText.atb",     ["Message"]),
    (r"QuestNameText\d+\.atb$",        "QuestNameText.atb",   ["Message"]),
    (r"RewardText\d+\.atb$",           "RewardText.atb",      ["Text"]),
    (r"Shop2ItemV2\.atb$",             "Shop2ItemV2.atb",     ["ProductName"]),
    (r"SpecialEffectsType\.atb$",      "SpecialEffectsType.atb", ["Name", "Effect", "Target"]),
    (r"UiText\.atb$",                  "UiText.atb",          ["Caption", "Help", "HelpMessage", "Faq", "FaqDetail"]),
]
def rule_for(fn):
    for pat, tbl, cols in RULES:
        if re.match(pat, fn): return tbl, cols
    return None, None

gloss = {}
for fn in sorted(glob.glob(os.path.join(TRANS, "*.json"))):
    try:
        d = json.load(open(fn, encoding="utf-8"))
        if isinstance(d, dict): gloss.update({k: v for k, v in d.items() if isinstance(v, str) and v})
    except Exception: pass
print("existing glossary:", len(gloss))

buckets = {}
def feed(bucket, tbl_obj, cols):
    if not (tbl_obj.form & 0x04): return
    try: fields = [f.name_en for f in tbl_obj.string_fields()]
    except Exception: return
    use = [c for c in cols if c in fields]
    for r in range(tbl_obj.count):
        vals = tbl_obj.get_row_strings(r)
        for c in use:
            v = vals.get(c) or ""
            if not v or ASCII_ONLY.match(v) or not KANA.search(v): continue
            if v in gloss: continue
            buckets.setdefault(bucket, set()).add(v)

for fn in sorted(os.listdir(D)):
    if fn.endswith(".md5"): continue
    tbl_name, cols = rule_for(fn)
    if not tbl_name: continue
    raw = open(os.path.join(D, fn), "rb").read()
    d = af.decompress_all4(raw)[2] if af.is_all4(raw) else raw
    if d[:4] == b"ALTB":
        try: feed(tbl_name, af.parse_altb(d), cols)
        except Exception: pass
    elif d[:4] == b"ALAR":
        try: ents = af.parse_alar_v3(d)
        except Exception: continue
        for e in ents:
            subs = af.parse_alar_v3(e.data) if af.is_alar_v3(e.data) else [e]
            for se in subs:
                x = se.data
                if x[:4] == b"ALL4":
                    try: x = af.decompress_all4(x)[2]
                    except Exception: continue
                if x[:4] == b"ALTB":
                    try: feed(tbl_name, af.parse_altb(x), cols)
                    except Exception: pass

total_short = total_long = 0
for name, items in sorted(buckets.items()):
    items = sorted(items)
    short = [t for t in items if "\n" not in t and len(t) <= 14]
    long_ = [t for t in items if t not in set(short)]
    total_short += len(short); total_long += len(long_)
    path = os.path.join(OUT, f"{name}.json")
    json.dump({"table": name, "entries": [{"jp": t} for t in short + long_]},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  {name:24s} unique={len(items):5d}  short={len(short):4d}  long={len(long_):4d}  chars={sum(map(len,items))}")
print(f"\n合计 unique short={total_short} long={total_long}")
