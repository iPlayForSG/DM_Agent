"""规则操作失败的事务级待办；成功的无关工具不能抹去未结算的操作。"""
from game_logic import GameLogic
from library import Library

RESOLUTION_TOOLS = {"adjust_currency", "check_spell_sequence","cast_spell", "attack_target", "roll_saving_throw", "roll_skill_check", "use_item", "use_feature",
                    "register_scene_actor", "start_encounter", "add_status", "remove_status", "adjust_hp"}


def identity(state, name, args):
    logic = GameLogic(state)
    def ref(value):
        if not value:
            return ""
        if not isinstance(value, str):
            return repr(value)
        try:
            actor = logic.get_character(value) or logic.get_combatant(value)
        except ValueError:
            actor = None
        return (getattr(actor, "character_id", "") or actor.linked_character_id or actor.combatant_id) if actor else str(value)
    source = next((args.get(key) for key in ("caster_ref", "source_ref", "attacker_ref", "actor_ref", "user_ref", "character_ref") if args.get(key)), "")
    targets = list(args.get("target_refs") or [])
    if args.get("target_ref"): targets.append(args["target_ref"])
    spell = Library().normalize_spell_name(args.get("spell_name", "")) if args.get("spell_name") else ""
    operation = args.get("item_name", args.get("name", ""))
    if name == 'adjust_currency':
        # 收入不能清除尚未成功的付款，补足钱之后仍须真正执行原付款。
        amount = args.get('amount')
        operation = 'payment' if isinstance(amount, int) and amount < 0 else 'income'
    return (name, ref(source), spell, operation, tuple(sorted(ref(value) for value in targets)))


def update_failures(state, failures, name, args, ok, error):
    if name not in RESOLUTION_TOOLS:
        return list(failures)
    current = identity(state, name, args)
    result = []
    for failure in failures:
        old = identity(state, failure["tool_name"], failure["args"])
        same = old[:4] == current[:4] and (old[4] == current[4] or not old[4])
        if not same:
            result.append(failure)
    if not ok:
        result.append({"tool_name": name, "args": args, "error": error})
    return result
