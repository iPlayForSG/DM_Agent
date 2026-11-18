"""有来源的通用法术效果执行器：按规则数据处理豁免、条件与触发事件。"""
from uuid import uuid4
import re

from models import ActiveSpellEffect
from roll_capture import dice_context
from scene_actors import creature_type
from spell_rules import RuleConflict, RulesUnavailable

ALIASES = {"失能":"Incapacitated", "倒地":"Prone", "魅惑":"Charmed", "麻痹":"Paralyzed",
           "隐形":"Invisible", "恐慌":"Frightened", "昏迷":"Unconscious", "中毒":"Poisoned",
           "目盲":"Blinded", "耳聋":"Deafened", "束缚":"Restrained", "震慑":"Stunned"}
CONDITIONS = tuple(ALIASES.values()) + ("Heroism",)
SAVE_LABELS = {"strength":"力量", "dexterity":"敏捷", "constitution":"体质", "intelligence":"智力", "wisdom":"感知", "charisma":"魅力"}
EVENT_NAMES = {"受到伤害":"target_damaged", "回合结束":"target_turn_end"}


def canonical_condition(name):
    return ALIASES.get(name, next((value for value in CONDITIONS if value.casefold() == str(name).casefold()), name))


def actor(logic, ref):
    return logic.get_character(ref) or logic.get_combatant(ref)


def actor_id(logic, ref):
    value = actor(logic, ref)
    if value is None:
        raise ValueError(f"Spell target not found: {ref}; register the established scene actor first")
    return getattr(value, 'character_id', '') or value.linked_character_id or value.combatant_id


def sync(logic, value):
    if hasattr(value, 'character_id'):
        logic._sync_combatant_from_character(value)
    else:
        logic._sync_character_from_combatant(value)


def effect_patch(logic):
    state = logic.state
    patch = {"active_character_id": state.active_character_id,
             "granted_dice": [bonus.model_dump(mode='json') for bonus in state.granted_dice],
             "active_spell_effects": [effect.model_dump(mode='json') for effect in state.active_spell_effects],
             "spell_cast_history": list(state.spell_cast_history), "rules_time_seconds": state.rules_time_seconds,
             "scene_actors": {key: value.model_dump(mode='json') for key, value in state.scene_actors.items()},
             "characters": {key: {"status_effects": list(value.status_effects), "concentration_spell": value.concentration_spell,
                                  "concentration_spell_level": value.concentration_spell_level, "temp_hp": value.temp_hp,
                                  "temp_hp_source": value.temp_hp_source, "hp_current": value.hp_current} for key, value in state.characters.items()}}
    if state.encounter:
        patch['encounter'] = {"combatants": {key: {"status_effects": list(value.status_effects), "temp_hp": value.temp_hp,
                                                  "temp_hp_source": value.temp_hp_source, "hp_current": value.hp_current} for key, value in state.encounter.combatants.items()}}
    return patch


def end_effect(logic, effect, reason):
    if effect not in logic.state.active_spell_effects:
        return
    logic.state.active_spell_effects.remove(effect)
    value = actor(logic, effect.target_id)
    for condition in effect.added_conditions:
        successor = next((other for other in logic.state.active_spell_effects if other.target_id == effect.target_id and condition in other.conditions), None)
        if successor:
            if condition not in successor.added_conditions:
                successor.added_conditions.append(condition)
        elif value:
            value.status_effects = [status for status in value.status_effects if canonical_condition(status) != condition]
    if value:
        if value.temp_hp_source == effect.effect_id:
            value.temp_hp = 0
            value.temp_hp_source = ""
        sync(logic, value)
    caster = logic.state.characters.get(effect.caster_id)
    if effect.requires_concentration and caster and caster.concentration_spell == effect.spell_name and not any(
            other.requires_concentration and other.caster_id == effect.caster_id and other.spell_name == effect.spell_name for other in logic.state.active_spell_effects):
        caster.concentration_spell = ''; caster.concentration_spell_level = 0
    logic.effect_events.append({'type':'effect_ended', 'spell_name':effect.spell_name,
                               'target_name':value.name if value else effect.target_id, 'reason':reason})


def end_concentration(logic, caster_id, reason='停止专注'):
    caster = logic._concentration_character(caster_id)
    if not caster:
        raise ValueError(f"Spell caster not found: {caster_id}")
    for effect in list(logic.state.active_spell_effects):
        if effect.caster_id == caster.character_id and effect.requires_concentration:
            end_effect(logic, effect, reason)
    caster.concentration_spell = ''; caster.concentration_spell_level = 0
    return effect_patch(logic)


def cleanup(logic):
    for effect in list(logic.state.active_spell_effects):
        caster, target = actor(logic, effect.caster_id), actor(logic, effect.target_id)
        if not caster or not target or target.defeat_state == 'dead':
            end_effect(logic, effect, '目标或来源不再有效')
        elif effect.requires_concentration and (getattr(caster, 'concentration_spell', '') != effect.spell_name
                or caster.hp_current <= 0 or logic.is_incapacitated(caster) or caster.defeat_state == 'dead'):
            end_effect(logic, effect, '专注结束')


def expire(logic, current_ref=None):
    from d20_bonuses import expire as expire_dice
    expire_dice(logic.state)
    for effect in list(logic.state.active_spell_effects):
        if effect.expires_at_seconds <= logic.state.rules_time_seconds and (current_ref is None or effect.caster_id == current_ref):
            end_effect(logic, effect, '持续时间结束')


def in_combat_against_party(logic, caster_id, target_id):
    encounter = logic.state.encounter
    if not encounter or not encounter.active:
        return False
    target = encounter.combatants.get(target_id)
    caster = next((value for value in encounter.combatants.values() if value.combatant_id == caster_id or value.linked_character_id == caster_id), None)
    return bool(caster and target and target.side == 'enemy' and caster.side == 'party')


def dispatch(logic, event, source_ref='', target_ref='', amount=0):
    # 外部伤害来源可以只有标签；目标仍必须是已登记的权威实体。
    source = actor_id(logic, source_ref) if source_ref and actor(logic, source_ref) else source_ref
    target = actor_id(logic, target_ref) if target_ref else ''
    source_actor = actor(logic, source) if source else None
    for effect in list(logic.state.active_spell_effects):
        events = set(effect.end_events)
        caster_event = source == effect.caster_id
        target_event = source == effect.target_id
        end = (event == 'attack_roll' and ((caster_event and 'caster_attack_roll' in events) or (target_event and 'target_attack_roll' in events)))
        end |= event == 'cast_spell' and target_event and 'target_cast_spell' in events
        end |= event == 'forces_save' and caster_event and 'caster_forces_save' in events
        if event == 'damage' and amount > 0:
            ally = source in logic.state.characters or bool(source_actor and getattr(source_actor, 'side', '') == 'party')
            end |= target == effect.target_id and 'target_damaged' in events
            end |= caster_event and 'caster_dealt_damage' in events
            end |= target_event and 'target_dealt_damage' in events
            end |= target == effect.target_id and (caster_event or ally) and 'caster_or_ally_harmed_target' in events
        if end:
            end_effect(logic, effect, {'attack_roll':'攻击触发结束', 'cast_spell':'施法触发结束', 'forces_save':'迫使生物豁免触发结束', 'damage':'伤害触发结束'}[event])


def modifiers_for(logic, target_ref, key):
    identifier = actor_id(logic, target_ref)
    # 同名法术重复覆盖不叠加；不同来源的独立规则仍分别生效。
    grouped = {}
    for effect in logic.state.active_spell_effects:
        if effect.target_id == identifier and key in effect.modifiers:
            grouped[effect.rule_id or effect.spell_name] = effect.modifiers[key]
    return list(grouped.values())


def require_harm_allowed(logic, source_ref, target_ref):
    if not actor(logic, source_ref):
        return
    source, target = actor_id(logic, source_ref), actor_id(logic, target_ref)
    if any(effect.target_id == source and effect.caster_id == target and 'Charmed' in effect.conditions
           for effect in logic.state.active_spell_effects):
        raise RuleConflict('受魅惑的生物不能攻击魅惑自己的来源，或以有害能力、魔法针对该来源。')


def _save(logic, effect, trigger, mode='normal', automatic=None):
    value = actor(logic, effect.target_id)
    if not value:
        raise ValueError('Spell target no longer exists')
    dispatch(logic, 'forces_save', source_ref=effect.caster_id, target_ref=effect.target_id)
    conditions = {canonical_condition(status) for status in value.status_effects}
    if automatic is None and effect.save_name in {'strength', 'dexterity'} and conditions & {'Paralyzed', 'Stunned', 'Unconscious'}:
        automatic = (False, '目标状态使该豁免自动失败')
    if automatic is not None:
        result = {'target_name': value.name, 'save_name': effect.save_name, 'dc': effect.save_dc,
                  'success': automatic[0], 'automatic': True, 'reason': automatic[1]}
        summary = f"{value.name} {SAVE_LABELS.get(effect.save_name, effect.save_name)}豁免自动{'成功' if automatic[0] else '失败'}：{automatic[1]}"
    else:
        if hasattr(value, 'character_id'):
            modifier = logic._character_save_modifier(value, effect.save_name)
        else:
            from rules_catalog import ABILITY_ALIAS
            modifier = next((int(number) for key, number in value.saving_throws.items() if ABILITY_ALIAS.get(key, key).casefold() == effect.save_name), logic._ability_modifier_from_stats(value.stats, effect.save_name))
        with dice_context(reason=f'{effect.spell_name}：{trigger}', visibility='public'):
            result = logic.roll_saving_throw(effect.target_id, effect.save_name, modifier, effect.save_dc, mode)
        summary = f"{value.name} {SAVE_LABELS.get(effect.save_name, effect.save_name)}豁免{'（优势）' if mode == 'advantage' else ''} {result['total']} vs DC {effect.save_dc} -> {'成功' if result['success'] else '失败'} | {effect.spell_name}：{trigger}"
    logic.effect_events.append({'type':'spell_save', 'spell_name':effect.spell_name, 'trigger':trigger, 'summary':summary, **result})
    return result


def repeat_saves(logic, target_ref, trigger):
    cleanup(logic)
    identifier = actor_id(logic, target_ref)
    event = EVENT_NAMES.get(trigger, trigger)
    for effect in list(logic.state.active_spell_effects):
        if effect.target_id == identifier and event in effect.repeat_saves:
            if _save(logic, effect, trigger, effect.repeat_saves[event])['success']:
                end_effect(logic, effect, '豁免成功')
            elif event == 'target_turn_end':
                effect.next_save_at_seconds = logic.state.rules_time_seconds + 6


def apply_ongoing(logic, target_ref, event):
    for effect in list(logic.state.active_spell_effects):
        if effect.target_id != actor_id(logic, target_ref):
            continue
        for operation in effect.ongoing:
            if operation.get('event') != event:
                continue
            if operation['kind'] == 'temp_hp':
                value = actor(logic, effect.target_id)
                amount = max(0, effect.spell_modifier)
                if amount > value.temp_hp:
                    value.temp_hp, value.temp_hp_source = amount, effect.effect_id
                    sync(logic, value)


def before_turn(logic, value):
    cleanup(logic)
    identifier = getattr(value, 'linked_character_id', None) or getattr(value, 'character_id', None) or value.combatant_id
    for effect in list(logic.state.active_spell_effects):
        if effect.caster_id == identifier and 'caster_turn_start' in effect.end_events:
            end_effect(logic, effect, '施法者下一回合开始')
    expire(logic, identifier)
    present = {value.linked_character_id for value in logic.state.encounter.combatants.values()} if logic.state.encounter else set()
    for effect in list(logic.state.active_spell_effects):
        if effect.caster_id not in present and effect.expires_at_seconds <= logic.state.rules_time_seconds:
            end_effect(logic, effect, '持续时间结束')
    apply_ongoing(logic, identifier, 'target_turn_start')


def immunity_conditions(logic, target):
    result = {canonical_condition(value) for value in getattr(target, 'condition_immunities', [])}
    template_id = getattr(target, 'monster_template_id', '')
    if template_id:
        from storage import MonsterStorage
        template = logic.state.monster_templates.get(template_id) or MonsterStorage().load_monster(template_id)
        if template:
            result.update(canonical_condition(value) for value in template.condition_immunities)
    target_id = actor_id(logic, getattr(target, 'character_id', '') or target.combatant_id)
    for effect in logic.state.active_spell_effects:
        if effect.target_id == target_id:
            result.update(effect.immunities)
    return result


def validate_targets(logic, caster, references, slot, rule):
    if not references and rule.get('default_target') == 'self':
        references = [caster.character_id]
    count = int(rule.get('target_base', 1)) + max(0, slot - int(rule.get('slot_base', slot))) * int(rule.get('target_per_slot', 0))
    if count and not references:
        raise ValueError('法术必须指定 target_ref 或 target_refs；请先登记已确认的场景目标。')
    ids = [actor_id(logic, ref) for ref in references]
    if rule.get('target_self') and ids != [caster.character_id]:
        raise RuleConflict('该法术只能以施法者自身为目标。')
    if len(ids) != len(set(ids)) or len(ids) > count:
        raise RuleConflict(f'该法术本次最多选择{count}个不同目标，请调整目标数量。')
    for ref in ids:
        value = actor(logic, ref)
        if rule.get('save') or any(op['kind'] == 'damage' for op in rule.get('effects', [])):
            require_harm_allowed(logic, caster.character_id, ref)
        if value.defeat_state == 'dead':
            raise RuleConflict('该法术不能以尸体为目标，请调整行动。')
        kind = 'humanoid' if hasattr(value, 'character_id') else creature_type(value.creature_type)
        if (rule.get('target_types') or 'not_humanoid' in rule.get('auto_save', [])) and not kind:
            raise ValueError('目标生物类型尚未登记，无法判断该法术是否合法')
        if rule.get('target_types') and kind not in rule['target_types']:
            raise RuleConflict(f"{value.name}的生物类型不符合该法术的目标限制，请调整行动。")
    return ids


def amount_expression(operation, slot, modifier):
    base = operation.get('dice', '')
    if not base:
        return str(max(0, modifier))
    match = re.fullmatch(r'(\d+)d(\d+)([+-]\d+)?', base)
    if not match:
        raise RulesUnavailable('法术效果骰式不受支持')
    count, sides, fixed = int(match[1]), int(match[2]), int(match[3] or 0)
    if operation.get('upcast_dice'):
        increase = re.fullmatch(r'(\d+)d(\d+)', operation['upcast_dice'])
        if not increase or int(increase[2]) != sides:
            raise RulesUnavailable('升环骰式不受支持')
        count += max(0, slot - operation.get('slot_base', slot)) * int(increase[1])
    if operation.get('modifier') == 'spellcasting':
        fixed += modifier
    return f'{count}d{sides}' + (f'{fixed:+d}' if fixed else '')


def apply_rule(logic, caster, spell_name, target_ids, slot, rule, save_dc, modifier):
    from game_logic import DiceRoller
    cast_id = uuid4().hex
    for target_id in target_ids:
        target = actor(logic, target_id)
        has_ticks = 'target_turn_end' in rule.get('repeat_saves', {}) or bool(rule.get('ongoing'))
        effect = ActiveSpellEffect(effect_id=uuid4().hex, cast_id=cast_id, spell_name=spell_name, rule_id=rule['id'],
            caster_id=caster.character_id, target_id=target_id, save_name=rule.get('save', ''), save_dc=save_dc,
            requires_concentration=bool(rule.get('concentration')), repeat_saves=rule.get('repeat_saves', {}),
            end_events=rule.get('end_events', []), immunities=rule.get('immunities', []), ongoing=rule.get('ongoing', []),
            spell_modifier=modifier, modifiers=rule.get('modifiers', {}), kind=rule.get('kind', 'debuff'), description=rule.get('description', ''),
            expires_at_seconds=logic.state.rules_time_seconds + int(rule.get('duration', 0)),
            next_save_at_seconds=logic.state.rules_time_seconds + 6 if has_ticks else 0)
        saved = False
        if rule.get('save'):
            automatic = None
            target_type = 'humanoid' if hasattr(target, 'character_id') else creature_type(target.creature_type)
            fighting = in_combat_against_party(logic, caster.character_id, target_id)
            checks = {'not_humanoid': target_type != 'humanoid', 'fighting_caster': fighting,
                      'same_spell_24h': any(entry['rule_id'] == rule['id'] and entry['caster_id'] == caster.character_id and entry['target_id'] == target_id
                                            and entry['at'] >= logic.state.rules_time_seconds - 86400 for entry in logic.state.spell_cast_history)}
            reasons = {'not_humanoid':'目标不是类人生物', 'fighting_caster':'目标正在与施法者一方战斗', 'same_spell_24h':'过去24小时内已对该目标施放过此法术'}
            for condition in rule.get('auto_save', []):
                if checks.get(condition):
                    automatic = (True, reasons[condition]); break
            mode = 'advantage' if any(checks.get(condition) for condition in rule.get('save_advantage', [])) else 'normal'
            saved = _save(logic, effect, '初次施法', mode, automatic)['success']
        for operation in rule.get('effects', []):
            if operation['kind'] == 'conditions' and not saved:
                immunities = immunity_conditions(logic, target)
                effect.conditions.extend(canonical_condition(value) for value in operation['values'] if canonical_condition(value) not in immunities)
                if immunities & {canonical_condition(value) for value in operation['values']}:
                    logic.effect_events.append({'type':'effect_immunity','spell_name':spell_name,'target_name':target.name,'conditions_applied':effect.conditions})
            elif operation['kind'] in {'damage', 'healing'}:
                if saved and not operation.get('save_multiplier'):
                    continue
                expression = amount_expression(operation, slot, modifier)
                with dice_context(kind='damage' if operation['kind'] == 'damage' else 'healing', actor=caster.name, target=target.name,
                                  label='法术伤害' if operation['kind'] == 'damage' else '法术治疗', reason=spell_name, dc=None):
                    total, detail = DiceRoller.roll(expression)
                amount = max(0, int(total * (operation.get('save_multiplier', 0) if saved else 1)))
                result = logic.update_target_hp(target_id, -amount if operation['kind'] == 'damage' else amount)
                if operation['kind'] == 'damage':
                    dispatch(logic, 'damage', caster.character_id, target_id, amount)
                logic.effect_events.append({'type':operation['kind'], 'spell_name':spell_name, 'target_name':target.name,
                    'expression':expression, 'total':amount, 'detail':detail, 'damage_type':operation.get('damage_type', '')})
        if not saved and (effect.conditions or effect.immunities or effect.ongoing or effect.modifiers):
            existing = {canonical_condition(value) for value in target.status_effects}
            effect.added_conditions = [value for value in effect.conditions if value not in existing]
            target.status_effects.extend(effect.added_conditions)
            if rule.get('duration', 0) > 0:
                logic.state.active_spell_effects.append(effect)
            sync(logic, target)
            target_caster = logic._concentration_character(target_id)
            if target_caster:
                logic._clear_incapacitated_concentration(target_caster)
        logic.state.spell_cast_history.append({'rule_id':rule['id'], 'caster_id':caster.character_id, 'target_id':target_id, 'at':logic.state.rules_time_seconds})
    logic.state.spell_cast_history = [entry for entry in logic.state.spell_cast_history if entry['at'] >= logic.state.rules_time_seconds - 86400]
    cleanup(logic)
    if rule.get('concentration') and not any(effect.cast_id == cast_id for effect in logic.state.active_spell_effects):
        if caster.concentration_spell == spell_name:
            caster.concentration_spell = ''; caster.concentration_spell_level = 0
    return effect_patch(logic)


def preserve_manual_condition(logic, target_ref, status):
    identifier = actor_id(logic, target_ref)
    for effect in logic.state.active_spell_effects:
        if effect.target_id == identifier:
            effect.added_conditions = [value for value in effect.added_conditions if value != canonical_condition(status)]


def require_condition_removable(logic, target_ref, status):
    identifier = actor_id(logic, target_ref)
    if any(effect.target_id == identifier and canonical_condition(status) in effect.conditions for effect in logic.state.active_spell_effects):
        raise RuleConflict('该状态仍由持续法术维持，须按来源规则解除，不能直接移除。')


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
        next_at = min(min(e.expires_at_seconds, e.next_save_at_seconds or e.expires_at_seconds) for e in logic.state.active_spell_effects)
        if next_at > end:
            break
        logic.state.rules_time_seconds = max(logic.state.rules_time_seconds, next_at)
        expire(logic)
        targets = {e.target_id for e in logic.state.active_spell_effects if e.next_save_at_seconds > 0 and e.next_save_at_seconds <= logic.state.rules_time_seconds}
        for ref in targets:
            repeat_saves(logic,ref,'回合结束')
            apply_ongoing(logic,ref,'target_turn_start')
        for effect in logic.state.active_spell_effects:
            if effect.next_save_at_seconds and effect.next_save_at_seconds <= logic.state.rules_time_seconds:
                effect.next_save_at_seconds = logic.state.rules_time_seconds + 6
    logic.state.rules_time_seconds = end
    expire(logic)
    return effect_patch(logic)
