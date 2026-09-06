"""对话只消费一个玩家回合，交接状态属于本次图调用而非规则存档。"""
import json

from game_logic import GameLogic
from prompts import narrative_pacing_context


def player_actor(state, actor):
    return bool(actor and actor.side == "party" and state.is_player_controlled(actor.linked_character_id))


def initial_flow(state):
    encounter = state.encounter
    current = encounter.get_current_combatant() if encounter and encounter.active else None
    return {
        "input_actor_id": current.linked_character_id if player_actor(state, current) else (state.active_character_id if state.is_player_controlled(state.active_character_id) else state.get_primary_character_id()),
        "action_done": bool(current and player_actor(state, current) and encounter.turn_action_used),
        "stop_at_player": bool(encounter and encounter.active and (not current or not player_actor(state, current) or not GameLogic._combatant_can_take_turn(current))),
        "combat": bool(encounter and encounter.active),
        "started_in_combat": bool(encounter and encounter.active),
    }


def handoff_ready(state, flow):
    encounter = state.encounter
    if not encounter or not encounter.active or not encounter.turn_order_started:
        return False
    current = encounter.get_current_combatant()
    different_player = bool(current and flow.get("input_actor_id") and current.linked_character_id != flow["input_actor_id"])
    if (flow.get("stop_at_player") or different_player) and player_actor(state, current) and GameLogic._combatant_can_take_turn(current):
        return True
    # 倒地的主控不能令 DM 队友无止境自动作战；留给玩家接管仍可行动的队友。
    capable_players = any(player_actor(state, actor) and GameLogic._combatant_can_take_turn(actor) for actor in encounter.combatants.values())
    capable_companions = any(actor.side == "party" and actor.linked_character_id in state.characters and GameLogic._combatant_can_take_turn(actor) for actor in encounter.combatants.values())
    return not capable_players and capable_companions


def needs_advance(state, flow):
    encounter = state.encounter
    current = encounter.get_current_combatant() if encounter and encounter.active else None
    return bool(current and player_actor(state, current)
                and current.linked_character_id == flow.get("input_actor_id")
                and (flow.get("action_done") or encounter.turn_action_used)
                and not state.pending_spell_attacks and not handoff_ready(state, flow))


def finishing_tools(state):
    # 主动作后仍可结算玩家在同一条输入中声明的合法附赠动作；规则层继续审核槽位和资源。
    return ["advance_turn", "end_concentration"] + ([] if state.encounter.turn_bonus_action_used else ["use_feature", "cast_spell", "use_item"])


def after_tool(before, after, flow, tool_name):
    result = dict(flow)
    result["combat"] = bool(flow.get("combat") or (after.encounter and after.encounter.active))
    current = before.encounter.get_current_combatant() if before.encounter and before.encounter.active else None
    if current and player_actor(before, current) and current.linked_character_id == flow.get("input_actor_id"):
        if tool_name == "advance_turn" and before.encounter.turn_order_started:
            result["stop_at_player"] = True
        elif after.encounter and after.encounter.turn_action_used:
            result["action_done"] = True
    return result


def narrative_scope(state, flow, initial_payload=None):
    # 卡片颜色表示曾发生战斗；长度例外则取决于这条回复开始时是否就在战斗中。
    started = bool((initial_payload.get("encounter") or {}).get("active")) if initial_payload is not None else bool(flow.get("started_in_combat", flow.get("combat", False)))
    seen_combat = started or bool(flow.get("combat") or (state.encounter and state.encounter.active))
    return "combat" if started else "mixed" if seen_combat else "story"


def guidance(state, flow, initial_payload=None):
    pacing = narrative_pacing_context(narrative_scope(state, flow, initial_payload))
    if not flow.get("combat") and not (state.encounter and state.encounter.active):
        return pacing
    controllers = ", ".join(f"{c.name}: {'player' if state.is_player_controlled(c.character_id) else 'DM'}" for c in state.characters.values())
    common = (pacing + "\n" + f"Combat controllers: {controllers}. Use real registered tools and dice for ALL DM actors. "
              "Resolve only the input player's declared action, advance that turn, then resolve DM turns in initiative order until the NEXT player decision. "
              "Never reuse the old instruction for that next player. Narrate resolved events with the scene-aware pacing policy. ")
    encounter = state.encounter
    current = encounter.get_current_combatant() if encounter and encounter.active else None
    character = state.characters.get(current.linked_character_id) if current else None
    if character:
        # 主持上下文最初只装配一次；轮到托管队友时必须提供它此刻的装备/法术，不能沿用主角或臆造攻击。
        sheet = {
            "actor_ref": character.character_id,
            "name": character.name,
            "weapons": [item.model_dump(mode="json") for item in character.inventory if item.type == "weapon" and item.quantity > 0],
            "spells": character.spells.model_dump(mode="json"),
            "concentration_spell": character.concentration_spell,
            "status_effects": character.status_effects,
            "ongoing_spell_effects": [e.model_dump(mode="json") for e in state.active_spell_effects if character.character_id in {e.caster_id,e.target_id}],
            "resources": {name: pool.model_dump(mode="json") for name, pool in character.resources.items()},
            "action_used": encounter.turn_action_used,
            "bonus_action_used": encounter.turn_bonus_action_used,
        }
        common += "Current authoritative party actor sheet: " + json.dumps(sheet, ensure_ascii=False) + ". "
    if handoff_ready(state, flow):
        return common + "STOP: the next player decision is reached, or no player can act. Write the final in-world narration of the events already resolved, preserving any pre-combat story and giving significant combat moments room, then leave the next player's decision (or companion takeover if all players are unable to act). Do not execute more tools."
    if needs_advance(state, flow):
        return common + "The input player's action is already spent. Never repeat a primary action. Resolve ONLY an explicitly declared legal bonus action if still available; otherwise call advance_turn now. Do not invent optional player actions."
    return common
