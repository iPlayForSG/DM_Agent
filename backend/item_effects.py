"""物品规则资料与只读效果说明；不执行使用、伤害或治疗结算。

消耗品数值依据本地 5e.tools items.json 的 XPHB pp.222/228 与
XDMG p.288；只保留本项目需要的数值和自行整理的简体中文说明。
"""
from copy import deepcopy
import re

from library import Library
from starter_shop import get_shop_item_by_name


ITEM_EFFECTS = [
    {"name": "Potion of Healing", "aliases": ["治疗药水", "治疗药", "治疗药剂", "治愈药水"],
     "type": "potion", "healing_expression": "2d4+2",
     "effect_description": "附赠动作饮用，或喂给5尺内的另一名生物；饮用者恢复2d4+2生命。"},
    {"name": "Potion of Greater Healing", "aliases": ["高等治疗药水", "强效治疗药水"],
     "type": "potion", "healing_expression": "4d4+4", "effect_description": "饮用后恢复4d4+4生命。"},
    {"name": "Potion of Superior Healing", "aliases": ["超等治疗药水", "超效治疗药水"],
     "type": "potion", "healing_expression": "8d4+8", "effect_description": "饮用后恢复8d4+8生命。"},
    {"name": "Potion of Supreme Healing", "aliases": ["极效治疗药水", "至高治疗药水"],
     "type": "potion", "healing_expression": "10d4+20", "effect_description": "饮用后恢复10d4+20生命。"},
    {"name": "Acid", "aliases": ["强酸", "强酸瓶", "酸液", "酸液瓶"], "type": "consumable",
     "damage_expression": "2d6", "damage_type": "acid",
     "effect_description": "攻击动作中替代一次攻击，投向20尺内可见生物或物体；目标敏捷豁免失败受到2d6强酸伤害。DC为8+使用者敏捷调整值+熟练加值。"},
    {"name": "Alchemist's Fire", "aliases": ["炼金火", "炼金火焰", "炼金火瓶"], "type": "consumable",
     "damage_expression": "1d4", "damage_type": "fire",
     "effect_description": "攻击动作中替代一次攻击，投向20尺内可见生物或物体；目标敏捷豁免失败受到1d4火焰伤害并开始燃烧。DC为8+使用者敏捷调整值+熟练加值；燃烧另按对应规则结算。"},
]


def lookup_item_rules(name):
    shop = get_shop_item_by_name(name)
    if shop:
        return shop
    key = str(name or "").strip().casefold().replace("’", "'")
    for entry in ITEM_EFFECTS:
        if key in {value.casefold() for value in [entry["name"], *entry["aliases"]]}:
            return deepcopy(entry)
    return None


def scroll_spell_name(name):
    """只接受明确卷轴语法，不能把含法术名的普通战利品认成卷轴。"""
    text = str(name or "").strip()
    for pattern in (r"(?:法术)?卷轴[（(：:]\s*(.+?)\s*[）)]?", r"(.+?)(?:法术)?卷轴", r"(?:Spell )?Scroll (?:of |[(:])(.+?)\)?"):
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            return match[1].strip("（）():： ")
    return ""


def enrich_effect_fields(item, *, library=None, strict=False):
    """返回副本；已知目录纠正缺项，自定义备注和名字保持不变。"""
    result = item.model_copy(deep=True)
    definition = lookup_item_rules(item.rules_name or item.name)
    if strict and item.rules_name and not definition:
        raise ValueError(f"未收录的物品规则名称：{item.rules_name}")
    if definition:
        result.rules_name = definition["name"]
        result.type = definition.get("type", result.type)
        for key in ("damage_expression", "damage_type", "healing_expression", "effect_description"):
            if definition.get(key):
                setattr(result, key, definition[key])
        if definition.get("armor_class_bonus"):
            result.armor_class_bonus = int(definition["armor_class_bonus"])
        result.properties = list(dict.fromkeys([*definition.get("properties", []), *result.properties]))
        if not result.notes:
            result.notes = definition.get("notes", "")
    if item.name.strip().casefold() in {"卷轴", "法术卷轴", "spell scroll"}:
        result.type = "scroll"
    spell_name = item.spell_name or scroll_spell_name(item.name)
    if spell_name:
        result.type = "scroll"
        details = (library or Library()).get_spell_details(spell_name) or {}
        if details:
            result.spell_name = details.get("name") or spell_name
            if result.spell_level is None:
                result.spell_level = int(details.get("level") or 0)
            if strict and result.spell_level < int(details.get("level") or 0):
                raise ValueError("卷轴环级不能低于其法术基础环级")
    return result, definition or {}


def effect_display(item, *, library=None):
    """保留骰点的上下文（每发、每回合等），不把第一个骰式当总伤害。"""
    description = item.effect_description
    summary = description
    if item.type == "scroll":
        details = (library or Library()).get_spell_details(item.spell_name) or {}
        if not details:
            return {"effect_summary": description or "卷轴法术资料未完整记录", "effect_description": description}
        body = str(details.get("desc") or details.get("description") or "")
        higher = str(details.get("higherLevels") or details.get("higher_levels") or "")
        base_level = int(details.get("level") or 0)
        prefix = "基础法术效果" if item.spell_level != base_level else "法术效果"
        # 描述本身包含规则确定的次数、伤害类型、豁免与变量，不猜测卷轴未提供的调整值。
        dice_sentences = [sentence.strip() for sentence in re.split(r"(?<=[。！？\n])", body)
                          if re.search(r"\d+d\d+", sentence, re.IGNORECASE)]
        summary = f"{prefix}：" + ("".join(dice_sentences) if dice_sentences else body)
        if item.spell_level != base_level:
            summary += " 升环效果见说明。"
        description = "\n\n".join(part for part in (
            description, f"{base_level}环基础法术：{body}", f"升环施法：{higher}" if higher else "",
            "卷轴按法术的施法时间使用；可用职业、豁免DC、攻击加值及高环级施法检定依卷轴规则结算。",
        ) if part)
    elif not summary and item.type in {"weapon", "potion", "consumable", "scroll"} and not (item.damage_expression or item.healing_expression):
        summary = "使用效果未完整记录"
    return {"effect_summary": summary, "effect_description": description}
