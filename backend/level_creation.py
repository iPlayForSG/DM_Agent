"""单职业等级建卡的确定性配置；与运行中升级及特性执行分开。"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from models import Character, InventoryItem, ResourcePool, SpellSlot, Stats
from starter_shop import get_shop_catalog

ABILITIES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
LEVEL_XP = [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000]
FEATURE_LABELS = {
    "Ability Score Improvement": "属性值提升", "Epic Boon": "史诗恩惠", "Expertise": "专精",
    "Jack of All Trades": "万事通", "Bardic Inspiration": "吟游激励", "Spellcasting": "施法",
    "Font of Inspiration": "激励之源", "Countercharm": "反迷惑", "Magical Secrets": "魔法奥秘",
    "Superior Inspiration": "卓越激励", "Words of Creation": "造物真言", "Extra Attack": "额外攻击",
    "Second Wind": "回气", "Action Surge": "动作如潮", "Indomitable": "不屈",
    "Weapon Mastery": "武器精通", "Fighting Style": "战斗风格", "Channel Divinity": "引导神力",
    "Wild Shape": "荒野形态", "Pact Magic": "契约魔法", "Eldritch Invocations": "魔能祈唤",
    "Mystic Arcanum": "玄奥秘法", "Sneak Attack": "偷袭", "Martial Arts": "武艺",
    "Unarmored Defense": "无甲防御", "Unarmored Movement": "无甲移动", "Metamagic": "超魔法",
    "Font of Magic": "魔力泉涌", "Scholar": "学者", "Arcane Recovery": "奥术回想",
}
SUBCLASS_LABELS = {
    "College of Dance": "舞蹈学院", "College of Glamour": "魅惑学院", "College of Lore": "逸闻学院", "College of Valor": "勇气学院",
    "Life Domain": "生命领域", "Light Domain": "光明领域", "Trickery Domain": "诡术领域", "War Domain": "战争领域",
    "Circle of the Land": "大地结社", "Circle of the Moon": "月亮结社", "Circle of the Sea": "海洋结社", "Circle of the Stars": "星辰结社",
    "Battle Master": "战斗大师", "Champion": "勇士", "Eldritch Knight": "奥法骑士", "Psi Warrior": "灵能武士",
    "Warrior of Mercy": "慈悲武者", "Warrior of Shadow": "暗影武者", "Warrior of the Elements": "元素武者", "Warrior of the Open Hand": "散打武者",
    "Oath of Devotion": "奉献之誓", "Oath of Glory": "荣耀之誓", "Oath of the Ancients": "古贤之誓", "Oath of Vengeance": "复仇之誓",
    "Beast Master": "驯兽师", "Fey Wanderer": "妖精漫游者", "Gloom Stalker": "幽域追猎者", "Hunter": "猎人",
    "Arcane Trickster": "奥法诡术师", "Assassin": "刺客", "Soulknife": "魂刃", "Thief": "盗贼",
    "Aberrant Sorcery": "畸变术法", "Clockwork Sorcery": "时钟术法", "Draconic Sorcery": "龙族术法", "Wild Magic Sorcery": "狂野魔法",
    "Archfey Patron": "至高妖精宗主", "Celestial Patron": "天界宗主", "Fiend Patron": "邪魔宗主", "Great Old One Patron": "旧日支配者宗主",
    "Abjurer": "防护师", "Diviner": "预言师", "Evoker": "塑能师", "Illusionist": "幻术师",
}


@lru_cache(maxsize=1)
def progression():
    return json.loads((Path(__file__).parent / "data/level_progression_2024.json").read_text(encoding="utf-8"))["classes"]


def class_progression(name, level, subclass_id=""):
    if type(level) is not int or not 1 <= level <= 20:
        raise ValueError("角色等级必须为1到20的整数")
    if name not in progression():
        raise ValueError(f"未收录职业等级成长：{name}")
    data = progression()[name]
    subclass = next((s for s in data["subclasses"] if s["id"] == subclass_id), None)
    if subclass_id and (subclass is None or level < 3):
        raise ValueError("当前职业或等级不能选择该子职业")
    return data, subclass


def _fixed_spells(entry, level, library, variant=""):
    spells, cantrips = [], []
    for block in entry.get("additional_spells", []):
        if block.get("name") and block["name"] != variant:
            continue
        for mode in ("prepared", "known"):
            for unlock, values in block.get(mode, {}).items():
                if not unlock.isdigit() or int(unlock) > level or not isinstance(values, list):
                    continue
                for value in values:
                    if not isinstance(value, str):
                        continue
                    details = library.get_spell_details(value.split("|")[0])
                    if details:
                        (cantrips if int(details.get("level", 0)) == 0 else spells).append(details["name"])
    return list(dict.fromkeys(spells)), list(dict.fromkeys(cantrips))


def options(rules, character):
    """不修改输入，返回尚未填完的选择及服务器计算的完整预览。"""
    name, level = character.class_name, character.level
    data, subclass = class_progression(name, level, character.subclass_id)
    base = rules.get_class_def(name)
    scores = (character.base_stats or character.stats).model_dump()
    errors = []
    asi_levels = [f["level"] for f in data["features"] if f["name"] in {"Ability Score Improvement", "Epic Boon"} and f["level"] <= level]
    for key in character.ability_increases:
        if key not in {str(n) for n in asi_levels}:
            errors.append(f"{key}级没有本次属性提升选择")
    for unlock in asi_levels:
        choices = character.ability_increases.get(str(unlock), [])
        if len(choices) != 2 or any(choice not in ABILITIES for choice in choices):
            errors.append(f"请完成{unlock}级的两点属性提升")
        for choice in choices[:2]:
            if choice in ABILITIES:
                scores[choice] += 1
                if scores[choice] > 20:
                    errors.append("属性值提升专长不能将属性提高到20以上")
    if name == "Monk" and level == 20:
        scores["dexterity"] += 4
        scores["wisdom"] += 4
    if level >= 3 and not subclass:
        errors.append("请选择当前职业的子职业")
    constitution = (scores["constitution"] - 10) // 2
    hit_die = int(data["hit_die"])
    # 最终体质调整值适用于每一级，包含升级提升后的追溯生命增长。
    hp = max(1, hit_die + constitution) + (level - 1) * max(1, hit_die // 2 + 1 + constitution)
    if subclass and subclass["name"] == "Draconic Sorcery":
        hp += level
    spell_data = subclass if subclass and subclass.get("caster_progression") else data
    slots = {str(i + 1): int(n) for i, n in enumerate(spell_data["slots"][level - 1]) if int(n)} if spell_data["slots"] else {}
    metrics = {**data["metrics"][level - 1], **(subclass["metrics"][level - 1] if subclass else {})}
    if data["caster_progression"] == "pact":
        slots = {str(metrics["Slot Level"]): int(metrics["Spell Slots"])}
    max_spell_level = max(map(int, slots), default=0)
    cantrips = int(spell_data["cantrips"][level - 1] or 0)
    prepared = int(spell_data["prepared"][level - 1] or 0)
    # 1级兼容既有职业目录；高等级从成长表派生，不能继续沿用起始数量。
    if level == 1:
        cantrips = int(base.get("starting_cantrips") or 0)
        prepared = int(base.get("starting_prepared_spells") or 0)
        slots = dict(base.get("starting_spell_slots") or {})
        max_spell_level = max(map(int, slots), default=0)
    spell_classes = ["Wizard"] if spell_data.get("caster_progression") == "1/3" else [name]
    if name == "Bard" and level >= 10:
        spell_classes.extend(["Cleric", "Druid", "Wizard"])
    spell_lookup = {}
    for spell_class in spell_classes:
        for spell in rules.library.get_spells_by_class(rules.resolve_spell_library_key(spell_class)):
            spell_lookup[spell["name"]] = spell
    forced_spells, forced_cantrips = [], []
    spell_variants = [block["name"] for block in (subclass or {}).get("additional_spells", []) if block.get("name")]
    variant = character.subclass_spell_variant or (spell_variants[0] if spell_variants else "")
    if character.subclass_spell_variant and character.subclass_spell_variant not in spell_variants:
        errors.append("所选结社法术环境无效")
    bonus_spell_options = {}
    bonus_spell_count = 2 if subclass and subclass["name"] == "College of Lore" and level >= 6 else 0
    if bonus_spell_count:
        for spell_class in ["Cleric", "Druid", "Wizard"]:
            for spell in rules.library.get_spells_by_class(rules.resolve_spell_library_key(spell_class)):
                if int(spell.get("level", 0)) <= 3: bonus_spell_options[spell["name"]] = spell
        normalized_bonus = rules.library.normalize_spell_names(character.bonus_spells)
        if len(normalized_bonus) != 2 or len(set(character.bonus_spells)) != 2 or set(normalized_bonus) - bonus_spell_options.keys():
            errors.append("请选择两个不同且有效的逸闻学院额外法术")
        for selected in normalized_bonus:
            if selected in bonus_spell_options:
                (forced_cantrips if int(bonus_spell_options[selected].get("level", 0)) == 0 else forced_spells).append(selected)
    elif character.bonus_spells:
        errors.append("当前子职业没有这些额外法术选择")
    if level > 1:
        for entry in (data, subclass or {}):
            extra, extra_cantrips = _fixed_spells(entry, level, rules.library, variant)
            forced_spells.extend(extra)
            forced_cantrips.extend(extra_cantrips)
    arcanum_levels = [int(spell_level) for unlock, levels in data.get("arcanum", {}).items() if int(unlock) <= level for spell_level in levels]
    for spell_level in arcanum_levels:
        selected = character.mystic_arcanum.get(str(spell_level), "")
        details = rules.library.get_spell_details(selected) if selected else {}
        if not details or int(details.get("level", 0)) != spell_level or details.get("name") not in spell_lookup:
            errors.append(f"请选择一个{spell_level}环玄奥秘法")
        else:
            forced_spells.append(details["name"])
    if set(character.mystic_arcanum) - {str(x) for x in arcanum_levels}:
        errors.append("玄奥秘法环级超出当前职业等级")
    from class_resources import resource_profile
    resources = resource_profile(name, level, scores, character.subclass_id, character.mystic_arcanum)
    expertise_count = 0
    if level > 1:
        if name == "Bard": expertise_count = 4 if level >= 9 else 2
        elif name == "Rogue": expertise_count = 4 if level >= 6 else 2
        elif name == "Ranger": expertise_count = 3 if level >= 9 else 1
        elif name == "Wizard": expertise_count = 1
    features = [{**feature, "origin": name} for feature in data["features"] if feature["level"] <= level]
    if subclass:
        features += [{**feature, "origin": subclass["name"]} for feature in subclass["features"] if feature["level"] <= level]
    for feature in features:
        feature["name_display"] = FEATURE_LABELS.get(feature["name"], rules.library.localize_game_terms(feature["name"]))
    weapon_previews = {}
    preview_actor = character.model_copy(update={"stats": Stats(**scores)})
    for item in get_shop_catalog():
        if item.get("type") == "weapon":
            attack = rules._character_weapon_attack_profile(preview_actor, InventoryItem(name=item["name"], type="weapon"))
            weapon_previews[item["name"]] = attack
            weapon_previews[rules.library.localize_game_terms(item["name"])] = attack
    def spell_summary(spell):
        return {key: spell[key] for key in ("name", "nameEN", "level", "school") if key in spell}
    spell_ability = spell_data.get("spellcasting_ability") or base.get("spellcasting_ability", "")
    if not spell_ability and subclass:
        spell_ability = next((block["ability"].upper() for block in subclass.get("additional_spells", []) if block.get("ability")), "")
    return {
        "class_name": name, "level": level, "subclass_id": character.subclass_id, "experience_points": LEVEL_XP[level - 1],
        "subclasses": [{"id": s["id"], "name": s["name"], "name_display": SUBCLASS_LABELS.get(s["name"], s["name"])} for s in data["subclasses"]],
        "subclass_name": SUBCLASS_LABELS.get(subclass["name"], subclass["name"]) if subclass else "",
        "ability_increase_levels": asi_levels, "choice_errors": list(dict.fromkeys(errors)),
        "weapon_previews": weapon_previews,
        "stats": scores, "hp_max": hp, "proficiency_bonus": 2 + (level - 1) // 4,
        "max_spell_level": max_spell_level, "expertise_count": expertise_count,
        "forced_spells": list(dict.fromkeys(forced_spells)), "forced_cantrips": list(dict.fromkeys(forced_cantrips)),
        "spell_variants": spell_variants, "bonus_spell_count": bonus_spell_count, "bonus_spell_options": [spell_summary(spell) for spell in bonus_spell_options.values()],
        "arcanum_levels": arcanum_levels, "features": features, "metrics": metrics,
        "spells": [spell_summary(spell) for spell in spell_lookup.values()],
        "class_config": {"starting_cantrips": cantrips, "starting_prepared_spells": prepared,
                         "starting_spell_slots": slots, "resources": resources,
                         "spellcasting_ability": spell_ability,
                         "spellcasting_mode": base.get("spellcasting_mode", "prepared")},
    }


def apply(rules, character):
    if character.base_stats is None:
        character.base_stats = character.stats.model_copy(deep=True)
    profile = options(rules, character)
    character.stats = Stats(**profile["stats"])
    character.subclass_name = profile["subclass_name"]
    character.class_features = profile["features"]
    character.experience_points = profile["experience_points"]
    character.hp_max = character.hp_current = profile["hp_max"]
    character.spells.ability = profile["class_config"]["spellcasting_ability"] or character.spells.ability
    character.spells.cantrips = list(dict.fromkeys([*character.spells.cantrips, *profile["forced_cantrips"]]))
    character.spells.prepared = list(dict.fromkeys([*character.spells.prepared, *profile["forced_spells"]]))
    character.spells.slots = {str(level): SpellSlot(total=int(total), used=0) for level, total in profile["class_config"]["starting_spell_slots"].items()}
    character.resources = {name: ResourcePool(**value) for name, value in profile["class_config"]["resources"].items()}
    character.class_resource_version = 1
    for skill in character.expertise_skills:
        if character.skill_proficiencies.get(skill, 0): character.skill_proficiencies[skill] = 2
    return profile


def validate(rules, character):
    profile = options(rules, character)
    errors = list(profile["choice_errors"])
    if character.level == 1:
        return errors
    allowed = {spell["name"] for spell in profile["spells"] if int(spell.get("level", 0)) <= profile["max_spell_level"]}
    cantrips = rules.library.normalize_spell_names(character.spells.cantrips)
    prepared = rules.library.normalize_spell_names(character.spells.prepared)
    chosen_cantrips = set(cantrips) - set(profile["forced_cantrips"])
    chosen_prepared = set(prepared) - set(profile["forced_spells"])
    if len(chosen_cantrips) != profile["class_config"]["starting_cantrips"]:
        errors.append("戏法数量不符合所选等级")
    if len(chosen_prepared) != profile["class_config"]["starting_prepared_spells"]:
        errors.append("预备/已知法术数量不符合所选等级")
    if (chosen_cantrips | chosen_prepared) - allowed:
        errors.append("所选法术不属于当前职业法术列表或超出可用环级")
    if len(set(character.expertise_skills)) != profile["expertise_count"] or len(set(character.expertise_skills)) != len(character.expertise_skills):
        errors.append(f"当前等级需要选择{profile['expertise_count']}项不同技能专精")
    for skill in character.expertise_skills:
        if not character.skill_proficiencies.get(skill): errors.append("只能为已熟练的技能选择专精")
        if character.class_name == "Wizard" and skill not in {"Arcana", "History", "Investigation", "Medicine", "Nature", "Religion"}:
            errors.append("学者专精必须选择学者特性允许的知识技能")
    return errors
