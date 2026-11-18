"""按能力段落提取本地手册原文，保留原文字词与可核对的来源。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

CLASSES={'Bard':'吟游诗人','Cleric':'牧师','Druid':'德鲁伊','Fighter':'战士','Monk':'武僧',
 'Paladin':'圣武士','Ranger':'游侠','Rogue':'游荡者','Sorcerer':'术士','Warlock':'魔契师','Wizard':'法师'}
BINDINGS={
 'Bard':{'Bardic Inspiration':['Bardic Inspiration','Font of Inspiration','Superior Inspiration']},
 'Cleric':{'Channel Divinity':['Channel Divinity'],'Divine Intervention':['Divine Intervention','Greater Divine Intervention']},
 'Druid':{'Wild Shape':['Wild Shape','Wild Resurgence','Archdruid']},
 'Fighter':{'Second Wind':['Second Wind'],'Action Surge':['Action Surge'],'Indomitable':['Indomitable']},
 'Monk':{'Focus Points':["Monk's Focus",'Heightened Focus','Perfect Focus'],'Uncanny Metabolism':['Uncanny Metabolism']},
 'Paladin':{'Lay on Hands':['Lay on Hands','Restoring Touch'],'Channel Divinity':['Channel Divinity'],
            'Divine Smite':["Paladin's Smite"],'Find Steed':['Faithful Steed']},
 'Ranger':{'Favored Enemy':['Favored Enemy'],'Tireless':['Tireless'],"Nature's Veil":["Nature's Veil"]},
 'Rogue':{'Stroke of Luck':['Stroke of Luck']},
 'Sorcerer':{'Sorcery Points':['Font of Magic'],'Innate Sorcery':['Innate Sorcery','Sorcery Incarnate','Arcane Apotheosis'],
             'Sorcerous Restoration':['Sorcerous Restoration']},
 'Warlock':{'Magical Cunning':['Magical Cunning','Eldritch Master'],'Contact Patron':['Contact Patron'],
             'Mystic Arcanum':['Mystic Arcanum']},
 'Wizard':{'Arcane Recovery':['Arcane Recovery'],'Signature Spell':['Signature Spells']},
 'Fighter:battle-master':{'Superiority Dice':['Combat Superiority','Improved Combat Superiority','Relentless','Ultimate Combat Superiority']},
 'Fighter:psi-warrior':{'Psionic Energy Dice':['Psionic Power']},
 'Rogue:soulknife':{'Psionic Energy Dice':['Psionic Power']},
}
SUB_FILES={'Fighter:battle-master':'战士/战斗大师.md','Fighter:psi-warrior':'战士/灵能武士.md','Rogue:soulknife':'游荡者/魂刃.md'}


def key(value):
    return re.sub('[^a-z]','',value.casefold())


def extract(path, relative):
    text=path.read_text(encoding='utf-8-sig')
    headers=list(re.finditer(r'^\*\*(\d+)级[:：]\s*([^*]+)\*\*',text,re.M))
    sections={}
    for i,header in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(text)
        segment=text[header.start():end].strip()
        # 这段是独立角色扮演侧栏，不属于吟游激励的规则说明。
        if key(header[2])=='bardicinspiration':
            segment=segment.split('**吟游诗人的曲目')[0].rstrip()
        title=' '.join(header[2].split())
        sections[key(title)]={'level':int(header[1]),'title':title,'text':segment,
            'source':f'核心规则/玩家手册2024/角色职业/{relative}',
            'source_line':text.count('\n',0,header.start())+1,
            'sha256':hashlib.sha256(segment.encode('utf-8')).hexdigest()}
    return sections


def build(source):
    result={}
    for owner,resources in BINDINGS.items():
        label=CLASSES[owner.split(':')[0]]
        relative=SUB_FILES.get(owner,f'{label}/{label}.md')
        sections=extract(source/relative,relative)
        result[owner]={}
        for resource,titles in resources.items():
            absent=[title for title in titles if key(title) not in sections]
            if absent:raise ValueError(f'{relative}缺少原文段落：{absent}')
            result[owner][resource]=[sections[key(title)] for title in titles]
    return {'source':'用户提供的本地《玩家手册2024》能力规则原文；不表示重新授权源文。','resources':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=build(args.source)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Imported',sum(len(rows) for rows in data['resources'].values()),'resource rule bindings')


if __name__=='__main__':main()
