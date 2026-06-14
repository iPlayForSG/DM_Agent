"""Core state mutation layer for encounters, damage, rewards, and campaign progress."""

import random
import re
from typing import Any, Dict, List, Optional, Tuple

from models import (
    ChapterRecord,
    Character,
    Combatant,
    EvidenceRecord,
    EncounterState,
    GameState,
    InventoryItem,
    MonsterTemplate,
    SearchRecord,
    random_id,
    stable_id,
)
from library import Library
from rules_catalog import ABILITY_ALIAS, SKILL_TO_ABILITY, proficiency_bonus_for_level


class DiceRoller:
    @staticmethod
    def roll(expression: str) -> Tuple[int, str]:
        expression = expression.lower().replace(" ", "")
        match = re.fullmatch(r"(\d+)d(\d+)([\+\-]\d+)?", expression)
        if not match:
            try:
                value = int(expression)
                return value, str(value)
            except ValueError:
                return 0, "Invalid Dice"

        count = int(match.group(1))
        sides = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + modifier

        detail = f"[{','.join(map(str, rolls))}]"
        if modifier:
            detail += f"{modifier:+d}"
        return total, detail

    @staticmethod
    def roll_d20(modifier: int = 0) -> Tuple[int, int, str]:
        natural = random.randint(1, 20)
        total = natural + modifier
        detail = f"[{natural}]"
        if modifier:
            detail += f"{modifier:+d}"
        return natural, total, detail


class GameLogic:
    _library = Library()
    FEATURE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
        "second wind": {
            "name": "Second Wind",
            "action_cost": "bonus_action",
            "resource_name": "Second Wind",
            "resource_cost": 1,
        },
        "二次呼吸": {
            "name": "Second Wind",
            "action_cost": "bonus_action",
            "resource_name": "Second Wind",
            "resource_cost": 1,
        },
        "wild shape": {
            "name": "Wild Shape",
            "action_cost": "bonus_action",
            "resource_name": "Wild Shape",
            "resource_cost": 1,
        },
        "野性变身": {
            "name": "Wild Shape",
            "action_cost": "bonus_action",
            "resource_name": "Wild Shape",
            "resource_cost": 1,
        },
        "action surge": {
            "name": "Action Surge",
            "action_cost": "free",
            "resource_name": "Action Surge",
            "resource_cost": 1,
        },
        "动作激涌": {
            "name": "Action Surge",
            "action_cost": "free",
            "resource_name": "Action Surge",
            "resource_cost": 1,
        },
    }

    def __init__(self, state: GameState):
        self.state = state

    # Patch helpers keep HTTP/API deltas shallow while the in-memory state stays authoritative.
    @staticmethod
    def _merge_patches(*patches: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for patch in patches:
            for key, value in (patch or {}).items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = GameLogic._merge_patches(merged[key], value)
                else:
                    merged[key] = value
        return merged

    @staticmethod
    def _normalize_defeat_state(defeat_state: str) -> str:
        normalized = (defeat_state or "active").strip().lower()
        allowed = {"active", "unconscious", "captured", "dead"}
        if normalized not in allowed:
            raise ValueError(f"Unsupported defeat state: {defeat_state}")
        return normalized

    @staticmethod
    def _defeat_statuses() -> List[str]:
        return ["Unconscious", "Captured", "Dead"]

    @classmethod
    def _status_for_defeat_state(cls, defeat_state: str) -> str:
        mapping = {
            "unconscious": "Unconscious",
            "captured": "Captured",
            "dead": "Dead",
        }
        return mapping.get(cls._normalize_defeat_state(defeat_state), "")

    def _apply_defeat_state(self, target: Any, defeat_state: str) -> None:
        normalized = self._normalize_defeat_state(defeat_state)
        target.defeat_state = normalized
        active_statuses = [status for status in target.status_effects if status not in self._defeat_statuses()]
        marker = self._status_for_defeat_state(normalized)
        if marker:
            active_statuses.append(marker)
        target.status_effects = active_statuses

    def _default_zero_hp_state(self, identifier: str) -> str:
        character = self.get_character(identifier)
        if character:
            return "unconscious"
        combatant = self.get_combatant(identifier)
        if combatant and combatant.linked_character_id:
            return "unconscious"
        return "dead"

    def _concentration_character(self, identifier: str) -> Optional[Character]:
        character = self.get_character(identifier)
        if character:
            return character
        combatant = self.get_combatant(identifier)
        if combatant and combatant.linked_character_id:
            return self.state.characters.get(combatant.linked_character_id)
        return None

    @staticmethod
    def _concentration_dc(damage_amount: int) -> int:
        return min(30, max(10, int(damage_amount) // 2))

    @staticmethod
    def _ability_modifier_from_stats(stats: Any, ability_name: str) -> int:
        attr = ABILITY_ALIAS.get(ability_name, ability_name).lower()
        return (getattr(stats, attr, 10) - 10) // 2

    @classmethod
    def _character_skill_modifiers(cls, character: Character) -> Dict[str, int]:
        proficiency = proficiency_bonus_for_level(character.level)
        modifiers: Dict[str, int] = {}
        for skill_name, rank in character.skill_proficiencies.items():
            rank_value = int(rank)
            if rank_value <= 0:
                continue
            ability = SKILL_TO_ABILITY.get(skill_name, "wisdom")
            modifiers[skill_name] = cls._ability_modifier_from_stats(character.stats, ability) + proficiency * rank_value
        return modifiers

    @classmethod
    def _character_save_modifiers(cls, character: Character) -> Dict[str, int]:
        proficiency = proficiency_bonus_for_level(character.level)
        modifiers: Dict[str, int] = {}
        for save_name, is_proficient in character.save_proficiencies.items():
            if not is_proficient:
                continue
            ability = ABILITY_ALIAS.get(save_name, save_name).lower()
            modifiers[ability] = cls._ability_modifier_from_stats(character.stats, ability) + proficiency
        return modifiers

    @classmethod
    def _character_save_modifier(cls, character: Character, save_name: str) -> int:
        ability = ABILITY_ALIAS.get(save_name, save_name).lower()
        modifier = cls._ability_modifier_from_stats(character.stats, ability)
        proficient = any(
            bool(value) and ABILITY_ALIAS.get(str(key), str(key)).lower() == ability
            for key, value in character.save_proficiencies.items()
        )
        if proficient:
            modifier += proficiency_bonus_for_level(character.level)
        return modifier

    def resolve_concentration_after_damage(self, identifier: str, damage_amount: int) -> Optional[Dict[str, Any]]:
        if damage_amount <= 0:
            return None

        character = self._concentration_character(identifier)
        if not character or not character.concentration_spell:
            return None

        previous_spell = character.concentration_spell
        previous_level = character.concentration_spell_level
        dc = self._concentration_dc(damage_amount)
        save_result: Optional[Dict[str, Any]] = None
        reason = "damage"
        broken = character.defeat_state != "active" or character.hp_current <= 0

        if broken:
            reason = "incapacitated_or_defeated"
        else:
            modifier = self._character_save_modifier(character, "constitution")
            save_result = self.roll_saving_throw(
                target_ref=character.character_id,
                save_name="constitution",
                modifier=modifier,
                dc=dc,
            )
            broken = not bool(save_result["success"])
            reason = "failed_save" if broken else "successful_save"

        patch: Dict[str, Any] = {}
        if broken:
            character.concentration_spell = ""
            character.concentration_spell_level = 0
            patch = {
                "characters": {
                    character.character_id: {
                        "concentration_spell": character.concentration_spell,
                        "concentration_spell_level": character.concentration_spell_level,
                    }
                }
            }

        return {
            "character_id": character.character_id,
            "character_name": character.name,
            "damage_amount": int(damage_amount),
            "dc": dc,
            "previous_spell": previous_spell,
            "previous_spell_level": previous_level,
            "current_spell": character.concentration_spell,
            "broken": broken,
            "reason": reason,
            "save": save_result,
            "patch": patch,
        }

    def _resolve_evidence_ref(
        self,
        evidence_ref: str,
        holder_character_id: str = "",
        location: str = "",
    ) -> str:
        normalized = (evidence_ref or "").strip()
        if not normalized:
            return ""

        normalized_lower = normalized.lower()
        stable_candidate = stable_id("evi", normalized)
        for record in self.state.evidence_records:
            if record.evidence_id == normalized:
                return record.evidence_id
            if record.evidence_id == stable_candidate:
                return record.evidence_id
            if record.title == normalized:
                return record.evidence_id
            if record.title.lower() == normalized_lower:
                return record.evidence_id

        candidates = self.state.evidence_records
        if holder_character_id:
            candidates = [
                record for record in candidates if record.holder_character_id == holder_character_id
            ] or candidates
        if location:
            location_lower = location.lower()
            candidates = [
                record
                for record in candidates
                if record.location.lower() == location_lower or record.source_ref.lower() == location_lower
            ] or candidates
        if len(candidates) == 1:
            return candidates[0].evidence_id
        return normalized

    def _start_turn_order_if_ready(self) -> bool:
        encounter = self.state.encounter
        if not encounter or encounter.turn_order_started:
            return False
        if not encounter.initiative_order:
            return False
        for combatant_id in encounter.initiative_order:
            combatant = encounter.combatants.get(combatant_id)
            if not combatant or combatant.initiative is None:
                return False
        eligible = [
            combatant_id
            for combatant_id in encounter.initiative_order
            if self._combatant_can_take_turn(encounter.combatants.get(combatant_id))
        ]
        encounter.current_combatant_id = eligible[0] if eligible else None
        encounter.turn_order_started = True
        self._reset_turn_action_state(encounter)
        return True

    @staticmethod
    def _combatant_can_take_turn(combatant: Optional[Combatant]) -> bool:
        if not combatant:
            return False
        if combatant.hp_current <= 0:
            return False
        return combatant.defeat_state == "active"

    # Entity lookup helpers accept either ids or display names.
    def get_character(self, identifier: str) -> Optional[Character]:
        if identifier in self.state.characters:
            return self.state.characters[identifier]

        for character in self.state.characters.values():
            if character.name == identifier:
                return character
        return None

    def get_combatant(self, identifier: str) -> Optional[Combatant]:
        if not self.state.encounter:
            return None

        if identifier in self.state.encounter.combatants:
            return self.state.encounter.combatants[identifier]

        for combatant in self.state.encounter.combatants.values():
            if combatant.name == identifier or combatant.linked_character_id == identifier:
                return combatant
        return None

    def get_actor_name(self, identifier: str) -> str:
        character = self.get_character(identifier)
        if character:
            return character.name
        combatant = self.get_combatant(identifier)
        if combatant:
            return combatant.name
        return identifier

    def get_current_combatant(self) -> Optional[Combatant]:
        if not self.state.encounter or not self.state.encounter.active:
            return None
        return self.state.encounter.get_current_combatant()

    def is_current_actor(self, identifier: str) -> bool:
        current = self.get_current_combatant()
        if not current:
            return True

        allowed_refs = {
            current.combatant_id,
            current.name,
        }
        if current.linked_character_id:
            allowed_refs.add(current.linked_character_id)
            linked_character = self.state.characters.get(current.linked_character_id)
            if linked_character:
                allowed_refs.add(linked_character.name)

        return identifier in allowed_refs

    # Local action endpoints should only execute actor-driven actions for the current turn holder.
    def require_current_actor(self, identifier: str) -> Optional[Combatant]:
        current = self.get_current_combatant()
        if not current and self.state.encounter and self.state.encounter.active and not self.state.encounter.turn_order_started:
            self._start_turn_order_if_ready()
            current = self.get_current_combatant()
        if not current:
            return None
        if self.is_current_actor(identifier):
            return current
        raise ValueError(f"It is currently {current.name}'s turn, not {self.get_actor_name(identifier)}'s turn")

    @staticmethod
    def _turn_action_key(encounter: EncounterState) -> str:
        if not encounter.current_combatant_id:
            return ""
        return f"{encounter.round_number}:{encounter.current_combatant_id}"

    def _reset_turn_action_state(self, encounter: Optional[EncounterState] = None) -> Dict[str, Any]:
        encounter = encounter or self.state.encounter
        if not encounter:
            return {}
        turn_key = self._turn_action_key(encounter)
        encounter.turn_action_key = turn_key
        encounter.turn_action_used = False
        encounter.turn_action_tool = ""
        encounter.turn_bonus_action_key = turn_key
        encounter.turn_bonus_action_used = False
        encounter.turn_bonus_action_tool = ""
        encounter.turn_reaction_key = turn_key
        encounter.turn_reaction_used = False
        encounter.turn_reaction_tool = ""
        return {
            "encounter": {
                "turn_action_key": encounter.turn_action_key,
                "turn_action_used": encounter.turn_action_used,
                "turn_action_tool": encounter.turn_action_tool,
                "turn_bonus_action_key": encounter.turn_bonus_action_key,
                "turn_bonus_action_used": encounter.turn_bonus_action_used,
                "turn_bonus_action_tool": encounter.turn_bonus_action_tool,
                "turn_reaction_key": encounter.turn_reaction_key,
                "turn_reaction_used": encounter.turn_reaction_used,
                "turn_reaction_tool": encounter.turn_reaction_tool,
            }
        }

    @staticmethod
    def _normalize_turn_action_cost(action_cost: str) -> str:
        normalized = str(action_cost or "action").strip().lower()
        if normalized in {"bonus", "bonus-action", "bonus_action"}:
            return "bonus_action"
        if normalized == "reaction":
            return "reaction"
        return "action"

    @staticmethod
    def _turn_slot_fields(action_cost: str) -> Tuple[str, str, str]:
        normalized = GameLogic._normalize_turn_action_cost(action_cost)
        if normalized == "bonus_action":
            return "turn_bonus_action_key", "turn_bonus_action_used", "turn_bonus_action_tool"
        if normalized == "reaction":
            return "turn_reaction_key", "turn_reaction_used", "turn_reaction_tool"
        return "turn_action_key", "turn_action_used", "turn_action_tool"

    @staticmethod
    def _turn_slot_label(action_cost: str) -> str:
        normalized = GameLogic._normalize_turn_action_cost(action_cost)
        if normalized == "bonus_action":
            return "bonus action"
        if normalized == "reaction":
            return "reaction"
        return "action"

    def require_turn_slot_available(self, action_cost: str, action_name: str) -> None:
        encounter = self.state.encounter
        if not encounter or not encounter.active:
            return
        current = encounter.get_current_combatant()
        if not current:
            return
        turn_key = self._turn_action_key(encounter)
        key_field, used_field, tool_field = self._turn_slot_fields(action_cost)
        slot_key = getattr(encounter, key_field, "")
        if slot_key and slot_key != turn_key:
            self._reset_turn_action_state(encounter)
        if getattr(encounter, used_field, False) and getattr(encounter, key_field, "") == turn_key:
            used_tool = getattr(encounter, tool_field, "") or f"a {self._turn_slot_label(action_cost)}"
            raise ValueError(
                f"{current.name} has already used their {self._turn_slot_label(action_cost)} this turn: {used_tool}"
            )

    def require_turn_action_available(self, action_name: str) -> None:
        self.require_turn_slot_available("action", action_name)

    def mark_current_turn_slot_used(self, action_cost: str, action_name: str) -> Dict[str, Any]:
        encounter = self.state.encounter
        if not encounter or not encounter.active:
            return {}
        current = encounter.get_current_combatant()
        if not current:
            return {}
        self.require_turn_slot_available(action_cost, action_name)
        key_field, used_field, tool_field = self._turn_slot_fields(action_cost)
        setattr(encounter, key_field, self._turn_action_key(encounter))
        setattr(encounter, used_field, True)
        setattr(encounter, tool_field, action_name)
        return {
            "encounter": {
                key_field: getattr(encounter, key_field),
                used_field: getattr(encounter, used_field),
                tool_field: getattr(encounter, tool_field),
            }
        }

    def mark_current_action_used(self, action_name: str) -> Dict[str, Any]:
        return self.mark_current_turn_slot_used("action", action_name)

    def _ensure_encounter(self) -> EncounterState:
        # Reuse the current active encounter, otherwise build a fresh one around the party.
        if self.state.encounter and self.state.encounter.active:
            return self.state.encounter

        encounter = EncounterState(encounter_id=random_id("enc"), active=True, round_number=1)
        for character in self.state.characters.values():
            combatant = Combatant(
                combatant_id=stable_id("cmb", f"{character.character_id}-party"),
                name=character.name,
                side="party",
                linked_character_id=character.character_id,
                hp_current=character.hp_current,
                hp_max=character.hp_max,
                ac=character.ac,
                initiative_bonus=character.initiative_bonus,
                status_effects=list(character.status_effects),
                defeat_state=character.defeat_state,
                stats=character.stats.model_copy(deep=True),
                skills=self._character_skill_modifiers(character),
                saving_throws=self._character_save_modifiers(character),
            )
            encounter.combatants[combatant.combatant_id] = combatant

        encounter.initiative_order = list(encounter.combatants.keys())
        encounter.current_combatant_id = None
        encounter.turn_order_started = False
        self.state.encounter = encounter
        self.state.scene = "combat"
        self.state.campaign.phase = "combat"
        return encounter

    def _sync_combatant_from_character(self, character: Character) -> Optional[Combatant]:
        # Party combatants mirror character truth. Monster combatants are encounter-only.
        combatant = self.get_combatant(character.character_id)
        if not combatant:
            return None

        combatant.hp_current = character.hp_current
        combatant.hp_max = character.hp_max
        combatant.ac = character.ac
        combatant.initiative_bonus = character.initiative_bonus
        combatant.status_effects = list(character.status_effects)
        combatant.defeat_state = character.defeat_state
        combatant.stats = character.stats.model_copy(deep=True)
        combatant.skills = self._character_skill_modifiers(character)
        combatant.saving_throws = self._character_save_modifiers(character)
        return combatant

    def _sync_character_from_combatant(self, combatant: Combatant) -> Optional[Character]:
        if not combatant.linked_character_id:
            return None

        character = self.state.characters.get(combatant.linked_character_id)
        if not character:
            return None

        character.hp_current = combatant.hp_current
        character.hp_max = combatant.hp_max
        character.ac = combatant.ac
        character.initiative_bonus = combatant.initiative_bonus
        character.status_effects = list(combatant.status_effects)
        character.defeat_state = combatant.defeat_state
        return character

    def _refresh_initiative_order(self, reset_current: bool = False) -> None:
        # Sort descending initiative while preserving previous relative order on ties.
        encounter = self.state.encounter
        if not encounter:
            return

        previous_order = list(encounter.initiative_order)
        order_index = {combatant_id: index for index, combatant_id in enumerate(previous_order)}

        ordered = sorted(
            encounter.combatants.values(),
            key=lambda item: (
                item.initiative is None,
                -(item.initiative or -999),
                order_index.get(item.combatant_id, 9999),
                item.name,
            ),
        )
        encounter.initiative_order = [combatant.combatant_id for combatant in ordered]

        if reset_current:
            encounter.current_combatant_id = encounter.initiative_order[0] if encounter.initiative_order else None
            encounter.turn_order_started = bool(encounter.current_combatant_id)
        elif encounter.current_combatant_id not in encounter.initiative_order:
            encounter.current_combatant_id = encounter.initiative_order[0] if encounter.initiative_order else None

    def _build_monster_combatant(
        self,
        monster: MonsterTemplate,
        encounter_id: str,
        index: int,
        custom_name: str = "",
        hp_override: Optional[int] = None,
        side: str = "enemy",
    ) -> Combatant:
        label = custom_name.strip() or monster.name
        if index > 1 and not custom_name.strip():
            label = f"{monster.name} {index}"

        return Combatant(
            combatant_id=stable_id("cmb", f"{encounter_id}-{monster.monster_id}-{index}"),
            monster_template_id=monster.monster_id,
            name=label,
            side=side,
            hp_current=hp_override if hp_override is not None else monster.hp_max,
            hp_max=hp_override if hp_override is not None else monster.hp_max,
            ac=monster.ac,
            initiative_bonus=monster.initiative_bonus,
            stats=monster.stats.model_copy(deep=True),
            skills=dict(monster.skills),
            saving_throws=dict(monster.saving_throws),
        )

    # HP and status mutations keep character and encounter mirrors in sync.
    def update_target_hp(self, identifier: str, amount: int) -> Optional[Dict[str, Any]]:
        concentration_check: Optional[Dict[str, Any]] = None
        damage_amount = max(0, -int(amount))
        character = self.get_character(identifier)
        if character:
            character.hp_current = max(0, min(character.hp_current + amount, character.hp_max))
            if character.hp_current > 0 and character.defeat_state != "captured":
                self._apply_defeat_state(character, "active")
            elif character.hp_current <= 0 and amount < 0 and character.defeat_state == "active":
                self._apply_defeat_state(character, "unconscious")
            combatant = self._sync_combatant_from_character(character)
            patch: Dict[str, Any] = {
                "characters": {
                    character.character_id: {
                        "hp_current": character.hp_current,
                        "status_effects": character.status_effects,
                        "defeat_state": character.defeat_state,
                    }
                }
            }
            concentration_check = self.resolve_concentration_after_damage(character.character_id, damage_amount)
            if concentration_check and concentration_check.get("patch"):
                patch = self._merge_patches(patch, concentration_check["patch"])
            if combatant:
                patch["encounter"] = {
                    "combatants": {
                        combatant.combatant_id: {
                            "hp_current": combatant.hp_current,
                            "status_effects": combatant.status_effects,
                            "defeat_state": combatant.defeat_state,
                        }
                    }
                }
            return {
                "target_type": "character",
                "target": character,
                "patch": patch,
                "concentration_check": concentration_check,
            }

        combatant = self.get_combatant(identifier)
        if not combatant:
            return None

        combatant.hp_current = max(0, min(combatant.hp_current + amount, combatant.hp_max))
        if combatant.hp_current > 0 and combatant.defeat_state != "captured":
            self._apply_defeat_state(combatant, "active")
        elif combatant.hp_current <= 0 and amount < 0 and combatant.defeat_state == "active":
            self._apply_defeat_state(combatant, self._default_zero_hp_state(identifier))
        character = self._sync_character_from_combatant(combatant)
        patch = {
            "encounter": {
                "combatants": {
                    combatant.combatant_id: {
                        "hp_current": combatant.hp_current,
                        "status_effects": combatant.status_effects,
                        "defeat_state": combatant.defeat_state,
                    }
                }
            }
        }
        if character:
            patch["characters"] = {
                character.character_id: {
                    "hp_current": character.hp_current,
                    "status_effects": character.status_effects,
                    "defeat_state": character.defeat_state,
                }
            }
        concentration_ref = character.character_id if character else combatant.combatant_id
        concentration_check = self.resolve_concentration_after_damage(concentration_ref, damage_amount)
        if concentration_check and concentration_check.get("patch"):
            patch = self._merge_patches(patch, concentration_check["patch"])
        return {
            "target_type": "combatant",
            "target": combatant,
            "patch": patch,
            "concentration_check": concentration_check,
        }

    def set_defeat_state(self, identifier: str, defeat_state: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_defeat_state(defeat_state)
        character = self.get_character(identifier)
        if character:
            self._apply_defeat_state(character, normalized)
            combatant = self._sync_combatant_from_character(character)
            patch: Dict[str, Any] = {
                "characters": {
                    character.character_id: {
                        "status_effects": character.status_effects,
                        "defeat_state": character.defeat_state,
                    }
                }
            }
            if combatant:
                patch["encounter"] = {
                    "combatants": {
                        combatant.combatant_id: {
                            "status_effects": combatant.status_effects,
                            "defeat_state": combatant.defeat_state,
                        }
                    }
                }
            return {"target_type": "character", "target": character, "patch": patch}

        combatant = self.get_combatant(identifier)
        if not combatant:
            return None

        self._apply_defeat_state(combatant, normalized)
        character = self._sync_character_from_combatant(combatant)
        patch = {
            "encounter": {
                "combatants": {
                    combatant.combatant_id: {
                        "status_effects": combatant.status_effects,
                        "defeat_state": combatant.defeat_state,
                    }
                }
            }
        }
        if character:
            patch["characters"] = {
                character.character_id: {
                    "status_effects": character.status_effects,
                    "defeat_state": character.defeat_state,
                }
            }
        return {"target_type": "combatant", "target": combatant, "patch": patch}

    def add_status(self, identifier: str, status: str) -> Optional[Dict[str, Any]]:
        character = self.get_character(identifier)
        if character:
            if status not in character.status_effects:
                character.status_effects.append(status)
            combatant = self._sync_combatant_from_character(character)
            patch: Dict[str, Any] = {"characters": {character.character_id: {"status_effects": character.status_effects}}}
            if combatant:
                patch["encounter"] = {
                    "combatants": {combatant.combatant_id: {"status_effects": combatant.status_effects}}
                }
            return {"target_type": "character", "target": character, "patch": patch}

        combatant = self.get_combatant(identifier)
        if not combatant:
            return None

        if status not in combatant.status_effects:
            combatant.status_effects.append(status)
        character = self._sync_character_from_combatant(combatant)
        patch = {"encounter": {"combatants": {combatant.combatant_id: {"status_effects": combatant.status_effects}}}}
        if character:
            patch["characters"] = {character.character_id: {"status_effects": character.status_effects}}
        return {"target_type": "combatant", "target": combatant, "patch": patch}

    def remove_status(self, identifier: str, status: str) -> Optional[Dict[str, Any]]:
        character = self.get_character(identifier)
        if character:
            character.status_effects = [effect for effect in character.status_effects if effect != status]
            combatant = self._sync_combatant_from_character(character)
            patch: Dict[str, Any] = {"characters": {character.character_id: {"status_effects": character.status_effects}}}
            if combatant:
                patch["encounter"] = {
                    "combatants": {combatant.combatant_id: {"status_effects": combatant.status_effects}}
                }
            return {"target_type": "character", "target": character, "patch": patch}

        combatant = self.get_combatant(identifier)
        if not combatant:
            return None

        combatant.status_effects = [effect for effect in combatant.status_effects if effect != status]
        character = self._sync_character_from_combatant(combatant)
        patch = {"encounter": {"combatants": {combatant.combatant_id: {"status_effects": combatant.status_effects}}}}
        if character:
            patch["characters"] = {character.character_id: {"status_effects": character.status_effects}}
        return {"target_type": "combatant", "target": combatant, "patch": patch}

    def set_active_character(self, identifier: str) -> Optional[Character]:
        character = self.get_character(identifier)
        if not character:
            return None

        self.state.active_character_id = character.character_id
        return character

    def set_scene(self, scene: str) -> str:
        normalized = scene.strip().lower() or self.state.scene
        self.state.scene = normalized
        if normalized in {"setup", "exploration", "combat", "downtime", "level_up"}:
            self.state.campaign.phase = normalized
        return normalized

    def append_adventure_log(self, entry: str) -> None:
        text = entry.strip()
        if not text:
            return
        self.state.adventure_log.append(text)
        self.state.adventure_log = self.state.adventure_log[-50:]

    def add_inventory_item(
        self,
        character_ref: str,
        item_name: str,
        quantity: int = 1,
        item_type: str = "misc",
        notes: str = "",
        source: str = "",
        tags: Optional[List[str]] = None,
        is_equipped: bool = False,
        attack_bonus: Optional[int] = None,
        damage_expression: str = "",
        damage_type: str = "",
        armor_class_bonus: int = 0,
        properties: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        character = self.get_character(character_ref)
        if not character:
            return None

        normalized_name = item_name.strip()
        if not normalized_name:
            return None

        existing = next((entry for entry in character.inventory if entry.name == normalized_name), None)
        if existing:
            existing.quantity += max(1, quantity)
            if is_equipped:
                existing.is_equipped = True
            if item_type and existing.type == "misc":
                existing.type = item_type
            if notes:
                existing.notes = notes
            if source:
                existing.source = source
            if tags:
                existing.tags = list(dict.fromkeys([*existing.tags, *tags]))
            if attack_bonus is not None:
                existing.attack_bonus = attack_bonus
            if damage_expression:
                existing.damage_expression = damage_expression
            if damage_type:
                existing.damage_type = damage_type
            if armor_class_bonus:
                existing.armor_class_bonus = armor_class_bonus
            if properties:
                existing.properties = list(dict.fromkeys([*existing.properties, *properties]))
            item = existing
        else:
            item = InventoryItem(
                name=normalized_name,
                quantity=max(1, quantity),
                is_equipped=is_equipped,
                type=item_type or "misc",
                notes=notes,
                source=source,
                tags=list(tags or []),
                attack_bonus=attack_bonus,
                damage_expression=damage_expression,
                damage_type=damage_type,
                armor_class_bonus=armor_class_bonus,
                properties=list(properties or []),
            )
            character.inventory.append(item)

        patch = {
            "characters": {
                character.character_id: {
                    "inventory": [entry.model_dump(mode="json") for entry in character.inventory]
                }
            }
        }
        return {"character": character, "item": item, "patch": patch}

    def use_inventory_item(
        self,
        user_ref: str,
        item_name: str,
        quantity: int = 1,
    ) -> Dict[str, Any]:
        if quantity <= 0:
            raise ValueError("Item quantity must be greater than zero")

        self.require_current_actor(user_ref)
        user = self.get_character(user_ref)
        if not user:
            raise ValueError(f"Item user not found: {user_ref}")

        normalized_name = item_name.strip()
        if not normalized_name:
            raise ValueError("Item name is required")

        item = next((entry for entry in user.inventory if entry.name == normalized_name), None)
        if not item:
            raise ValueError(f"Item not found: {normalized_name}")
        if item.quantity < quantity:
            raise ValueError(
                f"Not enough item quantity for {normalized_name}: "
                f"requested {quantity}, available {item.quantity}"
            )

        item.quantity -= quantity
        patch = {
            "characters": {
                user.character_id: {
                    "inventory": [entry.model_dump(mode="json") for entry in user.inventory]
                }
            }
        }
        return {"character": user, "item": item, "quantity": quantity, "patch": patch}

    @staticmethod
    def _normalize_feature_action_cost(action_cost: str) -> str:
        normalized = str(action_cost or "action").strip().lower()
        if normalized in {"bonus", "bonus-action", "bonus_action"}:
            return "bonus_action"
        if normalized == "reaction":
            return "reaction"
        if normalized in {"free", "none", "no_action", "no-action", "passive"}:
            return "free"
        return "action"

    @staticmethod
    def _find_character_resource(character: Character, resource_name: str):
        normalized = str(resource_name or "").strip().casefold()
        if not normalized:
            return "", None
        for key, pool in character.resources.items():
            if key.casefold() == normalized:
                return key, pool
        return "", None

    @classmethod
    def feature_definition_for(cls, feature_name: str) -> Dict[str, Any]:
        normalized = str(feature_name or "").strip().casefold()
        if not normalized:
            return {}
        return dict(cls.FEATURE_DEFINITIONS.get(normalized) or {})

    def resolve_feature_use(
        self,
        actor_ref: str,
        feature_name: str,
        action_cost: str = "action",
        resource_name: str = "",
        resource_cost: int = 0,
    ) -> Dict[str, Any]:
        normalized_feature = str(feature_name or "").strip()
        if not normalized_feature:
            raise ValueError("Feature name is required")

        self.require_current_actor(actor_ref)
        character = self.get_character(actor_ref)
        combatant = self.get_combatant(actor_ref)
        if not character and combatant and combatant.linked_character_id:
            character = self.state.characters.get(combatant.linked_character_id)
        if not character and not combatant:
            raise ValueError(f"Feature actor not found: {actor_ref}")

        actor_type = "character" if character else "combatant"
        actor_id = character.character_id if character else combatant.combatant_id
        actor_name = character.name if character else combatant.name
        feature_definition = self.feature_definition_for(normalized_feature)
        normalized_action_cost = self._normalize_feature_action_cost(
            feature_definition.get("action_cost") or action_cost
        )
        patch: Dict[str, Any] = {}
        resource_payload: Dict[str, Any] = {}

        if normalized_action_cost != "free":
            self.require_turn_slot_available(normalized_action_cost, "use_feature")

        parsed_resource_cost = int(resource_cost or 0)
        if parsed_resource_cost < 0:
            raise ValueError("Feature resource cost cannot be negative")
        normalized_resource_name = str(resource_name or feature_definition.get("resource_name") or "").strip()
        if parsed_resource_cost <= 0 and feature_definition.get("resource_cost") and character:
            inferred_resource_name = normalized_resource_name or str(feature_definition.get("resource_name") or "")
            _, inferred_resource = self._find_character_resource(character, inferred_resource_name)
            if inferred_resource:
                parsed_resource_cost = int(feature_definition.get("resource_cost") or 0)
        if parsed_resource_cost > 0:
            if not normalized_resource_name:
                raise ValueError("Feature resource name is required when resource_cost is greater than zero")
            if not character:
                raise ValueError(f"Feature resource requires a character sheet: {actor_name}")
            resource_key, resource_pool = self._find_character_resource(character, normalized_resource_name)
            if not resource_pool:
                raise ValueError(f"Feature resource not found for {character.name}: {normalized_resource_name}")
            if resource_pool.current_value < parsed_resource_cost:
                raise ValueError(
                    f"Not enough feature resource for {resource_key}: "
                    f"requested {parsed_resource_cost}, available {resource_pool.current_value}"
                )
            before_value = resource_pool.current_value
            resource_pool.current_value -= parsed_resource_cost
            resource_payload = {
                "resource_name": resource_key,
                "resource_cost": parsed_resource_cost,
                "resource_before": before_value,
                "resource_after": resource_pool.current_value,
            }
            patch = self._merge_patches(
                patch,
                {
                    "characters": {
                        character.character_id: {
                            "resources": {
                                key: pool.model_dump(mode="json")
                                for key, pool in character.resources.items()
                            }
                        }
                    }
                },
            )

        if normalized_action_cost != "free":
            patch = self._merge_patches(
                patch,
                self.mark_current_turn_slot_used(normalized_action_cost, "use_feature"),
            )

        return {
            "actor_type": actor_type,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "feature_name": normalized_feature,
            "action_cost": normalized_action_cost,
            "resource_name": resource_payload.get("resource_name", normalized_resource_name),
            "resource_cost": resource_payload.get("resource_cost", parsed_resource_cost),
            "resource_before": resource_payload.get("resource_before"),
            "resource_after": resource_payload.get("resource_after"),
            "feature_definition": feature_definition,
            "patch": patch,
        }

    def record_evidence(
        self,
        title: str,
        summary: str,
        holder_ref: str = "",
        source_ref: str = "",
        location: str = "",
        tags: Optional[List[str]] = None,
        add_to_inventory: bool = True,
    ) -> Dict[str, Any]:
        normalized_title = title.strip()
        normalized_summary = summary.strip()
        record = EvidenceRecord(
            title=normalized_title,
            summary=normalized_summary,
            source_ref=source_ref.strip(),
            location=location.strip(),
            tags=list(tags or []),
        )

        patch: Dict[str, Any] = {}
        character = None
        if holder_ref:
            character = self.get_character(holder_ref)
            if not character:
                raise ValueError(f"Character not found for evidence holder: {holder_ref}")
            record.holder_character_id = character.character_id
            if add_to_inventory:
                inventory_result = self.add_inventory_item(
                    character_ref=character.character_id,
                    item_name=record.title,
                    quantity=1,
                    item_type="evidence",
                    notes=record.summary,
                    source=record.source_ref or record.location,
                    tags=record.tags,
                )
                if inventory_result:
                    patch = self._merge_patches(patch, inventory_result["patch"])

        self.state.evidence_records = [
            existing for existing in self.state.evidence_records if existing.evidence_id != record.evidence_id
        ]
        self.state.evidence_records.append(record)
        self.state.evidence_records.sort(key=lambda item: item.evidence_id)
        patch = self._merge_patches(
            patch,
            {"evidence_records": [item.model_dump(mode="json") for item in self.state.evidence_records]},
        )
        return {"evidence": record, "character": character, "patch": patch}

    def record_search_outcome(
        self,
        searcher_ref: str,
        target_ref: str,
        summary: str,
        location: str = "",
        recovered_items: Optional[List[str]] = None,
        recovered_evidence_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        searcher = self.get_character(searcher_ref)
        if not searcher:
            raise ValueError(f"Character not found for search: {searcher_ref}")

        record = SearchRecord(
            searcher_character_id=searcher.character_id,
            target_ref=target_ref.strip(),
            location=location.strip(),
            summary=summary.strip(),
            recovered_items=list(recovered_items or []),
            recovered_evidence_ids=[
                self._resolve_evidence_ref(
                    evidence_ref,
                    holder_character_id=searcher.character_id,
                    location=location,
                )
                for evidence_ref in (recovered_evidence_ids or [])
            ],
        )
        self.state.search_records.append(record)
        self.state.search_records = self.state.search_records[-50:]
        self.append_adventure_log(
            f"{searcher.name} searched {record.target_ref or 'target'} | {record.summary}"
        )
        patch = {
            "search_records": [item.model_dump(mode="json") for item in self.state.search_records],
            "adventure_log": list(self.state.adventure_log),
        }
        return {"search_record": record, "character": searcher, "patch": patch}

    def add_major_experience(self, character_ref: str, entry: str) -> Optional[Dict[str, Any]]:
        character = self.get_character(character_ref)
        if not character:
            return None

        text = entry.strip()
        if not text:
            return None

        if text not in character.major_experiences:
            character.major_experiences.append(text)
            character.major_experiences = character.major_experiences[-20:]

        patch = {
            "characters": {
                character.character_id: {
                    "major_experiences": list(character.major_experiences)
                }
            }
        }
        return {"character": character, "entry": text, "patch": patch}

    def record_chapter_progress(
        self,
        title: str,
        summary: str,
        chapter_number: int = 0,
        completed: bool = True,
    ) -> Dict[str, Any]:
        resolved_number = int(chapter_number) if int(chapter_number or 0) > 0 else len(self.state.campaign.completed_chapters) + 1
        record = ChapterRecord(
            chapter_number=resolved_number,
            title=title.strip(),
            summary=summary.strip(),
            status="completed" if completed else "in_progress",
        )

        self.state.campaign.current_chapter_number = record.chapter_number
        self.state.campaign.current_chapter_title = record.title
        self.state.campaign.current_chapter_summary = record.summary

        if completed:
            remaining = [
                existing
                for existing in self.state.campaign.completed_chapters
                if existing.chapter_number != record.chapter_number
            ]
            remaining.append(record)
            remaining.sort(key=lambda item: item.chapter_number)
            self.state.campaign.completed_chapters = remaining
            log_entry = f"Chapter {record.chapter_number} complete: {record.title} | {record.summary}"
            self.append_adventure_log(log_entry)
            for character in self.state.characters.values():
                experience_entry = f"Chapter {record.chapter_number}: {record.title} - {record.summary}"
                if experience_entry not in character.major_experiences:
                    character.major_experiences.append(experience_entry)
                    character.major_experiences = character.major_experiences[-20:]

        patch = {
            "campaign": {
                "current_chapter_number": self.state.campaign.current_chapter_number,
                "current_chapter_title": self.state.campaign.current_chapter_title,
                "current_chapter_summary": self.state.campaign.current_chapter_summary,
                "completed_chapters": [
                    chapter.model_dump(mode="json") for chapter in self.state.campaign.completed_chapters
                ],
            },
            "adventure_log": list(self.state.adventure_log),
        }
        if completed:
            patch["characters"] = {
                character.character_id: {
                    "major_experiences": list(character.major_experiences)
                }
                for character in self.state.characters.values()
            }
        return {"chapter": record, "patch": patch}

    # Encounter lifecycle.
    def start_encounter(self, enemy_names: List[str], enemy_hp: int = 10, enemy_ac: int = 10) -> EncounterState:
        # Starting combat again while an encounter is already active corrupts turn order and enemy HP.
        if self.state.encounter and self.state.encounter.active:
            has_existing_enemies = any(
                not combatant.linked_character_id for combatant in self.state.encounter.combatants.values()
            )
            if has_existing_enemies:
                raise ValueError("An encounter is already active. Use add_enemy for reinforcements instead.")

        encounter = self._ensure_encounter()

        for name in enemy_names:
            clean_name = name.strip()
            if not clean_name:
                continue
            combatant = Combatant(
                combatant_id=stable_id("cmb", f"{encounter.encounter_id}-{clean_name}"),
                name=clean_name,
                side="enemy",
                hp_current=enemy_hp,
                hp_max=enemy_hp,
                ac=enemy_ac,
                initiative_bonus=0,
            )
            encounter.combatants[combatant.combatant_id] = combatant

        encounter.active = True
        encounter.round_number = max(1, encounter.round_number)
        self._refresh_initiative_order()
        encounter.current_combatant_id = None
        encounter.turn_order_started = False
        self.state.scene = "combat"
        self.state.campaign.phase = "combat"
        return encounter

    def add_enemy(
        self,
        name: str,
        hp_max: int = 10,
        ac: int = 10,
        initiative_bonus: int = 0,
        side: str = "enemy",
    ) -> Combatant:
        encounter = self._ensure_encounter()
        combatant = Combatant(
            combatant_id=stable_id("cmb", f"{encounter.encounter_id}-{name}-{len(encounter.combatants)}"),
            name=name,
            side=side,
            hp_current=hp_max,
            hp_max=hp_max,
            ac=ac,
            initiative_bonus=initiative_bonus,
        )
        encounter.combatants[combatant.combatant_id] = combatant
        encounter.initiative_order.append(combatant.combatant_id)
        self._refresh_initiative_order()
        return combatant

    def add_monster_from_template(
        self,
        monster: MonsterTemplate,
        quantity: int = 1,
        custom_name: str = "",
        hp_override: Optional[int] = None,
        side: str = "enemy",
    ) -> List[Combatant]:
        encounter = self._ensure_encounter()
        spawned: List[Combatant] = []

        for index in range(1, max(1, quantity) + 1):
            combatant = self._build_monster_combatant(
                monster=monster,
                encounter_id=encounter.encounter_id,
                index=index,
                custom_name=custom_name,
                hp_override=hp_override,
                side=side,
            )
            encounter.combatants[combatant.combatant_id] = combatant
            encounter.initiative_order.append(combatant.combatant_id)
            spawned.append(combatant)

        self._refresh_initiative_order()
        return spawned

    def remove_combatant(self, identifier: str) -> Optional[Combatant]:
        encounter = self.state.encounter
        if not encounter:
            return None

        combatant = self.get_combatant(identifier)
        if not combatant or combatant.combatant_id not in encounter.combatants:
            return None
        if combatant.linked_character_id:
            raise ValueError("Party members cannot be removed from the encounter with this endpoint")

        previous_order = list(encounter.initiative_order)
        removed_index = previous_order.index(combatant.combatant_id) if combatant.combatant_id in previous_order else -1
        del encounter.combatants[combatant.combatant_id]
        encounter.initiative_order = [combatant_id for combatant_id in previous_order if combatant_id != combatant.combatant_id]

        if encounter.current_combatant_id == combatant.combatant_id:
            if encounter.initiative_order:
                next_index = min(max(removed_index, 0), len(encounter.initiative_order) - 1)
                encounter.current_combatant_id = encounter.initiative_order[next_index]
            else:
                encounter.current_combatant_id = None

        self._refresh_initiative_order()

        if not any(not entry.linked_character_id for entry in encounter.combatants.values()):
            encounter.active = False
            encounter.current_combatant_id = None
            encounter.turn_order_started = False
            self.state.scene = "exploration"
            self.state.campaign.phase = "exploration"

        return combatant

    # Combat resolution helpers.
    def _expand_critical_damage(self, expression: str) -> str:
        match = re.fullmatch(r"(\d+)d(\d+)([\+\-]\d+)?", expression.lower().replace(" ", ""))
        if not match:
            return expression
        dice_count = int(match.group(1)) * 2
        sides = match.group(2)
        modifier = match.group(3) or ""
        return f"{dice_count}d{sides}{modifier}"

    def resolve_attack(
        self,
        attacker_ref: str,
        target_ref: str,
        attack_bonus: int,
        damage_expression: str,
        damage_type: str = "",
        resolution_mode: str = "normal",
    ) -> Optional[Dict[str, Any]]:
        target_character = self.get_character(target_ref)
        target_combatant = None if target_character else self.get_combatant(target_ref)
        if not target_character and not target_combatant:
            return None

        target = target_character or target_combatant
        natural, attack_total, attack_detail = DiceRoller.roll_d20(attack_bonus)
        critical = natural == 20
        hit = critical or (natural != 1 and attack_total >= target.ac)

        damage_total = 0
        damage_detail = ""
        damage_roll = damage_expression
        patch: Dict[str, Any] = {}
        concentration_check: Optional[Dict[str, Any]] = None
        if hit and damage_expression:
            if critical:
                damage_roll = self._expand_critical_damage(damage_expression)
            damage_total, damage_detail = DiceRoller.roll(damage_roll)
            hp_result = self.update_target_hp(target_ref, -damage_total)
            if hp_result:
                patch = hp_result["patch"]
                target = hp_result["target"]
                concentration_check = hp_result.get("concentration_check")
                if target.hp_current <= 0:
                    if resolution_mode == "nonlethal":
                        defeat_result = self.set_defeat_state(target_ref, "unconscious")
                    elif resolution_mode == "capture":
                        defeat_result = self.set_defeat_state(target_ref, "captured")
                    else:
                        defeat_result = self.set_defeat_state(target_ref, self._default_zero_hp_state(target_ref))
                    if defeat_result:
                        patch = self._merge_patches(patch, defeat_result["patch"])

        return {
            "attacker_name": self.get_actor_name(attacker_ref),
            "target_name": target.name,
            "target_ac": target.ac,
            "natural": natural,
            "attack_total": attack_total,
            "attack_detail": attack_detail,
            "hit": hit,
            "critical": critical,
            "damage_expression": damage_expression,
            "damage_roll": damage_roll,
            "damage_total": damage_total,
            "damage_detail": damage_detail,
            "damage_type": damage_type,
            "resolution_mode": resolution_mode,
            "target_hp_current": target.hp_current,
            "target_defeat_state": getattr(target, "defeat_state", "active"),
            "concentration_check": concentration_check,
            "patch": patch,
        }

    def roll_skill_check(
        self,
        actor_ref: str,
        skill_name: str,
        modifier: int,
        dc: int = 0,
    ) -> Dict[str, Any]:
        natural, total, detail = DiceRoller.roll_d20(modifier)
        return {
            "actor_name": self.get_actor_name(actor_ref),
            "skill_name": skill_name,
            "modifier": modifier,
            "dc": dc,
            "natural": natural,
            "total": total,
            "detail": detail,
            "success": None if dc <= 0 else total >= dc,
        }

    def roll_saving_throw(
        self,
        target_ref: str,
        save_name: str,
        modifier: int,
        dc: int,
    ) -> Dict[str, Any]:
        natural, total, detail = DiceRoller.roll_d20(modifier)
        return {
            "target_name": self.get_actor_name(target_ref),
            "save_name": save_name,
            "modifier": modifier,
            "dc": dc,
            "natural": natural,
            "total": total,
            "detail": detail,
            "success": total >= dc,
        }

    def set_initiative(self, identifier: str, initiative: int) -> Optional[Combatant]:
        combatant = self.get_combatant(identifier)
        if not combatant:
            character = self.get_character(identifier)
            if not character:
                return None
            encounter = self._ensure_encounter()
            combatant = encounter.combatants.get(stable_id("cmb", f"{character.character_id}-party"))
        if not combatant:
            return None

        combatant.initiative = initiative
        self._refresh_initiative_order()
        self._start_turn_order_if_ready()
        encounter = self.state.encounter
        if encounter and encounter.round_number == 1 and encounter.initiative_order:
            eligible_order = [
                combatant_id
                for combatant_id in encounter.initiative_order
                if self._combatant_can_take_turn(encounter.combatants.get(combatant_id))
            ]
            if eligible_order:
                encounter.current_combatant_id = eligible_order[0]
                self._reset_turn_action_state(encounter)
        return combatant

    def roll_initiative(self, identifier: str) -> Optional[Dict[str, Any]]:
        combatant = self.get_combatant(identifier)
        if not combatant:
            character = self.get_character(identifier)
            if character:
                encounter = self._ensure_encounter()
                combatant = encounter.combatants.get(stable_id("cmb", f"{character.character_id}-party"))
        if not combatant:
            return None

        expression = f"1d20{combatant.initiative_bonus:+d}" if combatant.initiative_bonus else "1d20"
        total, detail = DiceRoller.roll(expression)
        combatant.initiative = total
        self._refresh_initiative_order()
        self._start_turn_order_if_ready()
        encounter = self.state.encounter
        if encounter and encounter.round_number == 1 and encounter.initiative_order:
            eligible_order = [
                combatant_id
                for combatant_id in encounter.initiative_order
                if self._combatant_can_take_turn(encounter.combatants.get(combatant_id))
            ]
            if eligible_order:
                encounter.current_combatant_id = eligible_order[0]
                self._reset_turn_action_state(encounter)
        return {"combatant": combatant, "total": total, "detail": detail, "expression": expression}

    def advance_turn(self) -> Optional[Combatant]:
        encounter = self.state.encounter
        if not encounter or not encounter.initiative_order:
            return None

        if not encounter.turn_order_started:
            if self._start_turn_order_if_ready():
                return encounter.get_current_combatant()
            return None

        eligible_order = [
            combatant_id
            for combatant_id in encounter.initiative_order
            if self._combatant_can_take_turn(encounter.combatants.get(combatant_id))
        ]
        if not eligible_order:
            encounter.current_combatant_id = None
            return None

        if encounter.current_combatant_id not in eligible_order:
            encounter.current_combatant_id = eligible_order[0]
            self._reset_turn_action_state(encounter)
            return encounter.get_current_combatant()

        current_index = eligible_order.index(encounter.current_combatant_id)
        next_index = (current_index + 1) % len(eligible_order)
        if next_index == 0:
            encounter.round_number += 1
        encounter.current_combatant_id = eligible_order[next_index]
        self._reset_turn_action_state(encounter)
        return encounter.get_current_combatant()

    # Encounter summaries feed logs, HTTP responses, and DM context.
    def summarize_encounter(self) -> Dict[str, Any]:
        encounter = self.state.encounter
        if not encounter:
            return {
                "encounter_id": "",
                "round_number": 0,
                "party_count": len(self.state.characters),
                "party_hp_total": sum(character.hp_current for character in self.state.characters.values()),
                "enemy_total": 0,
                "enemy_defeated": 0,
                "enemy_remaining": 0,
                "enemy_dead": 0,
                "enemy_unconscious": 0,
                "enemy_captured": 0,
                "ally_total": 0,
                "ally_remaining": 0,
            }

        party_hp_total = sum(character.hp_current for character in self.state.characters.values())
        enemies = [combatant for combatant in encounter.combatants.values() if combatant.side == "enemy"]
        allies = [combatant for combatant in encounter.combatants.values() if combatant.side == "ally"]
        enemy_dead = sum(1 for combatant in enemies if combatant.defeat_state == "dead")
        enemy_unconscious = sum(1 for combatant in enemies if combatant.defeat_state == "unconscious")
        enemy_captured = sum(1 for combatant in enemies if combatant.defeat_state == "captured")
        enemy_defeated = sum(
            1 for combatant in enemies if combatant.defeat_state != "active" or combatant.hp_current <= 0
        )

        return {
            "encounter_id": encounter.encounter_id,
            "round_number": encounter.round_number,
            "party_count": len(self.state.characters),
            "party_hp_total": party_hp_total,
            "enemy_total": len(enemies),
            "enemy_defeated": enemy_defeated,
            "enemy_remaining": sum(
                1 for combatant in enemies if combatant.hp_current > 0 and combatant.defeat_state == "active"
            ),
            "enemy_dead": enemy_dead,
            "enemy_unconscious": enemy_unconscious,
            "enemy_captured": enemy_captured,
            "ally_total": len(allies),
            "ally_remaining": sum(1 for combatant in allies if combatant.hp_current > 0),
        }

    def build_encounter_end_summary(self, summary: Dict[str, Any]) -> str:
        parts = [
            f"遭遇在第 {summary['round_number']} 轮结束",
            f"队伍 HP 合计 {summary['party_hp_total']}",
        ]
        if summary["enemy_total"] > 0:
            parts.append(
                f"敌人被击败 {summary['enemy_defeated']}/{summary['enemy_total']}"
            )
            nonlethal_parts = []
            if summary.get("enemy_dead", 0) > 0:
                nonlethal_parts.append(f"死亡 {summary['enemy_dead']}")
            if summary.get("enemy_unconscious", 0) > 0:
                nonlethal_parts.append(f"昏迷 {summary['enemy_unconscious']}")
            if summary.get("enemy_captured", 0) > 0:
                nonlethal_parts.append(f"被俘 {summary['enemy_captured']}")
            if nonlethal_parts:
                parts.append(", ".join(nonlethal_parts))
        if summary["ally_total"] > 0:
            parts.append(f"盟友剩余 {summary['ally_remaining']}/{summary['ally_total']}")
        return " | ".join(parts)

    def finalize_encounter(self) -> Optional[Dict[str, Any]]:
        encounter = self.state.encounter
        if not encounter:
            return None

        summary_payload = self.summarize_encounter()
        ended_encounter = self.end_encounter()
        if not ended_encounter:
            return None

        summary = self.build_encounter_end_summary(summary_payload)
        self.append_adventure_log(summary)
        return {
            "encounter": ended_encounter,
            "summary": summary,
            "summary_payload": summary_payload,
            "adventure_log_entry": summary,
        }

    def end_encounter(self) -> Optional[EncounterState]:
        encounter = self.state.encounter
        if not encounter:
            return None

        encounter.active = False
        encounter.current_combatant_id = None
        encounter.turn_order_started = False
        self.state.scene = "exploration"
        self.state.campaign.phase = "exploration"
        return encounter

    def get_recent_history(self, limit: int = 12) -> str:
        visible_history = self.state.chat_history[-limit:]
        if not visible_history:
            return "No previous visible conversation."

        lines = []
        for message in visible_history:
            role = message.role.upper()
            lines.append(f"{role}: {message.content}")
        return "\n".join(lines)

    def get_state_summary(self) -> str:
        # The DM prompt gets a compact but stateful snapshot instead of raw JSON.
        active = self.state.get_active_char()
        lines = [
            f"Scene: {self.state.scene}",
            f"Turn: {self.state.turn_number}",
            f"Title: {self.state.title or self.state.game_id or 'Untitled Adventure'}",
        ]

        selected_adventure = self.state.campaign.selected_adventure()
        if selected_adventure:
            lines.append(f"Selected Adventure: {selected_adventure.title}")
            if selected_adventure.summary:
                lines.append(f"Adventure Summary: {selected_adventure.summary}")
            if selected_adventure.opening_scene:
                lines.append(f"Opening Scene Cue: {selected_adventure.opening_scene}")
        if self.state.campaign.current_chapter_title:
            lines.append(
                f"Current Chapter: {self.state.campaign.current_chapter_number or '?'} - "
                f"{self.state.campaign.current_chapter_title}"
            )
            if self.state.campaign.current_chapter_summary:
                lines.append(f"Chapter Summary: {self.state.campaign.current_chapter_summary}")
        if self.state.campaign.completed_chapters:
            lines.append(f"Completed Chapters: {len(self.state.campaign.completed_chapters)}")

        if active:
            active_class = self._library.localize_game_terms(active.class_name)
            lines.append(f"Active Character: {active.name} ({active_class} Lv.{active.level})")

        if not self.state.characters:
            lines.append("Party: none")
        else:
            lines.append("Party:")
            for character in self.state.characters.values():
                statuses = (
                    ", ".join(self._library.localize_game_terms(status) for status in character.status_effects)
                    if character.status_effects
                    else "正常"
                )
                class_name = self._library.localize_game_terms(character.class_name)
                prepared_spell_names = self._library.normalize_spell_names(character.spells.prepared[:8])
                prepared_spells = ", ".join(prepared_spell_names) if prepared_spell_names else "无"
                lines.append(
                    (
                        f"- {character.name} [{character.character_id}] | "
                        f"{class_name} Lv.{character.level} | "
                        f"HP {character.hp_current}/{character.hp_max} | AC {character.ac} | "
                        f"Init Bonus {character.initiative_bonus:+d} | "
                        f"Defeat State: {character.defeat_state} | "
                        f"Status: {statuses} | Prepared Spells: {prepared_spells}"
                    )
                )

        if self.state.encounter and self.state.encounter.combatants:
            encounter = self.state.encounter
            lines.append(
                f"Encounter: active={encounter.active} round={encounter.round_number} "
                f"id={encounter.encounter_id} started={encounter.turn_order_started}"
            )
            current = encounter.get_current_combatant()
            if current:
                lines.append(f"Current Combatant: {current.name} ({current.side})")
            elif encounter.active:
                lines.append("Current Combatant: none yet (initiative not finalized)")
            for combatant_id in encounter.initiative_order or list(encounter.combatants.keys()):
                combatant = encounter.combatants.get(combatant_id)
                if not combatant:
                    continue
                statuses = ", ".join(combatant.status_effects) if combatant.status_effects else "Normal"
                initiative = combatant.initiative if combatant.initiative is not None else "?"
                lines.append(
                    (
                        f"- Combatant {combatant.name} [{combatant.combatant_id}] | "
                        f"{combatant.side} | HP {combatant.hp_current}/{combatant.hp_max} | "
                        f"AC {combatant.ac} | Initiative {initiative} | "
                        f"Defeat State: {combatant.defeat_state} | Status: {statuses}"
                    )
                )

        if self.state.adventure_log:
            lines.append("Recent adventure log:")
            for entry in self.state.adventure_log[-5:]:
                lines.append(f"- {entry}")

        if self.state.evidence_records:
            lines.append("Recent evidence:")
            for record in self.state.evidence_records[-5:]:
                lines.append(
                    f"- {record.title} [{record.evidence_id}] | holder={record.holder_character_id or 'none'} | "
                    f"source={record.source_ref or record.location or 'unknown'}"
                )

        if self.state.search_records:
            lines.append("Recent searches:")
            for record in self.state.search_records[-5:]:
                lines.append(
                    f"- search {record.search_id} | searcher={record.searcher_character_id or 'none'} | "
                    f"target={record.target_ref or 'unknown'} | items={', '.join(record.recovered_items) or 'none'}"
                )

        return "\n".join(lines)
