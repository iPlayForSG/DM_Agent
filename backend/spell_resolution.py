"""Agent 与本地 API 共用的施法记账和法术攻击结算。"""

from uuid import uuid4

from game_logic import GameLogic
from models import GameState, SpellAttackCast
from rules_catalog import RuleCatalog


def spell_turn_key(state: GameState) -> str:
    encounter = state.encounter
    if encounter and encounter.active:
        return f"{encounter.encounter_id}:{encounter.round_number}:{encounter.current_combatant_id}"
    return f"exploration:{state.turn_number}"


def get_attack_cast(state: GameState, caster_ref: str, cast_id: str) -> SpellAttackCast:
    logic = GameLogic(state)
    caster = logic.get_character(caster_ref) or logic._concentration_character(caster_ref)
    cast = next((item for item in state.pending_spell_attacks if item.cast_id == cast_id), None)
    if not caster or not cast or cast.caster_id != caster.character_id:
        raise ValueError("Spell attack requires this caster's successful cast_id")
    if cast.turn_key != spell_turn_key(state) or cast.attacks_remaining <= 0:
        raise ValueError("Spell attack cast_id has expired or was already resolved")
    logic.require_actor_capable(caster_ref)
    return cast


def cast_spell(state: GameState, rules: RuleCatalog, caster_ref: str, spell_name: str, slot_level: int = 0):
    logic = GameLogic(state)
    caster = logic.get_character(caster_ref) or logic._concentration_character(caster_ref)
    if not caster:
        raise ValueError(f"Spell caster not found: {caster_ref}")
    validation = rules.can_cast_spell(caster, spell_name, slot_level or None)
    if not validation["ok"]:
        raise ValueError(validation["error"])
    details = validation["spell"]
    canonical_name = str(validation["spell_name"])
    resolved_slot = int(validation["resolved_slot_level"])
    cost = rules.spell_action_cost(details)
    logic.require_actor_slot_available(caster.character_id, cost, "cast_spell")
    profile = rules.get_spell_attack_profile(caster, canonical_name, resolved_slot)
    previous = caster.concentration_spell
    rules.consume_spell_slot(caster, resolved_slot)
    if details.get("concentration"):
        caster.concentration_spell = canonical_name
        caster.concentration_spell_level = int(details.get("level") or 0)
    action_patch = logic.mark_actor_slot_used(caster.character_id, cost, "cast_spell")
    state.pending_spell_attacks = [item for item in state.pending_spell_attacks if item.turn_key == spell_turn_key(state)]
    cast = None
    if profile:
        cast = SpellAttackCast(
            cast_id=uuid4().hex, caster_id=caster.character_id, spell_name=canonical_name,
            turn_key=spell_turn_key(state), action_cost=cost, attack_bonus=profile["attack_bonus"],
            damage_expression=profile["damage_expression"], damage_types=profile["damage_types"],
            attacks_remaining=profile["attack_count"],
        )
        state.pending_spell_attacks.append(cast)
    payload = {
        "caster_id": caster.character_id, "caster_name": caster.name, "spell_name": canonical_name,
        "requested_spell_name": spell_name, "spell_level": int(details.get("level") or 0),
        "resolved_slot_level": resolved_slot, "action_cost": cost,
        "concentration": bool(details.get("concentration")),
        "desc": str(details.get("desc") or details.get("description") or ""),
        "previous_concentration_spell": previous, "current_concentration_spell": caster.concentration_spell,
        "remaining_slots": {level: {"total": slot.total, "used": slot.used} for level, slot in caster.spells.slots.items()},
        "cast_id": cast.cast_id if cast else "", "attack_count": cast.attacks_remaining if cast else 0,
        "damage_types": cast.damage_types if cast else [],
    }
    return payload, GameLogic._merge_patches(action_patch, {
        "characters": {caster.character_id: {
            "spells": caster.spells.model_dump(mode="json"), "concentration_spell": caster.concentration_spell,
            "concentration_spell_level": caster.concentration_spell_level,
        }},
        "pending_spell_attacks": [item.model_dump(mode="json") for item in state.pending_spell_attacks],
    })


def resolve_spell_attack(state: GameState, caster_ref: str, target_ref: str, cast_id: str,
                         damage_type: str = "", roll_mode: str = "normal"):
    cast = get_attack_cast(state, caster_ref, cast_id)
    logic = GameLogic(state)
    logic.require_actor_action(caster_ref, cast.action_cost)
    kind = damage_type or (cast.damage_types[0] if len(cast.damage_types) == 1 else "")
    if kind not in cast.damage_types:
        raise ValueError(f"Choose a spell damage type from: {', '.join(cast.damage_types)}")
    result = logic.resolve_attack(caster_ref, target_ref, cast.attack_bonus, cast.damage_expression, kind, roll_mode=roll_mode)
    if result is None:
        raise ValueError(f"Spell attack target not found: {target_ref}")
    # 凭据在成功结算后消费，失败和重复请求不能免费得到第二次攻击。
    cast.attacks_remaining -= 1
    state.pending_spell_attacks = [item for item in state.pending_spell_attacks if item.attacks_remaining > 0]
    result.update({"cast_id": cast_id, "spell_name": cast.spell_name, "attack_name": cast.spell_name,
                   "attack_bonus": cast.attack_bonus, "modifier_source": "character_spellcasting",
                   "attacks_remaining": cast.attacks_remaining})
    result["patch"] = GameLogic._merge_patches(result["patch"], {
        "pending_spell_attacks": [item.model_dump(mode="json") for item in state.pending_spell_attacks],
    })
    return result
