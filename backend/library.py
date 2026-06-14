"""Lightweight spell library loader shared by rules and HTTP endpoints."""

import json
import os
import re
from typing import Dict, List, Any

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

TERM_TRANSLATIONS = {
    # Classes
    "Artificer": "奇械师",
    "Barbarian": "野蛮人",
    "Bard": "吟游诗人",
    "Cleric": "牧师",
    "Druid": "德鲁伊",
    "Fighter": "战士",
    "Monk": "武僧",
    "Paladin": "圣武士",
    "Ranger": "游侠",
    "Rogue": "游荡者",
    "Sorcerer": "术士",
    "Warlock": "邪术师",
    "Wizard": "法师",
    # Combat/status/action vocabulary
    "Poisoned": "中毒",
    "Unconscious": "昏迷",
    "Captured": "被俘",
    "Dead": "死亡",
    "Normal": "正常",
    "active": "正常",
    "unconscious": "昏迷",
    "captured": "被俘",
    "dead": "死亡",
    "defeat_state": "败北状态",
    "Action": "动作",
    "Bonus Action": "附赠动作",
    "Reaction": "反应",
    "Concentration": "专注",
    "Advantage": "优势",
    "Disadvantage": "劣势",
    # Species
    "Human": "人类",
    "Elf": "精灵",
    "Dwarf": "矮人",
    "Halfling": "半身人",
    # Species traits
    "Resourceful": "机敏",
    "Skilled Adaptation": "多才多艺",
    "Darkvision": "黑暗视觉",
    "Fey Ancestry": "妖精血脉",
    "Keen Senses": "感官敏锐",
    "Dwarven Resilience": "矮人坚韧",
    "Brave": "勇敢",
    "Halfling Nimbleness": "半身人轻巧",
    "Luck": "好运",
    # Backgrounds
    "Acolyte": "侍祭",
    "Criminal": "罪犯",
    "Entertainer": "艺人",
    "Farmer": "农夫",
    "Sage": "贤者",
    "Soldier": "士兵",
    "Wayfarer": "浪人",
    # Origin feats
    "Magic Initiate (Cleric)": "魔法学徒（牧师）",
    "Magic Initiate (Druid)": "魔法学徒（德鲁伊）",
    "Magic Initiate (Wizard)": "魔法学徒（法师）",
    "Alert": "警觉",
    "Crafter": "工匠",
    "Lucky": "幸运",
    "Musician": "音乐家",
    "Savage Attacker": "狂野攻击手",
    "Skilled": "技艺娴熟",
    "Tough": "坚韧",
    # Class resources
    "Wild Shape": "野性变身",
    "Wild Shape uses": "野性变身次数",
    "Second Wind": "二次呼吸",
    "Second Wind uses": "二次呼吸次数",
    "Lay on Hands": "圣疗之手",
    "Healing pool": "治疗储备",
    # Starter package labels and shared copy
    "Package A": "套装A",
    "Package B": "套装B",
    "Package C": "套装C",
    "Default starter equipment": "默认起始装备",
    # Weapons
    "Battleaxe": "战斧",
    "Club": "棍棒",
    "Dagger": "匕首",
    "Dart": "飞镖",
    "Flail": "链枷",
    "Glaive": "长柄刃",
    "Greataxe": "巨斧",
    "Greatsword": "巨剑",
    "Greatclub": "巨棍",
    "Halberd": "斩马刀",
    "Handaxe": "手斧",
    "Heavy Crossbow": "重型十字弓",
    "Hand Crossbow": "手持十字弓",
    "Javelin": "标枪",
    "Lance": "骑枪",
    "Light Crossbow": "轻型十字弓",
    "Light Hammer": "轻锤",
    "Longbow": "长弓",
    "Longsword": "长剑",
    "Mace": "硬头锤",
    "Maul": "大锤",
    "Morningstar": "晨星锤",
    "Net": "投网",
    "Pike": "长枪",
    "Quarterstaff": "长棍",
    "Rapier": "刺剑",
    "Scimitar": "弯刀",
    "Shortbow": "短弓",
    "Shortsword": "短剑",
    "Sickle": "镰刀",
    "Sling": "投石索",
    "Spear": "长矛",
    "Staff": "法杖",
    "Trident": "三叉戟",
    "Warhammer": "战锤",
    "War Pick": "战镐",
    "Whip": "鞭子",
    # Ammunition / travel gear
    "Arrow": "箭矢",
    "Arrows": "箭矢",
    "Bolt": "弩矢",
    "Bolts": "弩矢",
    "Quiver": "箭筒",
    # Armor
    "Chain Mail": "锁子甲",
    "Chain Shirt": "链甲衫",
    "Breastplate": "胸甲",
    "Half Plate": "半身板甲",
    "Hide Armor": "兽皮甲",
    "Leather Armor": "皮甲",
    "Padded Armor": "软垫甲",
    "Plate Armor": "板甲",
    "Ring Mail": "环甲",
    "Scale Mail": "鳞甲",
    "Shield": "盾牌",
    "Splint Armor": "夹板甲",
    "Studded Leather Armor": "钉皮甲",
    # Packs
    "Burglar's Pack": "盗贼套组",
    "Diplomat's Pack": "外交官套组",
    "Dungeoneer's Pack": "地下城探索套组",
    "Entertainer's Pack": "艺人套组",
    "Explorer's Pack": "探险家套组",
    "Priest's Pack": "祭司套组",
    "Scholar's Pack": "学者套组",
    # Tools
    "Artisan's Tools": "工匠工具",
    "Calligrapher's Supplies": "书法家工具",
    "Herbalism Kit": "药草学工具",
    "Potter's Tools": "陶工工具",
    "Thieves' Tools": "盗贼工具",
    "Woodcarver's Tools": "木雕工具",
    # Focuses / arcane & druidic items
    "Arcane Focus": "奥术法器",
    "Arcane Focus (Crystal)": "奥术法器（水晶）",
    "Arcane Focus (Orb)": "奥术法器（宝珠）",
    "Arcane Focus (Quarterstaff)": "奥术法器（长棍）",
    "Arcane Focus (Rod)": "奥术法器（魔杖）",
    "Arcane Focus (Staff)": "奥术法器（法杖）",
    "Arcane Focus (Wand)": "奥术法器（权杖）",
    "Druidic Focus": "德鲁伊法器",
    "Druidic Focus (Sprig of Mistletoe)": "德鲁伊法器（槲寄生枝）",
    "Druidic Focus (Totem)": "德鲁伊法器（图腾）",
    "Druidic Focus (Wooden Staff)": "德鲁伊法器（木杖）",
    "Druidic Focus (Yew Wand)": "德鲁伊法器（紫杉魔杖）",
    "Holy Symbol": "圣徽",
    "Holy Symbol (Amulet)": "圣徽（护符）",
    "Holy Symbol (Emblem)": "圣徽（徽记）",
    "Holy Symbol (Reliquary)": "圣徽（圣匣）",
    "Amulet": "护符",
    "Emblem": "徽记",
    "Reliquary": "圣匣",
    "Sprig of Mistletoe": "槲寄生枝",
    "Totem": "图腾",
    "Wooden Staff": "木杖",
    "Yew Wand": "紫杉魔杖",
    "Crystal": "水晶",
    "Orb": "宝珠",
    # Instruments
    "Musical Instrument": "乐器",
    "Bagpipes": "风笛",
    "Drum": "鼓",
    "Dulcimer": "扬琴",
    "Flute": "横笛",
    "Horn": "号角",
    "Lute": "琉特琴",
    "Lyre": "竖琴",
    "Pan Flute": "排笛",
    "Shawm": "肖姆管",
    "Viol": "维奥尔琴",
    # Weapon properties
    "Finesse": "灵巧",
    "Heavy": "重型",
    "Light": "轻型",
    "Loading": "装填",
    "Ranged": "远程",
    "Reach": "长刃",
    "Special": "特殊",
    "Thrown": "投掷",
    "Two-Handed": "双手",
    "Versatile": "多用",
    "Ammunition": "弹药",
    # Choice group labels
    "Tool or Instrument": "工具或乐器",
    # Choice group descriptions
    "Choose one musical instrument for this starter package.": "从这个起始套装中选择一件乐器。",
    "Choose the form of your holy symbol.": "选择圣徽的形态。",
    "Choose a druidic focus for this starter package.": "为这个起始套装选择一件德鲁伊法器。",
    "Choose one artisan's tool set or musical instrument for this starter package.": "为这个起始套装选择一套工匠工具或一件乐器。",
    # Starter package description presets
    "Chain Shirt, Shield, Mace, a Holy Symbol, a Priest's Pack, and 7 gp.": "链甲衫、盾牌、硬头锤、一枚圣徽、祭司套组和7金币。",
    "Leather Armor, 2 Daggers, a chosen Musical Instrument, an Entertainer's Pack, and 19 gp.": "皮甲、2把匕首、一件所选乐器、艺人套组和19金币。",
    "Leather Armor, Shield, Sickle, a Druidic Focus (Quarterstaff), an Explorer's Pack, Herbalism Kit, and 9 gp.": "皮甲、盾牌、镰刀、一件德鲁伊法器（长棍）、探险家套组、药草学工具和9金币。",
    "Chain Mail, Greatsword, Flail, 8 Javelins, a Dungeoneer's Pack, and 4 gp.": "锁子甲、巨剑、链枷、8支标枪、地下城探索套组和4金币。",
    "Studded Leather Armor, Scimitar, Shortsword, Longbow, 20 Arrows, a Quiver, a Dungeoneer's Pack, and 11 gp.": "钉皮甲、弯刀、短剑、长弓、20支箭矢、箭筒、地下城探索套组和11金币。",
    "Spear, 5 Daggers, a chosen Artisan's Tools or Musical Instrument, an Explorer's Pack, and 11 gp.": "长矛、5把匕首、一套所选工匠工具或乐器、探险家套组和11金币。",
    "Chain Mail, Shield, Longsword, 6 Javelins, a Holy Symbol, a Priest's Pack, and 9 gp.": "锁子甲、盾牌、长剑、6支标枪、一枚圣徽、祭司套组和9金币。",
    "Studded Leather Armor, Scimitar, Shortsword, Longbow, 20 Arrows, a Quiver, a Druidic Focus, an Explorer's Pack, and 7 gp.": "钉皮甲、弯刀、短剑、长弓、20支箭矢、箭筒、一件德鲁伊法器、探险家套组和7金币。",
    "Leather Armor, 2 Daggers, Shortsword, Shortbow, 20 Arrows, a Quiver, Thieves' Tools, a Burglar's Pack, and 8 gp.": "皮甲、2把匕首、短剑、短弓、20支箭矢、箭筒、盗贼工具、盗贼套组和8金币。",
    "Spear, 2 Daggers, an Arcane Focus (Crystal), a Dungeoneer's Pack, and 28 gp.": "长矛、2把匕首、一件奥术法器（水晶）、地下城探索套组和28金币。",
    "Leather Armor, Sickle, 2 Daggers, an Arcane Focus (Orb), a Book of occult lore, a Scholar's Pack, and 15 gp.": "皮甲、镰刀、2把匕首、一件奥术法器（宝珠）、一本奥术典籍、学者套组和15金币。",
    "2 Daggers, an Arcane Focus (Quarterstaff), Robes, a Spellbook, a Scholar's Pack, and 5 gp.": "2把匕首、一件奥术法器（长棍）、法袍、一本法术书、学者套组和5金币。",
    "Start with 50 gp instead of the default package.": "不选择默认套装，改为带着50金币开始。",
    "Start with 55 gp instead of the default package.": "不选择默认套装，改为带着55金币开始。",
    "Start with 90 gp instead of the default package.": "不选择默认套装，改为带着90金币开始。",
    "Start with 100 gp instead of the default package.": "不选择默认套装，改为带着100金币开始。",
    "Start with 110 gp instead of the default package.": "不选择默认套装，改为带着110金币开始。",
    "Start with 150 gp instead of the default package.": "不选择默认套装，改为带着150金币开始。",
    "Start with 155 gp instead of a starter loadout.": "不选择起始装备，改为带着155金币开始。",
    # Miscellaneous gear
    "Book (Occult Lore)": "典籍（奥术卷宗）",
    "Robes": "法袍",
    "Spellbook": "法术书",
    # Item type labels
    "armor": "护甲",
    "ammo": "弹药",
    "book": "典籍",
    "clothing": "服饰",
    "focus": "法器",
    "gear": "装备",
    "misc": "杂项",
    "pack": "套组",
    "tool": "工具",
    "weapon": "武器",
    # Damage types
    "bludgeoning": "钝击",
    "piercing": "穿刺",
    "slashing": "挥砍",
    "fire": "火焰",
    "cold": "寒冷",
    "lightning": "闪电",
    "thunder": "雷鸣",
    "acid": "强酸",
    "poison": "毒素",
    "necrotic": "黯蚀",
    "radiant": "光耀",
    "force": "力场",
    "psychic": "心灵",
    # Abilities
    "strength": "力量",
    "dexterity": "敏捷",
    "constitution": "体质",
    "intelligence": "智力",
    "wisdom": "感知",
    "charisma": "魅力",
    "Strength": "力量",
    "Dexterity": "敏捷",
    "Constitution": "体质",
    "Intelligence": "智力",
    "Wisdom": "感知",
    "Charisma": "魅力",
    # Skills
    "Acrobatics": "杂技",
    "Animal Handling": "驯兽",
    "Arcana": "奥秘",
    "Athletics": "运动",
    "Deception": "欺瞒",
    "History": "历史",
    "Insight": "洞悉",
    "Intimidation": "威吓",
    "Investigation": "调查",
    "Medicine": "医药",
    "Nature": "自然",
    "Perception": "察觉",
    "Performance": "表演",
    "Persuasion": "游说",
    "Religion": "宗教",
    "Sleight of Hand": "巧手",
    "Stealth": "隐匿",
    "Survival": "求生",
}

class Library:
    _instance = None

    def __new__(cls):
        # Keep the spell database in memory once per process.
        if cls._instance is None:
            cls._instance = super(Library, cls).__new__(cls)
            cls._instance.spells = {}
            cls._instance._load_data()
        return cls._instance

    def _load_data(self):
        spells_path = os.path.join(DATA_DIR, "spells.json")
        if os.path.exists(spells_path):
            try:
                with open(spells_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # The current source format is {"SPELL_DATABASE": {"Class": [Spells]}}.
                    self.spells = data.get("SPELL_DATABASE", {})
            except Exception as e:
                print(f"Error loading spells: {e}")

    def get_spells_by_class(self, class_name: str) -> List[Dict[str, Any]]:
        return self.spells.get(class_name, [])

    def get_all_classes(self) -> List[str]:
        return list(self.spells.keys())

    def get_spell_details(self, spell_name: str) -> Dict[str, Any]:
        # Search across all class buckets because the same spell can appear in several lists.
        normalized = str(spell_name or "").strip()
        normalized_fold = normalized.casefold()
        for class_spells in self.spells.values():
            for spell in class_spells:
                name = str(spell.get("name") or "").strip()
                name_en = str(spell.get("nameEN") or "").strip()
                if name == normalized or name_en.casefold() == normalized_fold:
                    return spell
        return {}

    def normalize_spell_name(self, spell_name: str) -> str:
        details = self.get_spell_details(spell_name)
        return str(details.get("name") or spell_name).strip()

    def normalize_spell_names(self, spell_names: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for spell_name in spell_names or []:
            canonical = self.normalize_spell_name(str(spell_name or "").strip())
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            normalized.append(canonical)
        return normalized

    @staticmethod
    def _replace_alias(text: str, english: str, chinese: str) -> str:
        if not english or not chinese or english == chinese:
            return text

        escaped_en = re.escape(english)
        escaped_zh = re.escape(chinese)
        text = re.sub(
            rf"{escaped_zh}\s*[（(]\s*{escaped_en}\s*[）)]",
            chinese,
            text,
        )
        text = re.sub(
            rf"{escaped_zh}\s*[|｜/]\s*{escaped_en}",
            chinese,
            text,
        )
        return re.sub(
            rf"(?<![A-Za-z0-9]){escaped_en}(?![A-Za-z0-9])",
            chinese,
            text,
        )

    @staticmethod
    def _strip_duplicate_chinese_aliases(text: str) -> str:
        return re.sub(
            r"([\u4e00-\u9fff][\u4e00-\u9fff·]{1,30})\s*[（(]\s*\1\s*[）)]",
            r"\1",
            text,
        )

    def localize_game_terms(self, text: str) -> str:
        """Convert player-facing English D&D aliases to canonical Simplified Chinese."""
        localized = str(text or "")
        if not localized:
            return localized

        aliases: Dict[str, str] = {}
        for class_spells in self.spells.values():
            for spell in class_spells:
                english = str(spell.get("nameEN") or "").strip()
                chinese = str(spell.get("name") or "").strip()
                if english and chinese:
                    aliases[english] = chinese
        aliases.update(TERM_TRANSLATIONS)

        for english, chinese in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
            localized = self._replace_alias(localized, english, chinese)
        return self._strip_duplicate_chinese_aliases(localized)

    def localize_rag_snippet(self, snippet: Dict[str, Any]) -> Dict[str, Any]:
        """Localize snippet display fields while preserving metadata used for citations."""
        localized = dict(snippet or {})
        for field in ("heading", "content"):
            if field in localized:
                localized[field] = self.localize_game_terms(str(localized.get(field) or ""))
        return localized

    def localize_rag_snippets(self, snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.localize_rag_snippet(snippet) for snippet in snippets or []]
