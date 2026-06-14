"""Rule catalog and validation helpers for level-1 character creation and play."""

import json
import os
from copy import deepcopy
from typing import Any, Dict, List, Optional

from library import Library
from models import Character, InventoryItem, PendingCustomEquipment, ResourcePool, SpellSlot
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
        if {"Ranged", "Thrown", "Finesse"} & properties:
            return max(strength_mod, dexterity_mod)
        return strength_mod

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

        point_buy = self.get_point_buy_config()
        for stat_name, stat_value in self.get_stat_values(character).items():
            if stat_value < point_buy["minimum"] or stat_value > point_buy["maximum"]:
                errors.append(
                    f"Ability score {stat_name}={stat_value} is outside the supported range {point_buy['minimum']}-{point_buy['maximum']}"
                )
        point_buy_spend = self.get_point_buy_spend(character)
        if point_buy_spend is None:
            errors.append("Ability scores do not match the configured point-buy table")
        elif point_buy_spend > point_buy["budget"]:
            errors.append(f"Ability score spend {point_buy_spend} exceeds the point-buy budget {point_buy['budget']}")

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
