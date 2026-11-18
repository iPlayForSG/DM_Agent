"""从用户提供的2024中文法术详述生成完整中文目录；缺条目时停止，避免静默漏译。"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from functools import lru_cache

FIELDS = {'施法时间':'castingTime', '施法距离':'range', '法术成分':'components', '持续时间':'duration'}
KEY_ALIASES = {'lightningarrows':'lightningarrow'}
TERMS = {'AC':'护甲等级', 'HP':'生命值', 'CR':'挑战等级', 'XP':'经验值', 'PB':'熟练加值',
         'DC':'难度等级', 'DM':'主持人', 'GP':'金币', 'SP':'银币', 'CP':'铜币', 'EP':'琥珀金币', 'PP':'铂金币'}
EXTRA_TERMS = {'Magic Missle':'魔法飞弹', 'arcane locks':'奥术锁', 'Protection from Evil':'防护善恶',
    'Potion of Healing':'治疗药水', 'Half Cover':'半身掩护', 'City of Sigil':'印记城',
    'Feeblemind':'弱智术', 'Branding Smite':'印记斩', 'PHB':'玩家手册',
    'Aberration':'异怪', 'Undead':'亡灵', 'Hostile':'敌对', 'Large':'大型', 'labyrinth':'迷宫', 'Invisible':'隐形',
    'Yes':'是', 'No':'不是', 'Maybe':'可能', 'Never':'不可能', 'Irrelevant':'无关', 'Unclear':'不清楚'}
DISPLAY_FIELDS = ('name','school','castingTime','range','duration','components','desc','higherLevels')


def spell_key(value):
    key = re.sub(r'[^a-z0-9]', '', str(value).casefold())
    return KEY_ALIASES.get(key, key)


def english_pattern(value):
    return r'(?<![A-Za-z])' + r'\s*'.join(re.escape(part) for part in value.split()) + r'(?![A-Za-z])'


def source_entries(directory):
    records = {}
    for level in range(10):
        path = directory / f'{level}环.md'
        text = path.read_text(encoding='utf-8-sig')
        headings = list(re.finditer(r'^#### ([^\n|]+)\|([^\n]+)\n', text, re.M))
        if not headings:
            raise ValueError(f'{path.name}没有可识别的法术详述')
        for i, heading in enumerate(headings):
            body = text[heading.end():headings[i+1].start() if i+1 < len(headings) else len(text)].strip()
            name, english = heading[1].strip(), heading[2].strip()
            key = spell_key(english)
            if key in records:
                raise ValueError(f'重复法术来源：{english}')
            values = {'name':name, 'nameEN':english, 'level':level}
            matches = []
            for label, field in FIELDS.items():
                found = re.search(r'^\*\*'+label+r'[:：]\*\*[ \t]*(?:\n[ \t]*)?([^\n]+)', body, re.M)
                if not found or not found[1].strip():
                    raise ValueError(f'{name}缺少{label}')
                values[field] = found[1].strip()
                matches.append(found)
            school = re.search(r'^\*([^*\n]+)\*',body,re.M)
            if not school:
                raise ValueError(f'{name}缺少学派/职业资料')
            values['school'] = next((v for v in ['防护','咒法','预言','惑控','塑能','幻术','死灵','变化'] if v in school[1]), '')
            classes = re.search(r'[（(]([^）)]+)[）)]',school[1])
            values['classList'] = classes[1].split('、') if classes else []
            values['concentration'] = '专注' in values['duration']
            values['ritual'] = '仪式' in values['castingTime']
            prose = body[max(match.end() for match in matches):].strip()
            # 升环和戏法强化分栏保留完整正文；子标题/召唤物资料卡不会被当成新法术切断。
            upgrade = re.search(r'\*\*(?:升环施法|戏法强化)[。.:：]?\*\*',prose)
            if upgrade:
                end = re.search(r'\n[ \t]*\n',prose[upgrade.start():])
                boundary = upgrade.start()+end.start() if end else len(prose)
                values['desc'] = (prose[:upgrade.start()].rstrip()+'\n\n'+prose[boundary:].lstrip()).strip()
                values['higherLevels'] = prose[upgrade.start():boundary].strip()
            else:
                values['desc'], values['higherLevels'] = prose, ''
            if not values['desc']:
                raise ValueError(f'{name}没有正文')
            values['translation_source'] = f'核心规则/玩家手册2024/法术详述/{path.name}#{name}'
            values['translation_source_sha256'] = hashlib.sha256(body.encode()).hexdigest()
            records[key] = values
    return records


def make_terms(records):
    terms = {entry['nameEN']:entry['name'] for entry in records.values()}
    text = '\n'.join(entry['desc']+'\n'+entry['higherLevels'] for entry in records.values())
    # 源文保留很多中英并列子标题，从明确的粗体/标题边界提取，避免删除普通正文内容。
    text = unwrap_english(text)
    labels = re.findall(r'\*\*([^*]+)\*\*',text) + re.findall(r'^#{5,6} (.+)',text,re.M)
    for label in labels:
        match = re.match(r'^([\u4e00-\u9fff·]+)\s*([A-Za-z][A-Za-z\s\x27’‘\-]*[A-Za-z])(?=[。:：(,]|$)',label)
        if match:
            terms.setdefault(' '.join(match[2].split()),match[1])
    terms.update(EXTRA_TERMS)
    return terms


def unwrap_english(value):
    return re.sub(r'(?<=[A-Za-z\x27’‘])\n[ \t]*(?:>[ \t]*)?(?=[A-Za-z])',' ',value)


@lru_cache(maxsize=8)
def compiled_terms(items):
    return [(chinese, re.compile(re.escape(chinese)+r'\s*'+english_pattern(english),re.I),
             re.compile(english_pattern(english),re.I))
            for english,chinese in sorted(items,key=lambda item:len(item[0]),reverse=True)]


def clean_chinese(value, terms):
    value = str(value).replace('\r\n','\n')
    # 引用块的折行先接回去，保证双语术语不会被换行和引用符拆断。
    value = unwrap_english(value)
    def label_only(match):
        # 同一个英文词可能也是法术名（如Resistance）；并列小标题直接保留其原有中文。
        return re.sub(r'^([\u4e00-\u9fff·]+)\s*[A-Za-z][A-Za-z\s\x27’‘\-]*[A-Za-z](?=[。:：(,]|$)',r'\1',match[0])
    value = re.sub(r'\*\*([^*]+)\*\*',lambda m:'**'+label_only(re.match(r'.*',m[1],re.S))+'**',value)
    value = re.sub(r'(?m)(?<=##### ).+$',label_only,value)
    for chinese, bilingual, pattern in compiled_terms(tuple(terms.items())):
        value = bilingual.sub(chinese,value)
        value = pattern.sub(chinese,value)
    for english, chinese in TERMS.items():
        value = re.sub(r'(?<![A-Za-z])'+english+r'(?![A-Za-z])',chinese,value)
    value = value.replace('‐','-').replace('−','-')
    value = value.translate(str.maketrans({'(':'（',')':'）',',':'，',':':'：',';':'；'}))
    # 中文标点紧贴强调闭合符会让CommonMark把星号当正文；移到强调范围外，文字含义不变。
    value = re.sub(r'(\*{1,2})([^*\n]+?)([。:：，；]+)\1',r'\1\2\1\3',value)
    return value.strip()


def translate(catalog, records, alias_catalog=None):
    terms = make_terms(records)
    translated = deepcopy(catalog)
    missing = set()
    cleaned = {}
    known_aliases = {}
    for data in [catalog, alias_catalog or {'SPELL_DATABASE':{}}]:
        for spells in data['SPELL_DATABASE'].values():
            for item in spells:
                known_aliases.setdefault(spell_key(item.get('nameEN') or item['name']),set()).update([item['name'],*item.get('aliases',[])])
    for spells in translated['SPELL_DATABASE'].values():
        for spell in spells:
            key = spell_key(spell.get('nameEN') or spell['name'])
            source = records.get(key)
            if not source:
                missing.add(spell.get('nameEN',spell['name']))
                continue
            if spell['level'] != source['level']:
                raise ValueError(f'{spell["name"]}的环级与来源不同')
            aliases = set(known_aliases[key])
            if source['nameEN'] != spell.get('nameEN'):
                aliases.add(source['nameEN'])
            if spell['name'] != source['name']:
                aliases.add(spell['name'])
            aliases.discard(source['name'])
            if key not in cleaned:
                cleaned[key] = {field:clean_chinese(source[field],terms) for field in DISPLAY_FIELDS}
            for field in DISPLAY_FIELDS:
                spell[field] = cleaned[key][field]
                if field not in {'desc','higherLevels'}:
                    spell[field] = re.sub(r'[*`]', '', spell[field])
            for field in ['concentration','ritual','classList','translation_source','translation_source_sha256']:
                spell[field] = deepcopy(source[field])
            spell['aliases'] = sorted(aliases)
            spell['rules_text_available'] = True
            spell['text_language'] = 'zh-Hans'
            spell['text_source'] = 'user_provided_local_phb2024'
    if missing:
        raise ValueError('本地来源缺少法术：'+', '.join(sorted(missing)))
    translated['source'] = '2024法术目录；中文资料依据用户提供的本地玩家手册法术详述。英文标识及原始来源元数据保留。'
    return translated


def merge_local(local, supplement):
    try:
        from .merge_spell_catalogs import merge_catalogs
    except ImportError:
        from merge_spell_catalogs import merge_catalogs
    return merge_catalogs(supplement, local)


def audit(catalog):
    unique = {spell_key(s['nameEN']):s for spells in catalog['SPELL_DATABASE'].values() for s in spells}
    untranslated = []
    for spell in unique.values():
        for field in DISPLAY_FIELDS:
            value = re.sub(r'\b\d*[dD]\d+\b','',spell.get(field,''))
            if field == 'components':
                value = re.sub(r'(?<![A-Za-z])[VSM](?![A-Za-z])','',value)
            words = re.findall(r'[A-Za-z]{2,}(?:[ \t]+[A-Za-z]{2,})*',value)
            if words:
                untranslated.append({'name':spell['name'],'field':field,'english':words})
    return {'unique_spells':len(unique),'class_entries':sum(map(len,catalog['SPELL_DATABASE'].values())),
            'missing_descriptions':[s['name'] for s in unique.values() if not s.get('desc')],
            'untranslated':untranslated}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--local',type=Path)
    parser.add_argument('--aliases-from',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--audit',type=Path)
    args = parser.parse_args()
    records = source_entries(args.source)
    catalog = json.loads(args.catalog.read_text(encoding='utf-8'))
    if args.local:
        catalog = merge_local(json.loads(args.local.read_text(encoding='utf-8')),catalog)
    alias_catalog = json.loads(args.aliases_from.read_text(encoding='utf-8')) if args.aliases_from else None
    result = translate(catalog,records,alias_catalog)
    report = audit(result)
    if args.audit:
        args.audit.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if report['untranslated'] or report['missing_descriptions']:
        raise ValueError('译文仍有缺失或未翻译字段，请查看审计报告后处理')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='untranslated'},ensure_ascii=False))
    print('Fields requiring review:',len(report['untranslated']))


if __name__ == '__main__':
    main()
