"""Starter-equipment purchase catalog used by the character builder."""

from copy import deepcopy
from typing import Any, Dict, List, Optional


STARTER_SHOP_ITEMS: List[Dict[str, Any]] = [
    {"id": "arrow_bundle", "name": "Arrow", "type": "ammo", "cost_gp": 1, "bundle_size": 20, "notes": "20 arrows per purchase."},
    {"id": "arcane_focus_crystal", "name": "Arcane Focus (Crystal)", "type": "focus", "cost_gp": 10},
    {"id": "arcane_focus_orb", "name": "Arcane Focus (Orb)", "type": "focus", "cost_gp": 20},
    {"id": "book_occult_lore", "name": "Book (Occult Lore)", "type": "book", "cost_gp": 25},
    {"id": "burglars_pack", "name": "Burglar's Pack", "type": "pack", "cost_gp": 16},
    {"id": "calligraphers_supplies", "name": "Calligrapher's Supplies", "type": "tool", "cost_gp": 10},
    {"id": "chain_mail", "name": "Chain Mail", "type": "armor", "cost_gp": 75, "armor_class_bonus": 6, "armor_kind": "heavy", "auto_equip": True},
    {"id": "chain_shirt", "name": "Chain Shirt", "type": "armor", "cost_gp": 50, "armor_class_bonus": 3, "armor_kind": "medium", "auto_equip": True},
    {"id": "dagger", "name": "Dagger", "type": "weapon", "cost_gp": 2, "damage_die": "1d4", "damage_type": "piercing", "properties": ["Finesse", "Light", "Thrown"]},
    {"id": "druidic_focus_sprig", "name": "Druidic Focus (Sprig of Mistletoe)", "type": "focus", "cost_gp": 1},
    {"id": "druidic_focus_totem", "name": "Druidic Focus (Totem)", "type": "focus", "cost_gp": 1},
    {"id": "druidic_focus_wooden_staff", "name": "Druidic Focus (Wooden Staff)", "type": "focus", "cost_gp": 5},
    {"id": "druidic_focus_yew_wand", "name": "Druidic Focus (Yew Wand)", "type": "focus", "cost_gp": 10},
    {"id": "drum", "name": "Drum", "type": "tool", "cost_gp": 6},
    {"id": "dungeoneers_pack", "name": "Dungeoneer's Pack", "type": "pack", "cost_gp": 12},
    {"id": "entertainers_pack", "name": "Entertainer's Pack", "type": "pack", "cost_gp": 40},
    {"id": "explorers_pack", "name": "Explorer's Pack", "type": "pack", "cost_gp": 10},
    {"id": "flail", "name": "Flail", "type": "weapon", "cost_gp": 10, "damage_die": "1d8", "damage_type": "bludgeoning"},
    {"id": "flute", "name": "Flute", "type": "tool", "cost_gp": 2},
    {"id": "greatsword", "name": "Greatsword", "type": "weapon", "cost_gp": 50, "damage_die": "2d6", "damage_type": "slashing", "properties": ["Heavy", "Two-Handed"]},
    {"id": "herbalism_kit", "name": "Herbalism Kit", "type": "tool", "cost_gp": 5},
    {"id": "holy_symbol_amulet", "name": "Holy Symbol (Amulet)", "type": "focus", "cost_gp": 5},
    {"id": "holy_symbol_emblem", "name": "Holy Symbol (Emblem)", "type": "focus", "cost_gp": 5},
    {"id": "holy_symbol_reliquary", "name": "Holy Symbol (Reliquary)", "type": "focus", "cost_gp": 5},
    {"id": "javelin", "name": "Javelin", "type": "weapon", "cost_gp": 1, "damage_die": "1d6", "damage_type": "piercing", "properties": ["Thrown"]},
    {"id": "leather_armor", "name": "Leather Armor", "type": "armor", "cost_gp": 10, "armor_class_bonus": 1, "armor_kind": "light", "auto_equip": True},
    {"id": "longbow", "name": "Longbow", "type": "weapon", "cost_gp": 50, "damage_die": "1d8", "damage_type": "piercing", "properties": ["Ammunition", "Heavy", "Ranged", "Two-Handed"]},
    {"id": "longsword", "name": "Longsword", "type": "weapon", "cost_gp": 15, "damage_die": "1d8", "damage_type": "slashing", "properties": ["Versatile"]},
    {"id": "lute", "name": "Lute", "type": "tool", "cost_gp": 35},
    {"id": "lyre", "name": "Lyre", "type": "tool", "cost_gp": 30},
    {"id": "mace", "name": "Mace", "type": "weapon", "cost_gp": 5, "damage_die": "1d6", "damage_type": "bludgeoning"},
    {"id": "potters_tools", "name": "Potter's Tools", "type": "tool", "cost_gp": 10},
    {"id": "priests_pack", "name": "Priest's Pack", "type": "pack", "cost_gp": 19},
    {"id": "quarterstaff", "name": "Quarterstaff", "type": "weapon", "cost_gp": 1, "damage_die": "1d6", "damage_type": "bludgeoning", "properties": ["Versatile"], "notes": "Can double as a focus when the class rules permit."},
    {"id": "quiver", "name": "Quiver", "type": "gear", "cost_gp": 1},
    {"id": "robes", "name": "Robes", "type": "clothing", "cost_gp": 1},
    {"id": "scholars_pack", "name": "Scholar's Pack", "type": "pack", "cost_gp": 40},
    {"id": "scimitar", "name": "Scimitar", "type": "weapon", "cost_gp": 25, "damage_die": "1d6", "damage_type": "slashing", "properties": ["Finesse", "Light"]},
    {"id": "shield", "name": "Shield", "type": "armor", "cost_gp": 10, "armor_class_bonus": 2, "armor_kind": "shield", "auto_equip": True},
    {"id": "shortbow", "name": "Shortbow", "type": "weapon", "cost_gp": 25, "damage_die": "1d6", "damage_type": "piercing", "properties": ["Ammunition", "Ranged", "Two-Handed"]},
    {"id": "shortsword", "name": "Shortsword", "type": "weapon", "cost_gp": 10, "damage_die": "1d6", "damage_type": "piercing", "properties": ["Finesse", "Light"]},
    {"id": "sickle", "name": "Sickle", "type": "weapon", "cost_gp": 1, "damage_die": "1d4", "damage_type": "slashing", "properties": ["Light"]},
    {"id": "spear", "name": "Spear", "type": "weapon", "cost_gp": 1, "damage_die": "1d6", "damage_type": "piercing", "properties": ["Thrown", "Versatile"]},
    {"id": "spellbook", "name": "Spellbook", "type": "book", "cost_gp": 50},
    {"id": "studded_leather_armor", "name": "Studded Leather Armor", "type": "armor", "cost_gp": 45, "armor_class_bonus": 2, "armor_kind": "light", "auto_equip": True},
    {"id": "thieves_tools", "name": "Thieves' Tools", "type": "tool", "cost_gp": 25},
    {"id": "viol", "name": "Viol", "type": "tool", "cost_gp": 30},
    {"id": "woodcarvers_tools", "name": "Woodcarver's Tools", "type": "tool", "cost_gp": 1},
]

_SHOP_BY_ID = {item["id"]: item for item in STARTER_SHOP_ITEMS}
_SHOP_BY_NAME = {item["name"]: item for item in STARTER_SHOP_ITEMS}


def get_shop_catalog() -> List[Dict[str, Any]]:
    return deepcopy(STARTER_SHOP_ITEMS)


def get_shop_item(item_id: str) -> Optional[Dict[str, Any]]:
    item = _SHOP_BY_ID.get(item_id)
    return deepcopy(item) if item else None


def get_shop_item_by_name(name: str) -> Optional[Dict[str, Any]]:
    item = _SHOP_BY_NAME.get(name)
    return deepcopy(item) if item else None
