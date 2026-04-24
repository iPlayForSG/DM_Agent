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
