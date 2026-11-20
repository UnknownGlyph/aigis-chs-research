"""
Resumable, checkpointed, parallel translation workflow for Millennium War Aigis (aigis_exe).
Designed to run via Antigravity `run_workflow`.

Args:
  tables       : list of extracted JSON table names (e.g. ["SkillList.atb", "SkillText.atb"])
  batch_file   : filename under translations/ to save/resume results (e.g. "batch_01_skills.json")
  style_hint   : brief context description for the translation agents
  chunk_size   : strings per agent call (default 80)
  concurrency  : parallel agents per wave (default 12)
  model        : model tier for agents (default "flash")
"""

import json
import os
import re

BASE_DIR = r"C:\Users\19409\.gemini\antigravity\scratch\aigis_l10n"
EXT_DIR = os.path.join(BASE_DIR, "extracted")
TRANS_DIR = os.path.join(BASE_DIR, "translations")

PLACEHOLDER_RE = re.compile(r"(%[0-9.]*[dfsx]|%c\[[0-9a-fA-F]+\]|<[A-Z0-9_]+>|\[[A-Z0-9_]+\])")
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

GLOSSARY_GUIDE = """你正在为塔防RPG《千年战争Aigis》（千年戦争アイギス）制作高质量简体中文汉化补丁。
严格规则：
1. 必须翻译为自然、地道、简洁的简体中文，字数尽量精简（切勿冗长，确保游戏UI不超框）。
2. 所有占位符与控制符必须原样逐字保留、绝不可增删改或翻译：如 <TIME>、<POW_R>、<RNG_R>、<ATK>、<DEF>、<ITEM0>、<NUM0>、<UNIT>、[QUANTIFIER]、[EXT_INFO]、%d、%s、%.1f、%5d、%c[ff0000] 等。
3. 保留原有的换行符 \\n（或 \\r\\n）结构与合理断行。
4. 保持术语统一：
   - 稀有度：アイアン=铁、ブロンズ=铜、シルバー=银、ゴールド=金、プラチナ=白金、ブラック=黑、サファイア=蓝宝石
   - 数值/机制：カリスマ=魅力、スタミナ=体力、神聖結晶=神圣结晶、魔水晶=魔水晶、刻水晶=刻水晶、虹水晶=虹水晶、闇水晶=暗水晶、聖霊=圣灵、クラスチェンジ=职业晋升、覚醒=觉醒、第二覚醒=第二觉醒、スキル覚醒=技能觉醒、ブロック数=阻挡数、射程=射程、攻撃力=攻击力、防御力=防御力、魔法耐性=魔法耐性、貫通攻撃=贯通攻击、物理攻撃=物理攻击、魔法攻撃=魔法攻击、攻撃後の待ち時間=攻击后摇、遠距離攻撃=远程攻击、近接=近战、トークン=召唤物、配置中=配置中、出撃メンバーにいるだけで=编入出击队伍即可、出撃コスト=出击费用、自動発動=自动发动、効果時間無限=持续时间无限、撤退=撤退、麻痺=麻痹、隠密=隐匿、悪天候=恶劣天气、ちび=Q版、英傑=英杰
   - 职业：ソルジャー=士兵、ヘビーアーマー=重甲、ワルキューレ=女武神、ローグ=盗贼、プリンセス=公主、バンデット=山贼、サムライ=武士、忍者=忍者、ペガサスライダー=天马骑士、アーチャー=弓箭手、メイジ=法师、ヒーラー=治疗师、ウィッチ=女巫、パイレーツ=海盗、ヴァンパイアハンター=吸血鬼猎人、ドラゴンライダー=龙骑士、ドラゴンシャーマン=龙巫女、風水使い=风水师、魔法剣士=魔法剑士、神官戦士=神官战士、レンジャー=游侠、ボウライダー=弓骑兵、メイジアーマー=魔法重甲、陰陽師=阴阳师、シーフ=窃贼、モンスタースレイヤー=魔物猎人、セーラー=水兵、マーチャント=商人、砲術士=炮术师、召喚士=召唤师、踊り子=舞娘、軍師=军师、錬金術士=炼金术士
   - 角色/势力：王子=王子、アンナ=安娜、アイギス=艾吉斯、帝国=帝国、東の国=东之国、華の国=华之国、砂漠の国=沙漠之国、妖怪=妖怪、竜族=龙族、魔神=魔神、神獣=神兽
5. 若条目本身已是标准中文/人名汉字无需改动或仅需转简体，也请在结果中输出对应简体中文。
6. 严格按输入序号 i 逐条输出，不要遗漏任何一条。不要调用任何文件/命令工具，直接调用 finish 返回结果。"""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "t": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "z": {"type": "string"},
                },
                "required": ["i", "z"],
            },
        }
    },
    "required": ["t"],
}


def ph_ok(jp, zh):
    return sorted(PLACEHOLDER_RE.findall(jp)) == sorted(PLACEHOLDER_RE.findall(zh))


def load_all_existing_translations(exclude_file=None):
    existing = {}
    if not os.path.isdir(TRANS_DIR):
        return existing
    for fn in sorted(os.listdir(TRANS_DIR)):
        if not fn.endswith(".json"):
            continue
        if fn == "glossary_zh.json" or fn == "full_zh.json" or fn.startswith("batch_"):
            p = os.path.join(TRANS_DIR, fn)
            try:
                d = json.load(open(p, "r", encoding="utf-8"))
                if isinstance(d, dict):
                    for k, v in d.items():
                        if isinstance(k, str) and isinstance(v, str) and v and ph_ok(k, v):
                            existing[k] = v
            except Exception:
                pass
    return existing


def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


tables = args["tables"]
batch_file = args["batch_file"]
style_hint = args.get("style_hint", "游戏文本")
chunk_size = int(args.get("chunk_size", 80))
concurrency = int(args.get("concurrency", 12))
model_tier = args.get("model", "inherit")
max_chunks = int(args.get("max_chunks", 0))

out_path = os.path.join(TRANS_DIR, batch_file)
os.makedirs(TRANS_DIR, exist_ok=True)

# Load existing batch progress if resuming
batch_dict = {}
if os.path.exists(out_path):
    batch_dict = json.load(open(out_path, "r", encoding="utf-8"))

global_existing = load_all_existing_translations()
global_existing.update(batch_dict)

phase(f"Collect strings ({batch_file})")
todo = []
seen = set()
for tbl_name in tables:
    p = os.path.join(EXT_DIR, f"{tbl_name}.json")
    if not os.path.exists(p):
        log(f"[WARN] Missing extracted table: {p}")
        continue
    d = json.load(open(p, "r", encoding="utf-8"))
    for e in d.get("entries", []):
        jp = e["jp"]
        if not jp or jp in seen or jp in global_existing:
            continue
        if not JP_RE.search(jp):
            continue
        seen.add(jp)
        todo.append(jp)

log(f"Target tables={tables}")
log(f"Already translated in cache: {len(global_existing)} | Remaining to translate: {len(todo)}")

if not todo:
    log("All strings in target tables are already translated!")
else:
    # Split into chunks
    chunks = [todo[i : i + chunk_size] for i in range(0, len(todo), chunk_size)]
    log(f"Split into {len(chunks)} chunks (chunk_size={chunk_size}, concurrency={concurrency}, model={model_tier})")

    async def translate_one_chunk(chunk_info):
        cidx, items = chunk_info
        payload_lines = [f"{i}: {json.dumps(s, ensure_ascii=False)}" for i, s in enumerate(items)]
        prompt = (
            f"{GLOSSARY_GUIDE}\n\n"
            f"当前批次类型：{style_hint}（共 {len(items)} 条，请全部翻译并按序号返回）。\n"
            f"输入列表：\n" + "\n".join(payload_lines)
        )
        for attempt in range(2):
            try:
                res = await agent(
                    prompt,
                    schema=RESULT_SCHEMA,
                    role=f"{batch_file} #{cidx+1}/{len(chunks)}" + (f" (retry)" if attempt else ""),
                    model=model_tier,
                )
                out = {}
                bad = []
                for obj in res.get("t", []):
                    idx = obj.get("i")
                    zh = obj.get("z", "")
                    if isinstance(idx, int) and 0 <= idx < len(items) and isinstance(zh, str) and zh.strip():
                        jp = items[idx]
                        # Normalize accidental double-escaped newlines from LLM JSON output
                        if "\\n" not in jp and "\\n" in zh:
                            zh = zh.replace("\\r\\n", "\r\n").replace("\\n", "\n")
                        if ph_ok(jp, zh):
                            out[jp] = zh
                        else:
                            bad.append(jp)
                missing = [s for s in items if s not in out]
                return cidx, out, missing
            except Exception as exc:
                if attempt == 1:
                    return cidx, {}, list(items)
        return cidx, {}, list(items)

    phase(f"Translate waves ({len(chunks)} chunks)")
    all_missing = []
    indexed_chunks = list(enumerate(chunks))
    for w_start in range(0, len(indexed_chunks), concurrency):
        wave = indexed_chunks[w_start : w_start + concurrency]
        results = await parallel(wave, translate_one_chunk)
        wave_ok = 0
        wave_miss = 0
        for cidx, got, miss in results:
            batch_dict.update(got)
            wave_ok += len(got)
            wave_miss += len(miss)
            all_missing.extend(miss)
        save_json_atomic(out_path, batch_dict)
        done_chunks = min(w_start + concurrency, len(chunks))
        log(f"Wave {done_chunks}/{len(chunks)} saved: +{wave_ok} ok, {wave_miss} retry-queued (batch total={len(batch_dict)})")

    # Deduplicate missing & run one focused retry pass if needed
    retry_items = []
    rseen = set()
    for s in all_missing:
        if s not in batch_dict and s not in rseen:
            rseen.add(s)
            retry_items.append(s)

    if retry_items:
        phase(f"Retry pass ({len(retry_items)} strings)")
        r_size = max(20, chunk_size // 2)
        r_chunks = list(enumerate([retry_items[i : i + r_size] for i in range(0, len(retry_items), r_size)]))
        for w_start in range(0, len(r_chunks), concurrency):
            wave = r_chunks[w_start : w_start + concurrency]
            results = await parallel(wave, translate_one_chunk)
            got_cnt = 0
            for _, got, _ in results:
                batch_dict.update(got)
                got_cnt += len(got)
            save_json_atomic(out_path, batch_dict)
            log(f"Retry wave saved: +{got_cnt} recovered (batch total={len(batch_dict)})")

still_missing = sum(1 for s in todo if s not in batch_dict)
log(f"DONE {batch_file}: translated {len(todo) - still_missing}/{len(todo)} new strings (still missing: {still_missing}). Saved to {out_path}.")
print(json.dumps({"batch_file": batch_file, "requested": len(todo), "translated": len(todo) - still_missing, "missing": still_missing, "total_in_file": len(batch_dict)}))
