"""Rule catalog and validation helpers for level-1 character creation and play."""

import json
import os
from typing import Any, Dict, List, Optional

from library import Library
from models import Character, InventoryItem, ResourcePool, SpellSlot

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "character_builder_2024.json")

# Skill/save lookup tables are shared by builder validation and live action resolution.
SKILL_TO_ABILITY = {
    "Acrobatics": "dexterity",
    "Animal Handling": "wisdom",
    "Arcana": "intelligence",
    "Athletics": "strength",
    "Deception": "charisma",
    "History": "intelligence",
    "Insight": "wisdom",
    "Intimidation": "charisma",
    "Investigation": "intelligence",
    "Medicine": "wisdom",
    "Nature": "intelligence",
    "Perception": "wisdom",
    "Performance": "charisma",
    "Persuasion": "charisma",
    "Religion": "intelligence",
    "Sleight of Hand": "dexterity",
    "Stealth": "dexterity",
    "Survival": "wisdom",
}

ABILITY_ALIAS = {
    "STR": "strength",
    "DEX": "dexterity",
    "CON": "constitution",
    "INT": "intelligence",
    "WIS": "wisdom",
    "CHA": "charisma",
    "Strength": "strength",
    "Dexterity": "dexterity",
    "Constitution": "constitution",
    "Intelligence": "intelligence",
    "Wisdom": "wisdom",
    "Charisma": "charisma",
}

SPELL_LIBRARY_KEY_ALIASES = {
    "bard": "吟游诗人",
    "吟游诗人": "吟游诗人",
    "cleric": "牧师",
    "牧师": "牧师",
    "druid": "德鲁伊",
    "德鲁伊": "德鲁伊",
    "paladin": "圣武士",
    "圣武士": "圣武士",
    "ranger": "游侠",
    "游侠": "游侠",
    "sorcerer": "术士",
    "术士": "术士",
    "warlock": "魔契师",
    "魔契师": "魔契师",
    "邪术师": "魔契师",
    "wizard": "法师",
    "法师": "法师",
}


def proficiency_bonus_for_level(level: int) -> int:
    return 2 + max(0, (max(1, level) - 1) // 4)


class RuleCatalog:
    _instance = None

    def __new__(cls):
        # The rule catalog is static data, so one in-memory instance is enough.
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        with open(DATA_PATH, "r", encoding="utf-8") as handle:
            self.data = json.load(handle)
        self.library = Library()

    def get_builder_catalog(self) -> Dict[str, Any]:
        return {
            "ability_generation": self.data.get("ability_generation", {}),
            "species": self.data.get("species", []),
            "backgrounds": self.data.get("backgrounds", []),
            "origin_feats": self.data.get("origin_feats", []),
            "classes": self.data.get("classes", []),
        }

    # Catalog lookup helpers.
    def get_background(self, name: str) -> Optional[Dict[str, Any]]:
        for background in self.data.get("backgrounds", []):
            if background["name"] == name:
                return background
        return None

    def get_species(self, name: str) -> Optional[Dict[str, Any]]:
        for species in self.data.get("species", []):
            if species["name"] == name:
                return species
        return None

    def get_class_def(self, class_name: str) -> Optional[Dict[str, Any]]:
        for class_def in self.data.get("classes", []):
            if class_def["name"] == class_name or class_def.get("spell_library_key") == class_name:
                return class_def
        return None

    def get_starter_options(self, class_def: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not class_def:
            return []

        options = class_def.get("starter_equipment_options") or []
        if options:
            return options

        legacy_items = class_def.get("starter_equipment") or []
        if not legacy_items:
            return []

        return [
            {
                "id": "package_a",
                "label": "Package A",
                "description": "Default starter equipment",
                "items": legacy_items,
                "gold_gp": 0,
            }
        ]

    def get_starter_option(self, class_def: Optional[Dict[str, Any]], option_id: str = "") -> Optional[Dict[str, Any]]:
        options = self.get_starter_options(class_def)
        if not options:
            return None

        if option_id:
            for option in options:
                if option.get("id") == option_id:
                    return option

        return options[0]

    def resolve_starter_option_items(
        self,
        option: Optional[Dict[str, Any]],
        starter_choice_ids: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        if not option:
            return []

        resolved_items = list(option.get("items", []))
        selected_ids = starter_choice_ids or {}

        for choice_group in option.get("choices", []):
            selected_option_id = selected_ids.get(choice_group.get("id", ""))
            if not selected_option_id:
                continue
            selected_option = next(
                (choice for choice in choice_group.get("options", []) if choice.get("id") == selected_option_id),
                None,
            )
            if selected_option:
                resolved_items.extend(selected_option.get("items", []))

        return resolved_items

    def resolve_spell_library_key(self, class_name: str) -> str:
        # Handle legacy localized keys before falling back to the requested name.
        class_def = self.get_class_def(class_name)
        library_keys = set(self.library.get_all_classes())
        candidates = [
            class_name,
            class_def.get("spell_library_key") if class_def else "",
            class_def.get("name") if class_def else "",
            class_def.get("id") if class_def else "",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            normalized = str(candidate).strip()
            alias = SPELL_LIBRARY_KEY_ALIASES.get(normalized) or SPELL_LIBRARY_KEY_ALIASES.get(normalized.lower())
            if alias:
                return alias
            if normalized in library_keys:
                return normalized
        return class_name

    def get_ability_modifier(self, character: Character, ability_name: str) -> int:
        attr = ABILITY_ALIAS.get(ability_name, ability_name).lower()
        value = getattr(character.stats, attr, 10)
        return (value - 10) // 2

    def get_skill_modifier(self, character: Character, skill_name: str) -> int:
        ability = SKILL_TO_ABILITY.get(skill_name, "wisdom")
        modifier = self.get_ability_modifier(character, ability)
        rank = int(character.skill_proficiencies.get(skill_name, 0))
        if rank > 0:
            modifier += proficiency_bonus_for_level(character.level) * rank
        return modifier

    def get_save_modifier(self, character: Character, save_name: str) -> int:
        ability = ABILITY_ALIAS.get(save_name, save_name)
        modifier = self.get_ability_modifier(character, ability)
        if character.save_proficiencies.get(ABILITY_ALIAS.get(save_name, save_name).lower(), False):
            modifier += proficiency_bonus_for_level(character.level)
        return modifier

    # Builder validation keeps save data coherent before it is persisted.
    def validate_character(self, character: Character) -> List[str]:
        errors: List[str] = []
        if character.species and not self.get_species(character.species):
            errors.append(f"Unknown species: {character.species}")

        background = self.get_background(character.background_name) if character.background_name else None
        if character.background_name and not background:
            errors.append(f"Unknown background: {character.background_name}")

        if background and character.origin_feat and background.get("origin_feat") != character.origin_feat:
            errors.append(
                f"Background {character.background_name} expects origin feat {background['origin_feat']}, got {character.origin_feat}"
            )

        class_def = self.get_class_def(character.class_name)
        if not class_def:
            errors.append(f"Unknown class: {character.class_name}")

        allowed_skills = set(background.get("skill_proficiencies", [])) if background else set()
        if class_def:
            allowed_skills.update(class_def.get("skill_choices", []))
        for skill in character.skill_proficiencies:
            if skill not in SKILL_TO_ABILITY:
                errors.append(f"Unknown skill: {skill}")
            elif allowed_skills and skill not in allowed_skills:
                errors.append(f"Skill {skill} is not available for class/background selection")

        if class_def:
            background_skills = set(background.get("skill_proficiencies", [])) if background else set()
            class_selected_skills = [
                skill
                for skill, rank in character.skill_proficiencies.items()
                if int(rank) > 0 and skill in class_def.get("skill_choices", []) and skill not in background_skills
            ]
            if len(class_selected_skills) > int(class_def.get("skills_to_choose", 0)):
                errors.append(
                    f"Selected {len(class_selected_skills)} class skills but only {class_def.get('skills_to_choose', 0)} are allowed"
                )

            starter_options = self.get_starter_options(class_def)
            if starter_options and character.starter_option_id:
                if not any(option.get("id") == character.starter_option_id for option in starter_options):
                    errors.append(f"Unknown starter equipment option: {character.starter_option_id}")
            starter_option = self.get_starter_option(class_def, character.starter_option_id)
            if starter_option:
                for choice_group in starter_option.get("choices", []):
                    group_id = choice_group.get("id", "")
                    selected_choice_id = character.starter_choice_ids.get(group_id, "")
                    if not selected_choice_id:
                        errors.append(f"Missing starter equipment choice: {group_id}")
                        continue
                    if not any(option.get("id") == selected_choice_id for option in choice_group.get("options", [])):
                        errors.append(f"Unknown starter equipment choice for {group_id}: {selected_choice_id}")

        for prepared_spell in character.spells.prepared:
            details = self.library.get_spell_details(prepared_spell)
            if not details:
                errors.append(f"Unknown prepared spell: {prepared_spell}")
            elif int(details.get("level", 0)) == 0:
                errors.append(f"Cantrip cannot be submitted as a prepared spell: {prepared_spell}")

        for cantrip_name in character.spells.cantrips:
            details = self.library.get_spell_details(cantrip_name)
            if not details:
                errors.append(f"Unknown cantrip: {cantrip_name}")
            elif int(details.get("level", 0)) != 0:
                errors.append(f"Cantrip list contains a non-cantrip spell: {cantrip_name}")

        if class_def and class_def.get("spellcasting_ability"):
            starting_cantrip_count = int(class_def.get("starting_cantrips", 0)) if character.level == 1 else 0
            if character.level == 1 and starting_cantrip_count > 0 and len(character.spells.cantrips) != starting_cantrip_count:
                errors.append(
                    f"Cantrip count {len(character.spells.cantrips)} must equal level 1 requirement {starting_cantrip_count}"
                )
            if class_def.get("spellcasting_mode") == "prepared":
                prepared_limit = int(class_def.get("starting_prepared_spells", 0)) if character.level == 1 else 0
                if character.level == 1 and prepared_limit > 0 and len(character.spells.prepared) != prepared_limit:
                    errors.append(
                        f"Prepared spell count {len(character.spells.prepared)} must equal level 1 requirement {prepared_limit}"
                    )
                if prepared_limit <= 0:
                    prepared_limit = max(1, self.get_ability_modifier(character, character.spells.ability) + character.level)
                if len(character.spells.prepared) > prepared_limit:
                    errors.append(
                        f"Prepared spell count {len(character.spells.prepared)} exceeds limit {prepared_limit}"
                    )

        for skill, rank in character.skill_proficiencies.items():
            if int(rank) not in (0, 1, 2):
                errors.append(f"Invalid proficiency rank for skill {skill}: {rank}")

        return errors

    def apply_builder_defaults(self, character: Character) -> Character:
        # Fill rule-driven defaults so the frontend can submit a smaller payload.
        background = self.get_background(character.background_name) if character.background_name else None
        class_def = self.get_class_def(character.class_name) if character.class_name else None

        if background and not character.origin_feat:
            character.origin_feat = background["origin_feat"]

        if background:
            merged_skills = dict(character.skill_proficiencies)
            for skill_name in background.get("skill_proficiencies", []):
                merged_skills.setdefault(skill_name, 1)
            character.skill_proficiencies = merged_skills

        if class_def and not character.save_proficiencies:
            character.save_proficiencies = {save_name: True for save_name in class_def.get("save_proficiencies", [])}

        if class_def and class_def.get("spellcasting_ability"):
            character.spells.ability = class_def["spellcasting_ability"]
            character.spells.casting_mode = class_def.get("spellcasting_mode", "prepared")

        if class_def and not character.resources:
            resources: Dict[str, ResourcePool] = {}
            for resource_name, resource_def in class_def.get("resources", {}).items():
                resources[resource_name] = ResourcePool(**resource_def)
            character.resources = resources

        starter_option = self.get_starter_option(class_def, character.starter_option_id)
        if starter_option and not character.starter_option_id:
            character.starter_option_id = starter_option.get("id", "")

        if starter_option and not character.inventory:
            resolved_items = self.resolve_starter_option_items(starter_option, character.starter_choice_ids)
            character.inventory = [InventoryItem(**item_def) for item_def in resolved_items]

        if starter_option and character.gold_gp <= 0:
            character.gold_gp = int(starter_option.get("gold_gp", 0))
        elif class_def and character.gold_gp <= 0:
            character.gold_gp = int(class_def.get("starting_gold_gp", 0))

        if class_def and not character.spells.slots and class_def.get("starting_spell_slots"):
            character.spells.slots = {
                level: SpellSlot(total=slot_total, used=0)
                for level, slot_total in class_def["starting_spell_slots"].items()
            }

        if class_def and character.hp_max <= 0:
            hit_die = int(class_def.get("hit_die", 8))
            character.hp_max = hit_die + self.get_ability_modifier(character, "constitution")
            character.hp_current = character.hp_max

        if class_def and character.ac <= 10:
            dex_mod = self.get_ability_modifier(character, "dexterity")
            armor_bonus = sum(item.armor_class_bonus for item in character.inventory if item.is_equipped)
            character.ac = 10 + dex_mod + armor_bonus

        return character

    def can_cast_spell(
        self,
        character: Character,
        spell_name: str,
        slot_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Spell legality is resolved locally so the DM never fabricates slot usage.
        details = self.library.get_spell_details(spell_name)
        if not details:
            return {"ok": False, "error": f"Unknown spell: {spell_name}"}

        spell_level = int(details.get("level", 0))
        if spell_level == 0:
            if spell_name not in character.spells.cantrips:
                return {"ok": False, "error": f"Cantrip not known: {spell_name}"}
            return {"ok": True, "spell": details, "resolved_slot_level": 0}

        if spell_name not in character.spells.prepared:
            return {"ok": False, "error": f"Spell not prepared or known: {spell_name}"}

        resolved_slot = spell_level if slot_level is None else int(slot_level)
        if resolved_slot < spell_level:
            return {"ok": False, "error": f"Slot level {resolved_slot} is too low for {spell_name}"}

        slot_state = character.spells.slots.get(str(resolved_slot))
        if not slot_state or slot_state.total - slot_state.used <= 0:
            return {"ok": False, "error": f"No available spell slot at level {resolved_slot}"}

        return {"ok": True, "spell": details, "resolved_slot_level": resolved_slot}

    def consume_spell_slot(self, character: Character, slot_level: int) -> None:
        if slot_level <= 0:
            return
        slot = character.spells.slots.get(str(slot_level))
        if slot:
            slot.used += 1
