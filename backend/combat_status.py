"""战斗状态的只读投影；不在浏览器复制效果结算。"""
from game_logic import GameLogic
from library import Library
from spell_effects import actor,actor_id,canonical_condition,is_laughter

CONDITION_INFO = {
 'Dead': ('死亡','debuff','已记录死亡，无法行动。'),
 'Captured': ('被俘','debuff','已记录被俘，按当前被俘状态限制行动。'),
 'Bless': ('祝福','buff','已记录祝福增益，具体效果依来源规则。'),
 'Hasted': ('加速','buff','已记录加速增益，具体效果依来源规则。'),
 'Incapacitated': ('失能','debuff','不能执行动作、附赠动作或反应，不能维持专注。'),
 'Prone': ('倒地','debuff','处于倒地状态；移动与攻击按倒地规则处理。'),
 'Poisoned': ('中毒','debuff','攻击检定与属性检定受到中毒状态影响。'),
 'Frightened': ('恐慌','debuff','受恐慌影响，行动与检定按该状态的规则处理。'),
 'Charmed': ('魅惑','debuff','受到魅惑来源的影响；具体限制见来源效果。'),
 'Unconscious': ('昏迷','debuff','失去意识，无法正常行动。'),
 'Paralyzed': ('麻痹','debuff','失能且无法正常移动，按麻痹规则处理。'),
 'Stunned': ('震慑','debuff','失能，按震慑状态处理。'),
 'Restrained': ('束缚','debuff','移动与攻击受到束缚状态限制。'),
 'Blinded': ('目盲','debuff','无法正常看见，视觉相关行动受限。'),
 'Invisible': ('隐形','buff','已记录隐形；能否被发现仍取决于感官和当前场景。'),
 'Blessed': ('祝福','buff','已记录祝福增益，具体效果依来源规则。'),
 'Haste': ('加速','buff','已记录加速增益，具体效果依来源规则。'),
 'Heroism': ('英雄气概','buff','已记录英雄气概，具体效果依来源规则。'),
}


def combat_status_entries(state, ref):
    logic=GameLogic(state);value=actor(logic,ref)
    if not value:return []
    identifier=actor_id(logic,ref);library=Library();entries=[]
    effects=[e for e in state.active_spell_effects if e.target_id==identifier]
    managed={condition for e in effects for condition in e.conditions}
    for effect in effects:
        source=state.characters.get(effect.caster_id)
        remaining=max(0,effect.expires_at_seconds-state.rules_time_seconds)
        labels=[CONDITION_INFO.get(c,(library.localize_game_terms(c),'status',''))[0] for c in effect.conditions]
        duration=f'剩余至多 {remaining} 秒游戏时间' if remaining else '本轮施法者行动开始时到期'
        entries.append({'id':effect.effect_id,'name':effect.spell_name,'kind':'debuff',
                        'summary':'、'.join(labels)+f' · 感知 DC {effect.save_dc}',
                        'source':f'来源：{source.name if source else effect.caster_id} · {duration}',
                        'description':'回合结束进行感知豁免；受到伤害时立即重掷且具有优势。成功、专注结束或持续时间到期时解除。效果维持时无法主动结束倒地，不会自动丢弃武器。'})
    for status in value.status_effects:
        canonical=canonical_condition(status)
        if canonical in managed:continue
        info=next((v for k,v in CONDITION_INFO.items() if k.casefold()==str(canonical).casefold() or v[0]==canonical),None)
        label,kind,description=info or (library.localize_game_terms(status),'status','已记录的状态；未提供额外来源或持续时间。')
        entries.append({'id':'status:'+status,'name':label,'kind':kind,'summary':description,'description':description,'source':''})
    character=logic._concentration_character(ref)
    if character and character.concentration_spell:
        name=library.localize_game_terms(character.concentration_spell)
        unconfirmed = is_laughter(character.concentration_spell) and not any(e.caster_id == character.character_id for e in state.active_spell_effects)
        entries.append({'id':'concentration','name':'专注：'+name,'kind':'concentration',
                        'summary':'尚无已确认的目标效果' if unconfirmed else '正在维持法术','source':'',
                        'description':'失能、死亡、专注豁免失败或主动结束专注时终止；新专注法术会替换它。'})
    if value.hiding:
        entries.append({'id':'hiding','name':'躲藏中','kind':'buff','summary':f'发现 DC {value.hiding.stealth_total}',
                        'source':'','description':'攻击、言语施法、被发现或暴露可能结束躲藏。'})
    if value.temp_hp>0:
        entries.append({'id':'temp-hp','name':'临时生命','kind':'buff','summary':str(value.temp_hp),'source':'','description':'受到伤害时优先消耗临时生命；不会与另一份临时生命相加。'})
    if character and character.inspiration:
        entries.append({'id':'inspiration','name':'激励','kind':'buff','summary':'可用','source':'','description':'已记录激励，可在规则允许时使用。'})
    return entries
