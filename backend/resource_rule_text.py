"""资源规则原文的只读投影，独立于存档中的次数和旧描述。"""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'data/class_resource_text_2024.json').read_text(encoding='utf-8'))['resources']


def tooltip_fields(class_name, resource_name, level=1, subclass_id=''):
    name='Mystic Arcanum' if resource_name.startswith('Mystic Arcanum (') else 'Signature Spell' if resource_name.startswith('Signature Spell ') else resource_name
    data=catalog()
    entries=data.get(f'{class_name}:{subclass_id}',{}).get(name) or data.get(class_name,{}).get(name,[])
    active=[entry for entry in entries if entry['level']<=level]
    if not active:return {}
    return {'rules_text':'\n\n'.join(entry['text'] for entry in active),
            'rules_source':'《玩家手册2024》 · '+active[0]['source'].split('/')[-1].removesuffix('.md'),
            'rules_source_refs':[{'path':entry['source'],'line':entry['source_line'],'sha256':entry['sha256']} for entry in active]}


def project_resources(resources, class_name, level=1, subclass_id=''):
    return {name:{**pool,**tooltip_fields(class_name,name,level,subclass_id)} for name,pool in resources.items()}
