"""离线合并法术目录：运行时不再合并多个来源。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re


def spell_identity(spell):
    name = str(spell.get('nameEN') or '').strip()
    if not name:
        raise ValueError('合并法术需要稳定的英文标识 nameEN')
    return re.sub(r'\s+', ' ', name.replace('’', "'").replace('‘', "'")).casefold()


def merge_catalogs(primary, legacy):
    """主目录内容优先；旧目录补全字段和别名，ID冲突须人工核对。"""
    result = deepcopy(primary)
    result['SPELL_DATABASE'] = {}
    global_aliases, global_ids, global_levels = {}, {}, {}
    for catalog in (primary, legacy):
        database = catalog.get('SPELL_DATABASE')
        if not isinstance(database, dict):
            raise ValueError('法术目录缺少 SPELL_DATABASE')
        for group, spells in database.items():
            if not isinstance(spells, list):
                raise ValueError(f'{group}法表不是列表')
            rows = result['SPELL_DATABASE'].setdefault(group, [])
            index = {spell_identity(spell):spell for spell in rows}
            for spell in spells:
                key = spell_identity(spell)
                if key in global_levels and global_levels[key] != spell['level']:
                    raise ValueError(f"{spell['nameEN']}的环级冲突")
                global_levels[key] = spell['level']
                if spell.get('id'):
                    if key in global_ids and global_ids[key] != spell['id']:
                        raise ValueError(f"{spell['nameEN']}的已有ID冲突")
                    global_ids[key] = spell['id']
                global_aliases.setdefault(key, set()).update([spell['name'], spell['nameEN'], *spell.get('aliases', [])])
                if key in index:
                    current = index[key]
                    for field, value in spell.items():
                        if field not in current:
                            current[field] = deepcopy(value)
                else:
                    current = deepcopy(spell)
                    rows.append(current)
                    index[key] = current
    for spells in result['SPELL_DATABASE'].values():
        for spell in spells:
            key = spell_identity(spell)
            spell['aliases'] = sorted(global_aliases[key] - {spell['name'],spell['nameEN']})
            if key in global_ids:
                spell['id'] = global_ids[key]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = merge_catalogs(json.loads(args.catalog.read_text(encoding='utf-8')),
                            json.loads(args.legacy.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    unique = {spell_identity(spell) for spells in result['SPELL_DATABASE'].values() for spell in spells}
    print(f'合并完成：{len(unique)}个法术，{sum(map(len,result["SPELL_DATABASE"].values()))}个职业条目')


if __name__ == '__main__':
    main()
