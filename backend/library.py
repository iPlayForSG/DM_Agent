"""Lightweight spell library loader shared by rules and HTTP endpoints."""

import json
import os
from typing import Dict, List, Any

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

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
        for class_spells in self.spells.values():
            for spell in class_spells:
                if spell.get("name") == spell_name or spell.get("nameEN") == spell_name:
                    return spell
        return {}
