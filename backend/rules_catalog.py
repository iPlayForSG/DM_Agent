"""Rule catalog and validation helpers for level-1 character creation and play."""

import json
import os
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

from library import Library, TERM_TRANSLATIONS
from models import Character, GameState, InventoryItem, PendingCustomEquipment, ResourcePool, SpellSlot
from starter_shop import get_shop_catalog, get_shop_item, get_shop_item_by_name

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
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
    "strength": "strength",
    "dexterity": "dexterity",
    "constitution": "constitution",
    "intelligence": "intelligence",
    "wisdom": "wisdom",
    "charisma": "charisma",
    "力量": "strength",
    "敏捷": "dexterity",
    "体质": "constitution",
    "智力": "intelligence",
    "感知": "wisdom",
    "魅力": "charisma",
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

SKILL_ALIASES = {name.casefold(): name for name in SKILL_TO_ABILITY}
SKILL_ALIASES.update(
    {
        str(TERM_TRANSLATIONS.get(name) or "").strip().casefold(): name
        for name in SKILL_TO_ABILITY
        if str(TERM_TRANSLATIONS.get(name) or "").strip()
    }
)

POINT_BUY_COSTS = {
    8: 0,
    9: 1,
    10: 2,
    11: 3,
    12: 4,
    13: 5,
    14: 7,
    15: 9,
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
        classes: List[Dict[str, Any]] = []
        for class_def in self.data.get("classes", []):
            class_copy = deepcopy(class_def)
            custom_purchase_option = self.get_custom_purchase_option(class_def)
            class_copy["custom_purchase_budget_gp"] = (
                int(custom_purchase_option.get("gold_gp", 0))
                if custom_purchase_option
                else int(class_def.get("starting_gold_gp", 0))
            )
            class_copy["custom_purchase_option_id"] = custom_purchase_option.get("id", "") if custom_purchase_option else ""
            classes.append(class_copy)
        return {
            "ability_generation": self.data.get("ability_generation", {}),
            "species": self.data.get("species", []),
            "backgrounds": self.data.get("backgrounds", []),
            "origin_feats": self.data.get("origin_feats", []),
            "classes": classes,
            "equipment_shop_items": get_shop_catalog(),
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

    def get_custom_purchase_option(self, class_def: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        options = self.get_starter_options(class_def)
        if not options:
            return None

        gold_only = [
            option
            for option in options
            if not option.get("items") and not option.get("choices")
        ]
        if gold_only:
            return max(gold_only, key=lambda option: int(option.get("gold_gp", 0)))

        return max(options, key=lambda option: int(option.get("gold_gp", 0)))

    def get_custom_purchase_budget_gp(self, class_def: Optional[Dict[str, Any]]) -> int:
        option = self.get_custom_purchase_option(class_def)
        if option:
            return int(option.get("gold_gp", 0))
        if class_def:
            return int(class_def.get("starting_gold_gp", 0))
        return 0

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
        # Normalize localized class keys before trying the requested name.
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

    @staticmethod
    def normalize_skill_name(skill_name: str) -> str:
        normalized = " ".join(str(skill_name or "").split()).strip()
        return SKILL_ALIASES.get(normalized.casefold(), normalized)

    @staticmethod
    def normalize_save_name(save_name: str) -> str:
        normalized = " ".join(str(save_name or "").split()).strip()
        return ABILITY_ALIAS.get(normalized, ABILITY_ALIAS.get(normalized.casefold(), normalized.casefold()))

    def get_skill_modifier(self, character: Character, skill_name: str) -> int:
        canonical_skill = self.normalize_skill_name(skill_name)
        ability = SKILL_TO_ABILITY.get(canonical_skill, "wisdom")
        modifier = self.get_ability_modifier(character, ability)
        rank = int(character.skill_proficiencies.get(canonical_skill, character.skill_proficiencies.get(skill_name, 0)))
        if rank > 0:
            modifier += proficiency_bonus_for_level(character.level) * rank
        return modifier

    def get_save_modifier(self, character: Character, save_name: str) -> int:
        ability = self.normalize_save_name(save_name)
        modifier = self.get_ability_modifier(character, ability)
        if any(
            bool(is_proficient) and self.normalize_save_name(proficiency_name) == ability
            for proficiency_name, is_proficient in character.save_proficiencies.items()
        ):
            modifier += proficiency_bonus_for_level(character.level)
        return modifier

    def get_spell_save_profile(self, character: Character, spell_name: str) -> Dict[str, Any]:
        class_def = self.get_class_def(character.class_name)
        casting_ability = str((class_def or {}).get("spellcasting_ability") or "").strip()
        if not casting_ability:
            raise ValueError(f"{character.name} has no authoritative spellcasting ability")

        details = self.library.get_spell_details(spell_name)
        if not details:
            raise ValueError(f"Unknown spell: {spell_name}")

        canonical_name = str(details.get("name") or spell_name).strip()
        known_spells = set(
            self.library.normalize_spell_names(
                list(character.spells.cantrips) + list(character.spells.prepared)
            )
        )
        if canonical_name not in known_spells:
            raise ValueError(f"Spell not known or prepared: {canonical_name}")

        description = " ".join(
            str(details.get(field_name) or "")
            for field_name in ("desc", "description", "higherLevels", "higher_levels")
        )
        save_match = re.search(
            r"(力量|敏捷|体质|智力|感知|魅力)\s*豁免"
            r"|(?:\b)(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+saving throw",
            description,
            flags=re.IGNORECASE,
        )
        if not save_match:
            raise ValueError(f"Spell does not define a saving throw: {canonical_name}")

        save_name = self.normalize_save_name(save_match.group(1) or save_match.group(2))
        dc = (
            8
            + proficiency_bonus_for_level(character.level)
            + self.get_ability_modifier(character, casting_ability)
        )
        return {
            "spell_name": canonical_name,
            "save_name": save_name,
            "dc": dc,
            "dc_source": "character_spellcasting",
            "casting_ability": self.normalize_save_name(casting_ability),
        }

    def get_point_buy_config(self) -> Dict[str, int]:
        point_buy = self.data.get("ability_generation", {}).get("point_buy", {})
        return {
            "budget": int(point_buy.get("budget", 27)),
            "minimum": int(point_buy.get("minimum", 8)),
            "maximum": int(point_buy.get("maximum", 15)),
        }

    def get_stat_values(self, character: Character) -> Dict[str, int]:
        return {
            "strength": int(character.stats.strength),
            "dexterity": int(character.stats.dexterity),
            "constitution": int(character.stats.constitution),
            "intelligence": int(character.stats.intelligence),
            "wisdom": int(character.stats.wisdom),
            "charisma": int(character.stats.charisma),
        }

    def get_point_buy_spend(self, character: Character) -> Optional[int]:
        total_cost = 0
        for value in self.get_stat_values(character).values():
            if value not in POINT_BUY_COSTS:
                return None
            total_cost += POINT_BUY_COSTS[value]
        return total_cost

    def get_expected_level_one_hp(self, character: Character, class_def: Optional[Dict[str, Any]]) -> int:
        if not class_def:
            return max(1, int(character.hp_max or 1))
        hit_die = int(class_def.get("hit_die", 8))
        return max(1, hit_die + self.get_ability_modifier(character, "constitution"))

    def _resolve_pending_custom_item(self, pending_item: PendingCustomEquipment) -> Optional[InventoryItem]:
        name = str(pending_item.name or "").strip()
        if not name:
            return None

        reserved_cost = int(pending_item.reserved_cost_gp or 0)
        notes: List[str] = ["待 DM 在创建后决定具体属性"]
        if reserved_cost > 0:
            notes.append(f"预留预算 {reserved_cost} gp")
        if str(pending_item.notes or "").strip():
            notes.append(str(pending_item.notes).strip())

        return InventoryItem(
            name=name,
            quantity=max(1, int(pending_item.quantity or 1)),
            type="gear",
            notes="; ".join(notes),
            source="dm_pending",
            tags=["custom_pending"],
        )

    def _build_inventory_item_from_shop_entry(self, item_def: Dict[str, Any], quantity: int) -> InventoryItem:
        bundle_size = max(1, int(item_def.get("bundle_size", 1) or 1))
        inventory_quantity = max(1, int(quantity or 1)) * bundle_size
        return InventoryItem(
            name=item_def["name"],
            quantity=inventory_quantity,
            is_equipped=bool(item_def.get("auto_equip", False)),
            type=item_def.get("type", "misc"),
            notes=item_def.get("notes", ""),
            source="custom_purchase",
            tags=list(item_def.get("tags", [])),
            damage_type=item_def.get("damage_type", ""),
            armor_class_bonus=int(item_def.get("armor_class_bonus", 0) or 0),
            properties=list(item_def.get("properties", [])),
        )

    def _weapon_ability_modifier(self, character: Character, item_data: Dict[str, Any]) -> int:
        properties = set(item_data.get("properties", []) or [])
        strength_mod = self.get_ability_modifier(character, "strength")
        dexterity_mod = self.get_ability_modifier(character, "dexterity")
        if "Finesse" in properties:
            return max(strength_mod, dexterity_mod)
        if "Ranged" in properties:
            return dexterity_mod
        return strength_mod

    def _character_weapon_attack_profile(self, character: Character, item: InventoryItem) -> Dict[str, Any]:
        catalog_item = get_shop_item_by_name(item.name) or {}
        item_data = {**item.model_dump(mode="python"), **catalog_item}
        ability_modifier = self._weapon_ability_modifier(character, item_data)
        attack_bonus = (
            int(item.attack_bonus)
            if item.attack_bonus is not None
            else ability_modifier + proficiency_bonus_for_level(character.level)
        )
        damage_die = str(catalog_item.get("damage_die") or "").strip()
        damage_expression = (
            self._format_damage_expression(damage_die, ability_modifier)
            if damage_die
            else str(item.damage_expression or "").strip()
        )
        if not damage_expression:
            raise ValueError(f"Weapon has no authoritative damage expression: {item.name}")
        return {
            "attack_name": item.name,
            "attack_bonus": attack_bonus,
            "damage_expression": damage_expression,
            "damage_type": str(catalog_item.get("damage_type") or item.damage_type or ""),
            "source": "character_sheet",
        }

    def resolve_character_attack_profile(
        self,
        character: Character,
        attack_name: str = "",
        requested_attack_bonus: Optional[int] = None,
        requested_damage_expression: str = "",
    ) -> Dict[str, Any]:
        weapons = [
            item
            for item in character.inventory
            if item.type == "weapon" and int(item.quantity or 0) > 0
        ]
        if not weapons:
            raise ValueError(f"Character has no weapon attack on the character sheet: {character.name}")

        normalized_name = " ".join(str(attack_name or "").split()).strip().casefold()
        selected: Optional[InventoryItem] = None
        if normalized_name:
            matching = [
                item
                for item in weapons
                if normalized_name
                in {
                    str(item.name or "").strip().casefold(),
                    str(self.library.localize_game_terms(item.name) or "").strip().casefold(),
                }
            ]
            if len(matching) == 1:
                selected = matching[0]
            elif not matching:
                raise ValueError(f"Weapon attack is not present on the character sheet: {attack_name}")
            else:
                raise ValueError(f"Weapon attack name is ambiguous on the character sheet: {attack_name}")
        elif len(weapons) == 1:
            selected = weapons[0]
        else:
            profiles = [self._character_weapon_attack_profile(character, item) for item in weapons]
            requested_expression = str(requested_damage_expression or "").strip().casefold()
            matching_profiles = [
                profile
                for profile in profiles
                if requested_attack_bonus is not None
                and int(profile["attack_bonus"]) == int(requested_attack_bonus)
                and requested_expression
                and str(profile["damage_expression"]).casefold() == requested_expression
            ]
            if len(matching_profiles) == 1:
                return matching_profiles[0]
            equipped = [item for item in weapons if item.is_equipped]
            if len(equipped) == 1:
                selected = equipped[0]
            else:
                raise ValueError("attack_name is required when a character has multiple available weapon attacks")

        return self._character_weapon_attack_profile(character, selected)

    @staticmethod
    def _solo_level_one_party(state: GameState) -> List[Character]:
        party = [character for character in state.characters.values() if character.hp_max > 0]
        if len(party) == 1 and int(party[0].level or 1) <= 1:
            return party
        return []

    @staticmethod
    def _challenge_rating_value(value: str) -> float:
        normalized = str(value or "0").strip()
        if "/" in normalized:
            numerator, denominator = normalized.split("/", 1)
            try:
                return float(numerator) / float(denominator)
            except (TypeError, ValueError, ZeroDivisionError):
                return 99.0
        try:
            return float(normalized)
        except (TypeError, ValueError):
            return 99.0

    @staticmethod
    def _damage_expression_bounds(expression: str) -> Optional[tuple[float, int]]:
        normalized = str(expression or "").lower().replace(" ", "")
        match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", normalized)
        if not match:
            return None
        count = int(match.group(1))
        sides = int(match.group(2))
        modifier = int(match.group(3) or 0)
        return count * (sides + 1) / 2 + modifier, count * sides + modifier

    def solo_level_one_encounter_error(
        self,
        state: GameState,
        enemy_names: List[str],
        enemy_hp: int,
        enemy_ac: int,
    ) -> str:
        if not self._solo_level_one_party(state):
            return ""
        if len([name for name in enemy_names if str(name or "").strip()]) > 1:
            return "A solo level-1 party cannot start against multiple new enemies without explicit balancing support."
        if int(enemy_hp or 0) > 15 or int(enemy_ac or 0) > 14:
            return "For a solo level-1 party, a new encounter enemy must use at most 15 HP and AC 14."
        return ""

    def solo_level_one_monster_template_error(
        self,
        state: GameState,
        challenge_rating: str,
        hp_max: int,
        ac: int,
        actions: Optional[List[str]] = None,
    ) -> str:
        party = self._solo_level_one_party(state)
        if not party:
            return ""
        if self._challenge_rating_value(challenge_rating) > 0.5:
            return "A game-authored monster facing one level-1 character must be CR 1/2 or lower."
        encounter_error = self.solo_level_one_encounter_error(state, ["monster"], hp_max, ac)
        if encounter_error:
            return encounter_error
        for action in actions or []:
            text = str(action or "")
            bonus_match = re.search(r"([+-]\d+)\s*(?:命中|to hit)", text, flags=re.IGNORECASE)
            if bonus_match and int(bonus_match.group(1)) > 4:
                return "A solo level-1 monster attack bonus cannot exceed +4."
            damage_match = re.search(r"(\d+d\d+(?:[+-]\d+)?)", text, flags=re.IGNORECASE)
            if damage_match:
                attack_error = self.solo_level_one_npc_attack_error(
                    state,
                    int(bonus_match.group(1)) if bonus_match else 0,
                    damage_match.group(1),
                )
                if attack_error:
                    return attack_error
        return ""

    def solo_level_one_npc_attack_error(
        self,
        state: GameState,
        attack_bonus: int,
        damage_expression: str,
    ) -> str:
        party = self._solo_level_one_party(state)
        if not party:
            return ""
        if int(attack_bonus or 0) > 4:
            return "A solo level-1 enemy attack bonus cannot exceed +4."
        damage_bounds = self._damage_expression_bounds(damage_expression)
        if not damage_bounds:
            return "A solo level-1 enemy attack requires a bounded dice damage expression."
        _, maximum_damage = damage_bounds
        if maximum_damage >= min(character.hp_max for character in party):
            return (
                "A routine enemy attack against a solo level-1 party cannot deal enough normal maximum damage "
                "to drop the character from full HP in one hit."
            )
        return ""

    def _format_damage_expression(self, damage_die: str, ability_modifier: int) -> str:
        if ability_modifier > 0:
            return f"{damage_die}+{ability_modifier}"
        if ability_modifier < 0:
            return f"{damage_die}{ability_modifier}"
        return damage_die

    def _canonicalize_inventory(self, character: Character) -> None:
        normalized_inventory: List[InventoryItem] = []
        for item in character.inventory:
            catalog_item = get_shop_item_by_name(item.name)
            if catalog_item:
                if not item.type or item.type == "misc":
                    item.type = catalog_item.get("type", item.type)
                if not item.notes and catalog_item.get("notes"):
                    item.notes = catalog_item["notes"]
                if not item.tags:
                    item.tags = list(catalog_item.get("tags", []))
                if not item.properties:
                    item.properties = list(catalog_item.get("properties", []))

                if item.type == "weapon":
                    item.damage_type = catalog_item.get("damage_type", item.damage_type)
                    damage_die = catalog_item.get("damage_die")
                    if damage_die:
                        item.damage_expression = self._format_damage_expression(
                            damage_die,
                            self._weapon_ability_modifier(character, catalog_item),
                        )
                if item.type == "armor" and int(item.armor_class_bonus or 0) <= 0:
                    item.armor_class_bonus = int(catalog_item.get("armor_class_bonus", 0) or 0)
                if not item.is_equipped and catalog_item.get("auto_equip"):
                    item.is_equipped = True

            normalized_inventory.append(item)

        character.inventory = normalized_inventory

    def _calculate_starting_ac(self, character: Character) -> int:
        dexterity_modifier = self.get_ability_modifier(character, "dexterity")
        shield_bonus = 0
        best_armor_ac: Optional[int] = None

        for item in character.inventory:
            if item.type != "armor" or not item.is_equipped:
                continue

            catalog_item = get_shop_item_by_name(item.name) or {}
            armor_kind = catalog_item.get("armor_kind", "")
            armor_bonus = int(item.armor_class_bonus or catalog_item.get("armor_class_bonus", 0) or 0)

            if armor_kind == "shield":
                shield_bonus += armor_bonus
                continue

            if armor_kind == "heavy":
                armor_ac = 10 + armor_bonus
            elif armor_kind == "medium":
                armor_ac = 10 + armor_bonus + min(2, dexterity_modifier)
            else:
                armor_ac = 10 + armor_bonus + dexterity_modifier

            best_armor_ac = armor_ac if best_armor_ac is None else max(best_armor_ac, armor_ac)

        base_ac = best_armor_ac if best_armor_ac is not None else 10 + dexterity_modifier
        return base_ac + shield_bonus

    def _materialize_builder_equipment(self, character: Character, class_def: Optional[Dict[str, Any]]) -> Dict[str, int]:
        equipment_mode = character.equipment_mode or "starter_package"
        inventory: List[InventoryItem] = []
        spent_gp = 0
        budget_gp = 0

        if equipment_mode == "custom_purchase":
            budget_gp = self.get_custom_purchase_budget_gp(class_def)
            for selection in character.custom_purchase_items:
                shop_item = get_shop_item(selection.item_id)
                if not shop_item:
                    continue
                quantity = max(1, int(selection.quantity or 1))
                spent_gp += int(shop_item.get("cost_gp", 0)) * quantity
                inventory.append(self._build_inventory_item_from_shop_entry(shop_item, quantity))
        else:
            starter_option = self.get_starter_option(class_def, character.starter_option_id)
            if starter_option:
                inventory = [
                    InventoryItem(**item_def)
                    for item_def in self.resolve_starter_option_items(starter_option, character.starter_choice_ids)
                ]
                budget_gp = int(starter_option.get("gold_gp", 0))

        pending_item = self._resolve_pending_custom_item(character.custom_pending_item)
        if pending_item:
            spent_gp += int(character.custom_pending_item.reserved_cost_gp or 0)
            inventory.append(pending_item)

        character.inventory = inventory
        character.gold_gp = max(0, budget_gp - spent_gp)
        self._canonicalize_inventory(character)
        return {"budget_gp": budget_gp, "spent_gp": spent_gp}

    # Builder validation keeps save data coherent before it is persisted.
    def validate_character(self, character: Character) -> List[str]:
        errors: List[str] = []
        if not str(character.name or "").strip():
            errors.append("Character name is required")

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

        stat_values = self.get_stat_values(character)
        generation_method = str(character.ability_generation_method or "point_buy").strip().lower()
        if generation_method == "point_buy":
            point_buy = self.get_point_buy_config()
            for stat_name, stat_value in stat_values.items():
                if stat_value < point_buy["minimum"] or stat_value > point_buy["maximum"]:
                    errors.append(
                        f"Ability score {stat_name}={stat_value} is outside the supported range "
                        f"{point_buy['minimum']}-{point_buy['maximum']}"
                    )
            point_buy_spend = self.get_point_buy_spend(character)
            if point_buy_spend is None:
                errors.append("Ability scores do not match the configured point-buy table")
            elif point_buy_spend > point_buy["budget"]:
                errors.append(f"Ability score spend {point_buy_spend} exceeds the point-buy budget {point_buy['budget']}")
        elif generation_method == "standard_array":
            standard_array = sorted(
                int(value)
                for value in self.data.get("ability_generation", {}).get("standard_array", [])
            )
            if sorted(stat_values.values()) != standard_array:
                errors.append("Ability scores do not match the configured standard array")
            if character.ability_rolls:
                errors.append("Standard-array characters must not include rolled ability records")
        elif generation_method == "rolled":
            roll_errors: List[str] = []
            if len(character.ability_rolls) != 6:
                roll_errors.append("Rolled ability generation requires exactly six recorded rolls")
            else:
                roll_totals: List[int] = []
                for index, roll in enumerate(character.ability_rolls, start=1):
                    dice = [int(value) for value in roll.dice]
                    if len(dice) != 4 or any(value < 1 or value > 6 for value in dice):
                        roll_errors.append(f"Ability roll {index} must contain four d6 results")
                        continue
                    dropped_index = int(roll.dropped_index)
                    if dropped_index < 0 or dropped_index >= len(dice) or dice[dropped_index] != min(dice):
                        roll_errors.append(f"Ability roll {index} must drop one of its lowest dice")
                        continue
                    expected_total = sum(dice) - min(dice)
                    if int(roll.total) != expected_total:
                        roll_errors.append(f"Ability roll {index} total does not match its dice")
                        continue
                    roll_totals.append(expected_total)
                if not roll_errors and sorted(roll_totals) != sorted(stat_values.values()):
                    roll_errors.append("Assigned ability scores do not match the recorded rolled pool")
            errors.extend(roll_errors)
        else:
            errors.append(f"Unsupported ability generation method: {character.ability_generation_method}")

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
            skill_target = int(class_def.get("skills_to_choose", 0))
            if len(class_selected_skills) > skill_target:
                errors.append(
                    f"Selected {len(class_selected_skills)} class skills but only {class_def.get('skills_to_choose', 0)} are allowed"
                )
            elif character.level == 1 and len(class_selected_skills) != skill_target:
                errors.append(
                    f"Selected {len(class_selected_skills)} class skills but level 1 requires exactly {skill_target}"
                )

            if character.level == 1:
                expected_hp = self.get_expected_level_one_hp(character, class_def)
                if int(character.hp_max) != expected_hp or int(character.hp_current) != expected_hp:
                    errors.append(
                        f"Level 1 HP must equal {expected_hp} for {character.class_name} with the chosen Constitution"
                    )

            equipment_mode = character.equipment_mode or "starter_package"
            if equipment_mode not in {"starter_package", "custom_purchase"}:
                errors.append(f"Unknown equipment mode: {equipment_mode}")

            starter_options = self.get_starter_options(class_def)
            if equipment_mode == "starter_package":
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
                if character.custom_purchase_items:
                    errors.append("Custom purchase items require custom_purchase equipment mode")
                pending_name = str(character.custom_pending_item.name or "").strip()
                pending_cost = int(character.custom_pending_item.reserved_cost_gp or 0)
                starter_gold = int(starter_option.get("gold_gp", 0)) if starter_option else 0
                if pending_name and pending_cost > starter_gold:
                    errors.append(
                        f"Custom pending equipment reserved cost {pending_cost} exceeds remaining starter gold {starter_gold}"
                    )
            elif equipment_mode == "custom_purchase":
                custom_budget = self.get_custom_purchase_budget_gp(class_def)
                if custom_budget <= 0:
                    errors.append(f"No custom purchase budget is configured for class {character.class_name}")

                total_spent = 0
                for selection in character.custom_purchase_items:
                    if int(selection.quantity or 0) <= 0:
                        errors.append(f"Custom purchase item {selection.item_id} must have a positive quantity")
                        continue
                    shop_item = get_shop_item(selection.item_id)
                    if not shop_item:
                        errors.append(f"Unknown custom purchase item: {selection.item_id}")
                        continue
                    total_spent += int(shop_item.get("cost_gp", 0)) * int(selection.quantity)

                pending_name = str(character.custom_pending_item.name or "").strip()
                pending_cost = int(character.custom_pending_item.reserved_cost_gp or 0)
                if pending_name:
                    total_spent += pending_cost
                if total_spent > custom_budget:
                    errors.append(f"Custom purchase spend {total_spent} exceeds budget {custom_budget}")

            pending_name = str(character.custom_pending_item.name or "").strip()
            pending_quantity = int(character.custom_pending_item.quantity or 0)
            pending_cost = int(character.custom_pending_item.reserved_cost_gp or 0)
            pending_notes = str(character.custom_pending_item.notes or "").strip()
            if pending_name:
                if pending_quantity <= 0:
                    errors.append("Custom pending equipment must have a positive quantity")
                if pending_cost < 0:
                    errors.append("Custom pending equipment reserved cost cannot be negative")
            elif pending_quantity not in (0, 1) or pending_cost != 0 or pending_notes:
                errors.append("Custom pending equipment must include a name before it can be saved")

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

        character.spells.cantrips = self.library.normalize_spell_names(character.spells.cantrips)
        character.spells.prepared = self.library.normalize_spell_names(character.spells.prepared)

        if class_def and not character.resources:
            resources: Dict[str, ResourcePool] = {}
            for resource_name, resource_def in class_def.get("resources", {}).items():
                resources[resource_name] = ResourcePool(**resource_def)
            character.resources = resources

        starter_option = self.get_starter_option(class_def, character.starter_option_id)
        if starter_option and not character.starter_option_id:
            character.starter_option_id = starter_option.get("id", "")

        if class_def:
            self._materialize_builder_equipment(character, class_def)
        elif starter_option and not character.inventory:
            resolved_items = self.resolve_starter_option_items(starter_option, character.starter_choice_ids)
            character.inventory = [InventoryItem(**item_def) for item_def in resolved_items]
            self._canonicalize_inventory(character)

        if not class_def and starter_option and character.gold_gp <= 0:
            character.gold_gp = int(starter_option.get("gold_gp", 0))

        if class_def and not character.spells.slots and class_def.get("starting_spell_slots"):
            character.spells.slots = {
                level: SpellSlot(total=slot_total, used=0)
                for level, slot_total in class_def["starting_spell_slots"].items()
            }

        if class_def and character.level == 1:
            character.hp_max = self.get_expected_level_one_hp(character, class_def)
            character.hp_current = character.hp_max
        elif class_def and character.hp_max <= 0:
            hit_die = int(class_def.get("hit_die", 8))
            character.hp_max = max(1, hit_die + self.get_ability_modifier(character, "constitution"))
            character.hp_current = character.hp_max

        if class_def:
            character.ac = self._calculate_starting_ac(character)

        return character

    def can_cast_spell(
        self,
        character: Character,
        spell_name: str,
        slot_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Spell legality is resolved locally so the DM never fabricates slot usage.
        character.spells.cantrips = self.library.normalize_spell_names(character.spells.cantrips)
        character.spells.prepared = self.library.normalize_spell_names(character.spells.prepared)

        details = self.library.get_spell_details(spell_name)
        if not details:
            return {"ok": False, "error": f"Unknown spell: {spell_name}"}

        canonical_name = str(details.get("name") or spell_name).strip()
        spell_level = int(details.get("level", 0))
        if spell_level == 0:
            if canonical_name not in self.library.normalize_spell_names(character.spells.cantrips):
                return {"ok": False, "error": f"Cantrip not known: {canonical_name}"}
            return {"ok": True, "spell": details, "spell_name": canonical_name, "resolved_slot_level": 0}

        if canonical_name not in self.library.normalize_spell_names(character.spells.prepared):
            return {"ok": False, "error": f"Spell not prepared or known: {canonical_name}"}

        resolved_slot = spell_level if slot_level is None else int(slot_level)
        if resolved_slot < spell_level:
            return {"ok": False, "error": f"Slot level {resolved_slot} is too low for {canonical_name}"}

        slot_state = character.spells.slots.get(str(resolved_slot))
        if not slot_state or slot_state.total - slot_state.used <= 0:
            return {"ok": False, "error": f"No available spell slot at level {resolved_slot}"}

        return {"ok": True, "spell": details, "spell_name": canonical_name, "resolved_slot_level": resolved_slot}

    @staticmethod
    def spell_action_cost(spell_details: Dict[str, Any]) -> str:
        casting_time = str(spell_details.get("castingTime") or spell_details.get("casting_time") or "").casefold()
        if "附赠" in casting_time or "bonus" in casting_time:
            return "bonus_action"
        if "反应" in casting_time or "reaction" in casting_time:
            return "reaction"
        return "action"

    def consume_spell_slot(self, character: Character, slot_level: int) -> None:
        if slot_level <= 0:
            return
        slot = character.spells.slots.get(str(slot_level))
        if slot:
            slot.used += 1
