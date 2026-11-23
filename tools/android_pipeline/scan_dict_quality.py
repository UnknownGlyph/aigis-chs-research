import json, re

s1 = json.load(open(r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work\step1_payload.json", encoding="utf-8"))
b15 = json.load(open(r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work\batch_15_fix_tables.json", encoding="utf-8"))
g = dict(s1["clean_glossary"])
g.update(b15)

BAD_TRIGGERS = [
    ("ハイドース", ["糖醇"]),
    ("ヤマタノオロチ", ["山田野"]),
    ("ウェーブ", ["波浪", "波峰", "波谷", "波状"]),
    ("オーブ", ["火炬", "奥布"]),
    ("コンプリート", ["完整奖励", "完整版"]),
    ("クリア", ["莉亚", "改为", "点击", "清晰", "清楚", "C莉"]),
    ("ギブアップ", ["给予"]),
    ("プロローグ", ["专业盗贼", "プロ盗贼"]),
    ("クロコ", ["甲壳虫"]),
]

dirty = {}
for jp_kw, bad_words in BAD_TRIGGERS:
    hits = []
    for k, v in g.items():
        if jp_kw in k and any(w in v for w in bad_words):
            dirty[k] = v
            hits.append((k, v))
    print(f"  {jp_kw:14s}: {len(hits):3d} dirty matches | sample={hits[0][1][:45]!r}" if hits else f"  {jp_kw:14s}: 0")

# Also check leaked untranslated English gaming keywords in zh where JP had katakana
EN_RE = re.compile(r"\b(Rank|Wave|Clear|Complete|Drop|Cost|Skill|Ability|Orbs?)\b", re.I)
leaked = [(k, v) for k, v in g.items() if EN_RE.search(v) and not EN_RE.search(k)]
print(f"\nLeaked English gaming terms: {len(leaked)}")
for k, v in leaked[:20]:
    print(f"  {k[:35]!r} => {v[:45]!r}")
    dirty[k] = v

print(f"\nTotal quality-fix candidates: {len(dirty)}")
json.dump(dirty, open(r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work\bad_clear_fix_todo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
