"""只读检查复合施法的资源、目标和相互终止条件，不尝试掷骰。"""
from game_logic import GameLogic
from spell_rules import rule_for, RuleConflict, RulesUnavailable
from spell_effects import validate_targets


def check_spell_sequence(state, rules, caster_ref, casts, preserve_effects=True):
    if not 1 <= len(casts) <= 8:
        raise ValueError("一次检查应包含1至8个明确施法动作")
    work = state.model_copy(deep=True)
    logic = GameLogic(work)
    caster = logic.get_character(caster_ref) or logic._concentration_character(caster_ref)
    if not caster:
        raise ValueError("未找到施法者")
    previous = [(effect.spell_name, {'concentration':effect.requires_concentration, 'end_events':effect.end_events})
                for effect in work.active_spell_effects if effect.caster_id == caster.character_id]
    costs = {"action": 0, "bonus_action": 0, "reaction": 0}
    slots_spent = 0
    checked = []
    sequence = []
    for cast in casts:
        validation = rules.can_cast_spell(caster, cast.get("spell_name", ""), cast.get("slot_level") or None)
        if not validation["ok"]:
            raise RuleConflict(validation["error"])
        details, slot = validation["spell"], int(validation["resolved_slot_level"])
        rule = rule_for(details)
        if not rule and not rules.get_spell_attack_profile(caster, validation["spell_name"], slot):
            raise RulesUnavailable(f"{validation['spell_name']}尚缺可执行规则资料")
        targets = validate_targets(logic, caster, cast.get("target_refs") or [], slot, rule) if rule else []
        cost = rules.spell_action_cost(details)
        if work.encounter and work.encounter.active:
            logic.require_actor_slot_available(caster.character_id, cost, "cast_spell")
            if cost in costs:
                costs[cost] += 1
                if costs[cost] > 1:
                    raise RuleConflict("这组施法需要重复使用同一回合的动作额度，请先选择当前回合要执行的行动。")
            slots_spent += int(slot > 0)
            if slots_spent > 1:
                raise RuleConflict("同一战斗回合只能消耗一个法术位，这组施法需要调整。")
        if preserve_effects:
            for earlier_name, earlier in previous:
                if (rule and rule.get("save") and "caster_forces_save" in earlier.get("end_events", [])) or (earlier.get("concentration") and details.get("concentration")):
                    raise RuleConflict(f"按此顺序，{validation['spell_name']}会结束先前的{earlier_name}，无法同时保留这些效果。请调整顺序或行动。")
        rules.consume_spell_slot(caster, slot)
        if rule:
            previous.append((validation["spell_name"], rule))
        checked.append(validation["spell_name"])
        sequence.append({"spell_name":validation['spell_name'], "target_ids":targets, "slot_level":slot})
    return {"valid": True, "spells": checked, "conflicts": [], "caster_id":caster.character_id,
            "sequence":sequence, "cast_history_count":sum('slot_level' in entry for entry in state.spell_cast_history)}
