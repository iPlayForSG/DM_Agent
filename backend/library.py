"""Lightweight spell library loader shared by rules and HTTP endpoints."""

import json
import os
import re
from typing import Dict, List, Any

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

TERM_TRANSLATIONS = {
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
    "Poisoned": "中毒",
    "Unconscious": "昏迷",
    "Captured": "被俘",
    "Dead": "死亡",
    "Normal": "正常",
    "Action": "动作",
    "Bonus Action": "附赠动作",
    "Reaction": "反应",
    "Concentration": "专注",
    "Advantage": "优势",
    "Disadvantage": "劣势",
    "Human": "人类",
    "Elf": "精灵",
    "Dwarf": "矮人",
    "Halfling": "半身人",
    "Acolyte": "侍祭",
    "Criminal": "罪犯",
    "Entertainer": "艺人",
    "Magic Initiate (Cleric)": "魔法学徒（牧师）",
    "Alert": "警觉",
    "Musician": "音乐家",
    "Package A": "套装A",
    "Package B": "套装B",
    "Chain Shirt, Shield, Mace, a Holy Symbol, a Priest's Pack, and 7 gp.": "链甲衫、盾牌、硬头锤、一枚圣徽、祭司套组和7金币。",
    "Start with 110 gp instead of the default package.": "不选择默认套装，改为带着110金币开始。",
    "Chain Shirt": "链甲衫",
    "Scale Mail": "鳞甲",
    "Mace": "硬头锤",
    "Shield": "盾牌",
    "Priest's Pack": "祭司套组",
    "Holy Symbol": "圣徽",
    "Holy Symbol (Amulet)": "圣徽（护符）",
    "Holy Symbol (Emblem)": "圣徽（徽记）",
    "Holy Symbol (Reliquary)": "圣徽（圣匣）",
    "Amulet": "护符",
    "Emblem": "徽记",
    "Reliquary": "圣匣",
    "Default starter equipment": "默认起始装备",
    "Choose the form of your holy symbol.": "选择圣徽的形态。",
    "armor": "护甲",
    "weapon": "武器",
    "pack": "套组",
    "focus": "法器",
    "misc": "杂项",
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
    "Acrobatics": "体操",
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
    "Persuasion": "说服",
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
