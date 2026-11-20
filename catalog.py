"""
Whitelisted translatable ALTB tables & display-text columns in Millennium War Aigis (aigis_exe).
Non-display / script-expression / internal-ID columns are intentionally EXCLUDED so game logic
can never be broken by localization.
"""

import hashlib
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class TableSpec:
    name: str                  # Original Aqualead logical filename (e.g. "UiText.atb")
    sha256: str                # Filename inside .cache/
    columns: List[str]         # Whitelisted display-text columns ONLY
    category: str              # ui | mission | title | system | gameplay | story
    description: str           # Human-readable purpose


def name_sha256(name: str) -> str:
    return hashlib.sha256(name.encode("ascii")).hexdigest()


# Verified safe display-text tables mapped from Aigis.exe + .cache/
TRANSLATABLE_TABLES: List[TableSpec] = [
    # --- Core UI & Dialogs ---
    TableSpec("UiText.atb", name_sha256("UiText.atb"), ["Caption", "Help", "HelpMessage"], "ui", "菜单标题、帮助分类与帮助说明"),
    TableSpec("MessageBoxText.atb", name_sha256("MessageBoxText.atb"), ["Message"], "ui", "系统弹窗提示与报错信息"),
    TableSpec("GuideText.atb", name_sha256("GuideText.atb"), ["Message"], "ui", "主界面与各界面副官安娜引导台词"),
    TableSpec("GoQuestWarningText.atb", name_sha256("GoQuestWarningText.atb"), ["Message"], "ui", "出击编队条件不足时的警告弹窗"),
    TableSpec("PresentFilterConfig.atb", name_sha256("PresentFilterConfig.atb"), ["Text"], "ui", "礼物箱筛选标签名"),
    TableSpec("BlessingText.atb", name_sha256("BlessingText.atb"), ["_NameText", "_InfluenceText", "_TargetText"], "ui", "战斗加护/祝福名称、效果与对象"),
    TableSpec("EventTalkerConfig.atb", name_sha256("EventTalkerConfig.atb"), ["TalkerName"], "ui", "活动/系统对话发言人名称"),
    TableSpec("MessageText.atb", name_sha256("MessageText.atb"), ["Message"], "ui", "各类功能引导、说明与系统消息"),
    TableSpec("SystemText.atb", name_sha256("SystemText.atb"), ["Data_Text"], "system", "全局系统界面文本、按钮/提示/道具/状态说明"),

    # --- Mission & Mode Names ---
    TableSpec("StoryMissionConfig.atb", name_sha256("StoryMissionConfig.atb"), ["Name", "PhaseName"], "mission", "主线剧情章节名"),
    TableSpec("DailyMissionConfig.atb", name_sha256("DailyMissionConfig.atb"), ["Name"], "mission", "每日曜日任务名"),
    TableSpec("TowerMissionConfig.atb", name_sha256("TowerMissionConfig.atb"), ["Name"], "mission", "英杰/统帅/恶灵之塔名称"),
    TableSpec("TowerMissionQuestList.atb", name_sha256("TowerMissionQuestList.atb"), ["QuestName"], "mission", "塔层关卡名(第N层)"),
    TableSpec("TrainingMissionConfig.atb", name_sha256("TrainingMissionConfig.atb"), ["Name"], "mission", "练习任务名"),
    TableSpec("ChallengeMissionConfig.atb", name_sha256("ChallengeMissionConfig.atb"), ["Name"], "mission", "挑战任务名"),
    TableSpec("TutorialMissionConfig.atb", name_sha256("TutorialMissionConfig.atb"), ["Name"], "mission", "战术指南任务名"),
    TableSpec("HarlemMissionConfig.atb", name_sha256("HarlemMissionConfig.atb"), ["Name"], "mission", "交流任务名"),
    TableSpec("AssaultMissionConfig.atb", name_sha256("AssaultMissionConfig.atb"), ["Name"], "mission", "人气投票/特别突袭任务名"),
    TableSpec("RaidMissionConfig.atb", name_sha256("RaidMissionConfig.atb"), ["Name"], "mission", "神兽降临任务名"),
    TableSpec("ColosseumMissionConfig.atb", name_sha256("ColosseumMissionConfig.atb"), ["Name"], "mission", "战神斗技场任务名"),
    TableSpec("EmpireMissionConfig.atb", name_sha256("EmpireMissionConfig.atb"), ["Name"], "mission", "帝国大讨伐/帝国任务名"),
    TableSpec("GoddessRevivalMissionConfig.atb", name_sha256("GoddessRevivalMissionConfig.atb"), ["Name"], "mission", "女神复活任务名"),
    TableSpec("DevilAdventMissionConfig.atb", name_sha256("DevilAdventMissionConfig.atb"), ["Name"], "mission", "魔神降临任务名"),
    TableSpec("EmergencyMissionConfig.atb", name_sha256("EmergencyMissionConfig.atb"), ["Name", "EventItemName"], "mission", "紧急任务与活动道具名"),
    TableSpec("ReproduceMissionConfig.atb", name_sha256("ReproduceMissionConfig.atb"), ["Name"], "mission", "复刻活动任务名"),
    TableSpec("SubjugationMissionConfig.atb", name_sha256("SubjugationMissionConfig.atb"), ["Name"], "mission", "大讨伐任务名"),
    TableSpec("SubjugationMissionQuestList.atb", name_sha256("SubjugationMissionQuestList.atb"), ["LevelText", "ConsumeText", "NumberOfEnemyText"], "mission", "大讨伐难度/消耗/敌数显示"),
    TableSpec("HistoryMissionConfig.atb", name_sha256("HistoryMissionConfig.atb"), ["Name"], "mission", "追忆历史任务名"),
    TableSpec("CfgMissionHistoryTable.atb", name_sha256("CfgMissionHistoryTable.atb"), ["Title"], "mission", "历史战绩标题"),
    TableSpec("EventNameText.atb", name_sha256("EventNameText.atb"), ["Data_Text", "Data_ItemName"], "mission", "活动标题与收集品名"),
    TableSpec("EventParam.atb", name_sha256("EventParam.atb"), ["Flavor"], "mission", "活动简介文本"),
    TableSpec("QuestNameText.atb", name_sha256("QuestNameText.atb"), ["Message"], "mission", "关卡名称"),

    # --- Player Titles, Items, Skills, Abilities, Units & Story ---
    TableSpec("PlayerTitle.atb", name_sha256("PlayerTitle.atb"), ["PlayerTitle", "Explan"], "title", "王子称号名称与效果说明"),
    TableSpec("BattleGodBlessConfigTable.atb", name_sha256("BattleGodBlessConfigTable.atb"), ["Name", "Description"], "gameplay", "战神加护名称与说明"),
    TableSpec("SkillList.atb", name_sha256("SkillList.atb"), ["SkillName"], "gameplay", "单位技能名称"),
    TableSpec("SkillText.atb", name_sha256("SkillText.atb"), ["Data_Text"], "gameplay", "单位技能效果说明"),
    TableSpec("AbilityList.atb", name_sha256("AbilityList.atb"), ["AbilityName"], "gameplay", "单位被动/特性名称"),
    TableSpec("AbilityText.atb", name_sha256("AbilityText.atb"), ["AbilityText"], "gameplay", "单位被动/特性说明"),
    TableSpec("NameText.atb", name_sha256("NameText.atb"), ["Message", "RealName"], "gameplay", "单位/角色名称"),
    TableSpec("StatusText.atb", name_sha256("StatusText.atb"), ["Message"], "story", "角色简介/背景/图鉴说明文本"),
    TableSpec("QuestEventText.atb", name_sha256("QuestEventText.atb"), ["Message", "Name"], "story", "关卡前后剧情对话文本"),
]

TABLES_BY_NAME: Dict[str, TableSpec] = {t.name: t for t in TRANSLATABLE_TABLES}


@dataclass(frozen=True)
class AlarSpec:
    name: str                  # e.g. "PlayerUnitTable.aar"
    sha256: str                # Filename inside .cache/
    mode: str                  # "direct_atb" | "nested_evtxt"
    target_entry: str          # Entry name (for direct_atb) or suffix (for nested_evtxt)
    columns: List[str]         # Whitelisted display-text columns ONLY
    category: str              # gameplay | story
    description: str


ALAR_ARCHIVES: List[AlarSpec] = [
    AlarSpec(
        "PlayerUnitTable.aar",
        name_sha256("PlayerUnitTable.aar"),
        "direct_atb",
        "ClassData.atb",
        ["Name", "Explanation"],
        "gameplay",
        "全部职业名称与职业特性说明(ClassData.atb)",
    ),
    AlarSpec(
        "EventHomeArc.aar",
        name_sha256("EventHomeArc.aar"),
        "nested_evtxt",
        "evtxt.atb",
        ["_TalkerName", "_TalkText"],
        "story",
        "主页特别剧情/周年庆对话(320段)",
    ),
    AlarSpec(
        "EventArc.aar",
        name_sha256("EventArc.aar"),
        "nested_evtxt",
        "evtxt.atb",
        ["_TalkerName", "_TalkText"],
        "story",
        "主线与活动剧情对话(829段)",
    ),
    AlarSpec(
        "paev03.aar",
        name_sha256("paev03.aar"),
        "nested_evtxt",
        "evtxt.atb",
        ["_TalkerName", "_TalkText"],
        "story",
        "交流/角色个人剧情对话(454段)",
    ),
]

# Font files
ROOT_FONT_NAME = "MainFontFix.aft"
ROOT_FONT_SHA256 = name_sha256(ROOT_FONT_NAME)   # f00e83cfe03f3252... (in game root)
CACHE_FONT_NAME = "MainFont.aft"
CACHE_FONT_SHA256 = name_sha256(CACHE_FONT_NAME) # cd4215ec2d8f4371... (in .cache/)
