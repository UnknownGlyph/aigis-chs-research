import json

FIX_PATH = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n\android_sync\work\batch_15_fix_tables.json"
d = json.load(open(FIX_PATH, encoding="utf-8"))

# Exact-length overrides to guarantee 0 drops on tight uncompressed QuestNameText*.atb tables
OVERRIDES = {
    "蟻巣食う喉元": "蚁巢咽喉",
    "鋼の都への海路": "通往钢都海路",
    "空からの贈物\u3000初級": "空中赠礼　初级",
    "空からの贈物\u3000上級": "空中赠礼　上级",
    "空からの贈物\u3000神級": "空中赠礼　神级",
    "空からの贈物　神級EX": "空中赠礼　神级EX",
    "男だけの祝杯\u3000神級EX": "男人们的祝酒 神级EX",
    "耐久演習(物理)": "耐久演习(物理)",
    "耐久演習(魔法)": "耐久演习(魔法)",
    "耐久演習(貫通)": "耐久演习(贯通)",
    "木人演習(飛行)": "木人演习(飞行)",
    "木人演習(百木人組手)": "木人演习(百木人)",
    "木人演習(範囲)": "木人演习(范围)",
    "蟲の森の繭守": "虫森茧守",
    "女王の正体": "女王真面目",
}
d.update(OVERRIDES)
json.dump(d, open(FIX_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Updated batch_15_fix_tables.json with exact-fit QuestNameText overrides.")
