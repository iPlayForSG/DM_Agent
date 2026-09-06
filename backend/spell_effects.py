"""有来源的持续法术效果与真实豁免；当前规则化塔莎狂笑术。"""
from uuid import uuid4

from models import ActiveSpellEffect
from roll_capture import dice_context

LAUGHTER_NAMES = {"塔莎狂笑术", "tasha's hideous laughter", "hideous laughter"}
CONDITIONS = ("Incapacitated", "Prone")
ALIASES = {"失能": "Incapacitated", "倒地": "Prone"}


def is_laughter(name):
    return str(name).replace('’', "'").strip().casefold() in LAUGHTER_NAMES


def canonical_condition(name):
    return ALIASES.get(name, next((c for c in CONDITIONS if c.casefold() == str(name).casefold()), name))


def actor(logic, ref):
    return logic.get_character(ref) or logic.get_combatant(ref)


def actor_id(logic, ref):
    value = actor(logic, ref)
    if value is None:
        raise ValueError(f"Spell target not found: {ref}")
    return getattr(value, 'character_id', '') or value.linked_character_id or value.combatant_id


def sync(logic, value):
    if hasattr(value, 'character_id'):
        logic._sync_combatant_from_character(value)
    else:
        logic._sync_character_from_combatant(value)


def effect_patch(logic):
    state = logic.state
    patch = {"active_character_id": state.active_character_id, "active_spell_effects": [e.model_dump(mode='json') for e in state.active_spell_effects],
             "rules_time_seconds": state.rules_time_seconds,
             "characters": {key: {"status_effects": list(c.status_effects), "concentration_spell": c.concentration_spell,
                                  "concentration_spell_level": c.concentration_spell_level} for key, c in state.characters.items()}}
    if state.encounter:
        patch['encounter'] = {"combatants": {key: {"status_effects": list(c.status_effects)} for key,c in state.encounter.combatants.items()}}
    return patch


def end_effect(logic, effect, reason):
    if effect not in logic.state.active_spell_effects:
        return
    logic.state.active_spell_effects.remove(effect)
    value = actor(logic, effect.target_id)
    for condition in effect.added_conditions:
        successor = next((e for e in logic.state.active_spell_effects if e.target_id == effect.target_id and condition in e.conditions), None)
        if successor:
            if condition not in successor.added_conditions:
                successor.added_conditions.append(condition)
        elif value:
            value.status_effects = [c for c in value.status_effects if canonical_condition(c) != condition]
    if value:
        sync(logic, value)
    caster = logic.state.characters.get(effect.caster_id)
    if caster and caster.concentration_spell == effect.spell_name and not any(e.caster_id == effect.caster_id and e.spell_name == effect.spell_name for e in logic.state.active_spell_effects):
        caster.concentration_spell = ''; caster.concentration_spell_level = 0
    logic.effect_events.append({'type':'effect_ended','spell_name':effect.spell_name,'target_name':value.name if value else effect.target_id,'reason':reason})


def end_concentration(logic, caster_id, reason='停止专注'):
    caster = logic._concentration_character(caster_id)
    if not caster:
        raise ValueError(f"Spell caster not found: {caster_id}")
    for effect in list(logic.state.active_spell_effects):
        if effect.caster_id == caster.character_id:
            end_effect(logic,effect,reason)
    caster.concentration_spell = ''; caster.concentration_spell_level = 0
    return effect_patch(logic)


def cleanup(logic):
    for effect in list(logic.state.active_spell_effects):
        caster = logic.state.characters.get(effect.caster_id)
        target = actor(logic,effect.target_id)
        if not caster or caster.concentration_spell != effect.spell_name or caster.hp_current <= 0 or logic.is_incapacitated(caster) or caster.defeat_state == 'dead':
            end_effect(logic,effect,'专注结束')
        elif not target or target.defeat_state == 'dead':
            end_effect(logic,effect,'目标不再有效')


def expire(logic, current_ref=None):
    for effect in list(logic.state.active_spell_effects):
        if effect.expires_at_seconds <= logic.state.rules_time_seconds and (current_ref is None or effect.caster_id == current_ref):
            end_effect(logic,effect,'持续时间结束')


def _save(logic, effect, trigger):
    value = actor(logic,effect.target_id)
    if not value:
        raise ValueError('Spell target no longer exists')
    if hasattr(value,'character_id'):
        modifier = logic._character_save_modifier(value,effect.save_name)
    else:
        modifier = next((int(v) for k,v in value.saving_throws.items() if str(k).casefold() in {effect.save_name,'wis'}), logic._ability_modifier_from_stats(value.stats,effect.save_name))
    roll_mode = 'advantage' if trigger == '受到伤害' else 'normal'
    with dice_context(reason=f'{effect.spell_name}：{trigger}',visibility='public'):
        result = logic.roll_saving_throw(effect.target_id,effect.save_name,modifier,effect.save_dc,roll_mode)
    event = {'type':'spell_save', 'spell_name':effect.spell_name, 'trigger':trigger, **result}
    event['summary'] = f"{value.name} 感知豁免{'（优势）' if roll_mode == 'advantage' else ''} {result['total']} vs DC {effect.save_dc} -> {'成功' if result['success'] else '失败'} | {effect.spell_name}：{trigger}"
    logic.effect_events.append(event)
    return result


def repeat_saves(logic, target_ref, trigger):
    cleanup(logic)
    identifier = actor_id(logic,target_ref)
    for effect in list(logic.state.active_spell_effects):
        if effect.target_id == identifier:
            if _save(logic,effect,trigger)['success']:
                end_effect(logic,effect,'豁免成功')
            elif trigger == '回合结束':
                effect.next_save_at_seconds = logic.state.rules_time_seconds + 6


def before_turn(logic, value):
    cleanup(logic)
    identifier = getattr(value,'linked_character_id',None) or getattr(value,'character_id',None) or value.combatant_id
    expire(logic,identifier)
    present = {c.linked_character_id for c in logic.state.encounter.combatants.values()} if logic.state.encounter else set()
    for effect in list(logic.state.active_spell_effects):
        if effect.caster_id not in present and effect.expires_at_seconds <= logic.state.rules_time_seconds:
            end_effect(logic,effect,'持续时间结束')


def immunity_conditions(logic, target):
    result = set()
    template_id = getattr(target,'monster_template_id','')
    if template_id:
        from storage import MonsterStorage
        template = logic.state.monster_templates.get(template_id) or MonsterStorage().load_monster(template_id)
        if template:result = {canonical_condition(c) for c in template.condition_immunities}
    return result


def validate_laughter_targets(logic, references, slot):
    if not references:
        raise ValueError('塔莎狂笑术必须指定 target_ref 或 target_refs；未做目标豁免不能宣布生效。')
    ids = [actor_id(logic,ref) for ref in references]
    if len(ids) != len(set(ids)) or len(ids) > slot:
        raise ValueError(f'塔莎狂笑术本次最多选择 {slot} 个不同目标。')
    if any(actor(logic,ref).defeat_state == 'dead' for ref in ids):
        raise ValueError('不能对尸体施放塔莎狂笑术。')
    return ids


def apply_laughter(logic, caster, spell_name, target_ids, profile):
    cast_id = uuid4().hex
    for target_id in target_ids:
        target = actor(logic,target_id)
        effect = ActiveSpellEffect(effect_id=uuid4().hex,cast_id=cast_id,spell_name=spell_name,
            caster_id=caster.character_id,target_id=target_id,save_name=profile['save_name'],save_dc=profile['dc'],
            expires_at_seconds=logic.state.rules_time_seconds+60, next_save_at_seconds=logic.state.rules_time_seconds+6)
        if _save(logic,effect,'初次施法')['success']:
            continue
        immunities = immunity_conditions(logic,target)
        effect.conditions = [c for c in CONDITIONS if c not in immunities]
        if immunities & set(CONDITIONS):
            logic.effect_events.append({"type":"effect_immunity","spell_name":spell_name,"target_name":target.name,"conditions_applied":effect.conditions})
        if not effect.conditions:
            logic.effect_events.append({'type':'effect_immune','spell_name':spell_name,'target_name':target.name})
            continue
        existing = {canonical_condition(c) for c in target.status_effects}
        effect.added_conditions = [c for c in effect.conditions if c not in existing]
        target.status_effects.extend(effect.added_conditions)
        logic.state.active_spell_effects.append(effect)
        sync(logic,target)
        target_caster = logic._concentration_character(target_id)
        if target_caster:
            logic._clear_incapacitated_concentration(target_caster)
    # 自我失能也会立刻打断自己的专注，不能留下自相矛盾的持续效果。
    cleanup(logic)
    if not any(e.caster_id == caster.character_id and e.cast_id == cast_id for e in logic.state.active_spell_effects):
        if caster.concentration_spell == spell_name:
            caster.concentration_spell = ''; caster.concentration_spell_level = 0
    return effect_patch(logic)


def preserve_manual_condition(logic, target_ref, status):
    identifier = actor_id(logic,target_ref)
    for effect in logic.state.active_spell_effects:
        if effect.target_id == identifier:
            effect.added_conditions = [c for c in effect.added_conditions if c != canonical_condition(status)]


def require_condition_removable(logic, target_ref, status):
    identifier = actor_id(logic,target_ref)
    if any(e.target_id == identifier and canonical_condition(status) in e.conditions for e in logic.state.active_spell_effects):
        raise ValueError('该状态仍由持续法术维持；须成功豁免、结束专注或等待效果到期。')


def advance_with_effects(logic):
    encounter = logic.state.encounter
    if not encounter.initiative_order:
        return None
    if not encounter.turn_order_started:
        logic._start_turn_order_if_ready()
        return encounter.get_current_combatant()
    order = list(encounter.initiative_order)
    current = encounter.get_current_combatant()
    cursor = order.index(current.combatant_id) if current and current.combatant_id in order else -1
    if current and current.defeat_state != 'dead':
        repeat_saves(logic,current.combatant_id,'回合结束')
    # 对失能者跳过的是行动，不是回合末事件。豁免恢复后也不能倒回该回合补行动。
    for offset in range(1,len(order)+1):
        index = (cursor+offset) % len(order)
        if index == 0:
            encounter.round_number += 1
            logic.state.rules_time_seconds += 6
        candidate = encounter.combatants.get(order[index])
        if not candidate:
            continue
        encounter.current_combatant_id = candidate.combatant_id
        before_turn(logic,candidate)
        if candidate.defeat_state != 'dead':
            # 失能也会进入自己的回合；反应额度此时恢复，不能延迟到解除控制后的下一轮。
            logic._reset_turn_action_state(encounter)
        if logic._combatant_can_take_turn(candidate):
            return candidate
        if candidate.defeat_state != 'dead':
            logic.effect_events.append({'type':'turn_skipped','target_name':candidate.name,'reason':'无法行动，仍结算回合末事件'})
            repeat_saves(logic,candidate.combatant_id,'回合结束')
    encounter.current_combatant_id = None
    return None


def advance_time(logic, seconds):
    if seconds <= 0 or seconds > 86400:
        raise ValueError('时间推进须在 1 秒至 1 天之间。')
    if logic.state.encounter and logic.state.encounter.active:
        raise ValueError('战斗中必须按先攻推进回合，不能跳过回合推进时间。')
    end = logic.state.rules_time_seconds + seconds
    # 非战斗的持续控制效果仍按六秒一轮提供重复豁免；没有效果时直接推进。
    while logic.state.active_spell_effects:
        cleanup(logic)
        if not logic.state.active_spell_effects:
            break
        next_at = min(min(e.expires_at_seconds, e.next_save_at_seconds or logic.state.rules_time_seconds+6) for e in logic.state.active_spell_effects)
        if next_at > end:
            break
        logic.state.rules_time_seconds = max(logic.state.rules_time_seconds, next_at)
        expire(logic)
        targets = {e.target_id for e in logic.state.active_spell_effects if e.next_save_at_seconds <= logic.state.rules_time_seconds}
        for ref in targets:
            repeat_saves(logic,ref,'回合结束')
    logic.state.rules_time_seconds = end
    expire(logic)
    return effect_patch(logic)
