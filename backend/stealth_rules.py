"""D&D 2024 躲藏/察觉的确定性结算；场景视线前提由 DM 明确提供。"""

from models import Character, HidingState


def actor_for(logic, ref):
    return logic.get_character(ref) or logic._concentration_character(ref) or logic.get_combatant(ref)


def is_invisible(actor):
    return bool(actor and (actor.hiding or any(str(s).casefold() in {"invisible", "隐形"} for s in actor.status_effects)))


def combine_roll_mode(requested="normal", *, advantage=False, disadvantage=False):
    if requested not in {"normal", "advantage", "disadvantage"}:
        raise ValueError("Invalid roll mode")
    advantage = advantage or requested == "advantage"
    disadvantage = disadvantage or requested == "disadvantage"
    return "normal" if advantage == disadvantage else "advantage" if advantage else "disadvantage"


def hiding_patch(logic, actor):
    data = actor.hiding.model_dump(mode="json") if actor.hiding else None
    if isinstance(actor, Character):
        mirror = logic._sync_combatant_from_character(actor)
        patch = {"characters": {actor.character_id: {"hiding": data}}}
        if mirror:
            patch["encounter"] = {"combatants": {mirror.combatant_id: {"hiding": data}}}
        return patch
    return {"encounter": {"combatants": {actor.combatant_id: {"hiding": data}}}}


def end_hiding(logic, ref):
    actor = actor_for(logic, ref)
    if not actor:
        raise ValueError("Hiding actor not found")
    if not actor.hiding:
        return {}
    actor.hiding = None
    return hiding_patch(logic, actor)


def skill_modifier(actor, skill, rules):
    if isinstance(actor, Character):
        return rules.get_skill_modifier(actor, skill)
    ability = "dexterity" if skill == "Stealth" else "wisdom"
    for name, modifier in actor.skills.items():
        if rules.normalize_skill_name(name) == skill:
            return int(modifier)
    return (getattr(actor.stats, ability) - 10) // 2


def hide_actor(state, rules, actor_ref, cover, observed, reason, roll_mode="normal"):
    from game_logic import GameLogic
    logic = GameLogic(state)
    actor = actor_for(logic, actor_ref)
    if not actor:
        raise ValueError("Hiding actor not found")
    if cover not in {"heavily_obscured", "three_quarters", "total"} or observed:
        raise ValueError("Hide requires heavy obscurement or three-quarters/total cover and being out of every enemy's sight")
    if not str(reason).strip():
        raise ValueError("Describe the established cover and sight conditions before hiding")
    logic.require_actor_slot_available(actor_ref, "action", "hide_actor")
    if actor.hiding:
        return {"actor_name": actor.name, "success": True, "already_hidden": True,
                "stealth_total": actor.hiding.stealth_total, "action_spent": False}, {}
    result = logic.roll_skill_check(actor_ref, "Stealth", skill_modifier(actor, "Stealth", rules), 15, roll_mode)
    if result["success"]:
        actor.hiding = HidingState(stealth_total=result["total"], cover=cover, reason=reason)
    patch = GameLogic._merge_patches(hiding_patch(logic, actor), logic.mark_actor_slot_used(actor_ref, "action", "hide_actor"))
    return {**result, "label": "躲藏", "actor_id": actor.character_id if isinstance(actor, Character) else actor.combatant_id,
            "stealth_total": result["total"], "cover": cover, "reason": reason,
            "action_spent": bool(state.encounter and state.encounter.active)}, patch


def search_hidden(state, rules, actor_ref, target_ref, passive=False, roll_mode="normal"):
    from game_logic import GameLogic
    logic = GameLogic(state)
    observer, target = actor_for(logic, actor_ref), actor_for(logic, target_ref)
    if not observer or not target or observer is target:
        raise ValueError("Search requires two distinct existing actors")
    if not target.hiding:
        raise ValueError("Target has no active Hide state")
    logic.require_actor_capable(actor_ref)
    mode = combine_roll_mode(roll_mode)
    modifier = skill_modifier(observer, "Perception", rules)
    dc = target.hiding.stealth_total
    patch = {}
    if passive:
        total = 10 + modifier + (5 if mode == "advantage" else -5 if mode == "disadvantage" else 0)
        result = {"total": total, "success": total >= dc, "dc": dc}
    else:
        logic.require_actor_slot_available(actor_ref, "action", "search_hidden")
        result = logic.roll_skill_check(actor_ref, "Perception", modifier, dc, mode)
        patch = logic.mark_actor_slot_used(actor_ref, "action", "search_hidden")
    observer_side = "party" if isinstance(observer, Character) else observer.side
    target_side = "party" if isinstance(target, Character) else target.side
    hostile_observer = (observer_side == "enemy") != (target_side == "enemy")
    if result["success"] and hostile_observer:
        patch = GameLogic._merge_patches(patch, end_hiding(logic, target_ref))
    return {**result, "label": "被动察觉" if passive else "搜索躲藏者", "actor_name": observer.name, "target_name": target.name,
            "passive": passive, "hiding_ended": bool(result["success"] and hostile_observer)}, patch
