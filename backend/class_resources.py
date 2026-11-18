"""职业资源的等级派生与旧角色迁移；不执行建卡重置或休息恢复。"""
from functools import lru_cache
import json
from pathlib import Path

VERSION = 1
LABELS = {'Bardic Inspiration':'吟游激励','Second Wind':'回气','Action Surge':'动作如潮','Indomitable':'不屈',
 'Channel Divinity':'引导神力','Wild Shape':'荒野形态','Focus Points':'专注点','Lay on Hands':'圣疗',
 'Favored Enemy':'宿敌（猎人印记）','Sorcery Points':'术法点','Innate Sorcery':'先天术法',
 'Arcane Recovery':'奥术回想','Uncanny Metabolism':'异能代谢','Sorcerous Restoration':'术法复苏',
 'Magical Cunning':'秘法回流','Contact Patron':'联系宗主','Divine Intervention':'神圣干预',
 'Divine Smite':'至圣斩（免费施法）','Find Steed':'寻获坐骑（免费施法）','Tireless':'不倦',
 "Nature's Veil":'自然面纱','Stroke of Luck':'幸运一击','Superiority Dice':'卓越骰','Psionic Energy Dice':'灵能骰'}
FIXED_ACTIONS = {'Bardic Inspiration':'bonus_action','Innate Sorcery':'bonus_action','Tireless':'action',
 "Nature's Veil":'bonus_action','Uncanny Metabolism':'free','Magical Cunning':'free','Sorcerous Restoration':'free',
 'Arcane Recovery':'free','Contact Patron':'free','Stroke of Luck':'free','Indomitable':'free'}


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'data/level_progression_2024.json').read_text(encoding='utf-8'))['classes']


def resource_profile(name, level, scores, subclass_id='', arcanum=None):
    data=catalog().get(name)
    if not data or not 1 <= level <= 20:
        return {}
    metrics=data['metrics'][level-1]
    result={}
    def add(key,total,recovery='long_rest',description='',short=0,display=''):
        if total>0:
            result[key]={'current_value':int(total),'max_value':int(total),'recovery':recovery,
                'short_rest_recovery':short,'description':description,'display_name':display or LABELS.get(key,key)}
    wisdom=max(1,(scores['wisdom']-10)//2)
    if name=='Bard':
        add('Bardic Inspiration',max(1,(scores['charisma']-10)//2),'short_rest' if level>=5 else 'long_rest',
            f"激励骰{metrics['Bardic Die']}。附赠动作给予60尺内另一名能看见或听见你的生物；不能给自己。1小时内一次D20检定失败后可消耗该骰；同一生物至多持有一枚。")
    for key in ('Second Wind','Channel Divinity','Wild Shape','Focus Points','Sorcery Points'):
        count=metrics.get(key,0)
        if str(count).isdigit() and int(count)>0:
            short=1 if key in {'Second Wind','Channel Divinity','Wild Shape'} else 0
            desc='短休恢复1次，长休恢复全部。' if short else '短休或长休恢复全部。' if key=='Focus Points' else '长休恢复全部；不同能力按实际消耗点数结算。'
            add(key,int(count),'short_rest' if key=='Focus Points' else 'long_rest',desc,short)
    if name=='Fighter':
        if level>=2:add('Action Surge',2 if level>=17 else 1,'short_rest','不消耗动作；本回合额外一个动作，不能用于魔法动作；每回合至多一次。')
        if level>=9:add('Indomitable',3 if level>=17 else 2 if level>=13 else 1,description='豁免失败后重掷，并增加战士等级；必须使用新结果。')
    if name=='Paladin':
        add('Lay on Hands',5*level,description='圣疗池；附赠动作触碰生物，按恢复生命的点数消耗；解除中毒消耗5点。')
        if level>=2:add('Divine Smite',1,description='每次长休后可不消耗法术位施展一次至圣斩，仍须满足施法触发与动作要求。')
        if level>=5:add('Find Steed',1,description='每次长休后可不消耗法术位施展一次寻获坐骑。')
    if name=='Ranger':
        add('Favored Enemy',metrics['Favored Enemy'],description='无需法术位施展猎人印记的次数；施法动作、目标和专注要求仍适用。')
        if level>=10:add('Tireless',wisdom,description=f'魔法动作获得1d8+{wisdom}点临时生命；使用次数为感知调整值，至少1次。')
        if level>=14:add("Nature's Veil",wisdom,description='附赠动作进入隐形状态，直到下一回合结束。')
    if name=='Wizard':
        add('Arcane Recovery',1,description=f'完成短休时可使用；恢复法术位的环数合计至多{(level+1)//2}，不能恢复6环及以上法术位。长休恢复此次数。')
        if level>=20:
            for number in (1,2):add(f'Signature Spell {number}',1,'short_rest','对应一道已选择的3环招牌法术；两道各自计次，不可互换额度。',display=f'招牌法术{number}（免费施法）')
    if name=='Sorcerer':
        add('Innate Sorcery',2,description='附赠动作激活，持续1分钟；术士法术豁免难度+1、术士法术攻击具有优势。')
        if level>=5:add('Sorcerous Restoration',1,description=f'短休时恢复至多{level//2}点术法点；长休恢复此特性使用次数。')
    if name=='Monk' and level>=2:add('Uncanny Metabolism',1,description='掷先攻时恢复全部专注点，并恢复武艺骰结果加武僧等级的生命；长休恢复此次数。')
    if name=='Warlock':
        if level>=2:add('Magical Cunning',1,description='耗时1分钟；恢复已消耗契约法术位的一半，向上取整。20级改为恢复全部。')
        if level>=9:add('Contact Patron',1,description='免费施放异界探知以联系宗主；长休后可再次使用。')
        for unlock,spell_level in ((11,6),(13,7),(15,8),(17,9)):
            if level>=unlock:add(f'Mystic Arcanum ({spell_level})',1,description=(arcanum or {}).get(str(spell_level),'对应已选择的玄奥秘法'),display=f'{spell_level}环玄奥秘法')
    if name=='Cleric' and level>=10:add('Divine Intervention',1,description='魔法动作选择合规的牧师法术祈求干预；20级祈愿术用法有2d4个长休的额外恢复限制。')
    if name=='Rogue' and level>=20:add('Stroke of Luck',1,'short_rest','D20检定失败后可以将结果视为掷出20。')
    # 已有等级表明确给出的独立子职资源，不能误把偷袭骰、武艺骰当成次数池。
    subclass=next((s for s in data['subclasses'] if s['id']==subclass_id),None) if level>=3 else None
    if subclass and subclass['name'] in {'Psi Warrior','Soulknife'}:
        row=subclass['metrics'][level-1]
        add('Psionic Energy Dice',int(row['Number']),description=f"灵能骰{row['Die Size']}；不同能力按各自规则消耗，短休恢复1枚，长休恢复全部。",short=1)
    if subclass and subclass['name']=='Battle Master':
        add('Superiority Dice',6 if level>=15 else 5 if level>=7 else 4,'short_rest',f"卓越骰{'1d12' if level>=18 else '1d10' if level>=10 else '1d8'}；战技按规则消耗。")
    return result


def migrate_character(character, raw):
    if ('class_resource_version' in raw and character.class_resource_version>=VERSION) or character.class_name not in catalog():
        return
    from models import ResourcePool
    expected=resource_profile(character.class_name,character.level,character.stats.model_dump(),character.subclass_id,character.mystic_arcanum)
    for name,definition in expected.items():
        old=character.resources.get(name)
        if old:
            # 校正容量时保留已消耗量，不能把读取旧存档变成一次免费恢复。
            spent=max(0,old.max_value-old.current_value)
            definition['current_value']=max(0,definition['max_value']-spent)
        character.resources[name]=ResourcePool(**definition)
    if character.class_name=='Druid' and character.level<2:
        character.resources.pop('Wild Shape',None)
    character.class_resource_version=VERSION


def migrate_game(state, raw):
    for key,character in state.characters.items():
        migrate_character(character,raw.get('characters',{}).get(key,{}))
