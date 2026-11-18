"""导入2024法术目录；可叠加用户提供的本地中文法术详述。"""
import argparse
import json
from pathlib import Path
import re

NAMES = {
    "Aid": "援助术", "Lesser Restoration": "次级复原术", "Mass Healing Word": "群体治愈真言", "Revivify": "回生术",
    "Greater Restoration": "高等复原术", "Mass Cure Wounds": "群体疗伤术", "Fireball": "火球术", "Fly": "飞行术",
    "Wish": "祈愿术", "Counterspell": "法术反制", "Dispel Magic": "解除魔法", "Fear": "恐惧术", "Haste": "加速术",
    "Slow": "缓慢术", "Heal": "医疗术", "Power Word Kill": "死亡真言", "Power Word Heal": "痊愈真言",
    "Misty Step": "迷踪步", "Mirror Image": "镜影术", "Invisibility": "隐形术", "Greater Invisibility": "高等隐形术",
    "Detect Thoughts": "侦测思想", "Hold Person": "人类定身术", "Hold Monster": "怪物定身术", "Fire Shield": "火焰护盾",
    "Contact Other Plane": "异界探知", "Find Steed": "寻获坐骑", "Divine Smite": "至圣斩", "Teleport": "传送术",
    "Dimension Door": "任意门", "Polymorph": "变形术", "Cone of Cold": "寒冰锥", "Wall of Force": "力场墙",
    "Sleet Storm": "冰雹雨", "Ice Storm": "冰风暴", "Lightning Bolt": "闪电束", "Mass Heal": "群体医疗术",
}
SCHOOLS = {"A": "防护", "C": "咒法", "D": "预言", "E": "惑控", "V": "塑能", "I": "幻术", "N": "死灵", "T": "变化"}


def plain(value):
    if isinstance(value, str):
        previous = None
        while value != previous:
            previous = value
            value = re.sub(r"\{@\w+ ([^{}]+)\}", lambda m: m[1].split("|")[0], value)
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (plain(x) for x in value)))
    if isinstance(value, dict):
        return "\n".join(filter(None, [value.get("name", ""), plain(value.get("entries", [])), plain(value.get("items", []))]))
    return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/spell_catalog_2024.json")
    parser.add_argument("--chinese-source", type=Path, default=Path(__file__).resolve().parents[1] / "Knowledge/grep_corpus/核心规则/玩家手册2024/法术详述")
    args = parser.parse_args()
    existing = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else None
    spells = json.loads((args.source / "spells/spells-xphb.json").read_text(encoding="utf-8"))["spell"]
    lookup = json.loads((args.source / "generated/gendata-spell-source-lookup.json").read_text(encoding="utf-8"))["xphb"]
    builder = json.loads((Path(__file__).resolve().parents[1] / "data/character_builder_2024.json").read_text(encoding="utf-8"))
    # 老构筑资产中的spell_library_key有历史编码问题，使用实际运行库的规范类别名。
    class_labels = {"Bard": "吟游诗人", "Cleric": "牧师", "Druid": "德鲁伊", "Fighter": "战士", "Monk": "武僧", "Paladin": "圣武士", "Ranger": "游侠", "Rogue": "游荡者", "Sorcerer": "术士", "Warlock": "魔契师", "Wizard": "法师"}
    classes = {c["name"]: class_labels[c["name"]] for c in builder["classes"]}
    output = {"source": "2024 XPHB spell metadata; SRD text under CC BY 4.0, see docs/SRD_LICENSE.md", "SPELL_DATABASE": {key: [] for key in classes.values()}}
    for spell in spells:
        source_classes = lookup.get(spell["name"].lower(), {}).get("class", {}).get("XPHB", {})
        time = spell.get("time", [{}])[0]
        distance = spell.get("range", {}).get("distance", {})
        duration = spell.get("duration", [{}])[0]
        licensed = bool(spell.get("srd52"))
        detail = {
            "name": NAMES.get(spell["name"], spell["name"]), "nameEN": spell["name"], "level": spell["level"],
            "school": SCHOOLS[spell["school"]], "source": "XPHB", "source_page": spell.get("page"),
            "castingTime": f"{time.get('number', 1)} " + {"action": "动作", "bonus": "附赠动作", "reaction": "反应", "minute": "分钟", "hour": "小时"}.get(time.get("unit"), time.get("unit", "")),
            "range": str(distance.get("amount", "")) + {"feet": "尺", "mile": "英里", "self": "自身", "touch": "触及", "sight": "视线", "unlimited": "无限"}.get(distance.get("type"), distance.get("type", "")),
            "concentration": bool(duration.get("concentration")), "ritual": bool(spell.get("meta", {}).get("ritual")),
            "duration": (str(duration.get("duration", {}).get("amount", "")) + " " + duration.get("duration", {}).get("type", "")) if duration.get("type") == "timed" else duration.get("type", ""),
            "components": "、".join(key.upper() for key in ("v", "s", "m") if spell.get("components", {}).get(key)),
            "desc": plain(spell.get("entries", [])) if licensed else "",
            "higherLevels": plain(spell.get("entriesHigherLevel", [])) if licensed else "",
            "rules_text_available": licensed, "srd52": spell.get("srd52", False),
        }
        for name in source_classes:
            if name in classes:
                output["SPELL_DATABASE"][classes[name]].append(detail)
    if existing:
        from merge_spell_catalogs import merge_catalogs
        # 重新导入保留当前目录中的中文、历史ID和别名，不依赖已移除的旧法表。
        output = merge_catalogs(existing, output)
    if args.chinese_source.exists():
        from translate_spell_catalog import source_entries, translate, audit
        output = translate(output, source_entries(args.chinese_source), existing)
        report = audit(output)
        if report["untranslated"] or report["missing_descriptions"]:
            raise ValueError("中文源文尚有未完成的翻译字段，停止生成以免覆盖完整目录")
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Wrote", len(spells), "spell definitions across", len(output["SPELL_DATABASE"]), "class lists")


if __name__ == "__main__":
    main()
