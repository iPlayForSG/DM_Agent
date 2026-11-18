"""全目录中文覆盖、旧名兼容，以及提取器保留规则内容的回归。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from library import Library
from spell_rules import declared_spells,rule_for
from rules_catalog import RuleCatalog
from models import Character
from utils.translate_spell_catalog import audit, clean_chinese, make_terms, source_entries, spell_key, translate


class SpellTranslationTests(unittest.TestCase):
    def test_source_necrotic_term_preserves_spell_attack_resolution(self):
        hero=Character(name='合成角色',class_name='Wizard')
        profile=RuleCatalog().get_spell_attack_profile(hero,'Vampiric Touch',3)
        self.assertEqual(profile['damage_expression'],'3d6')
        self.assertEqual(profile['damage_types'],['necrotic'])

    def test_entire_bundled_catalog_has_chinese_display_fields(self):
        data=json.loads((ROOT/'backend/data/spell_catalog_2024.json').read_text(encoding='utf-8'))
        result=audit(data)
        self.assertEqual(result['unique_spells'],391)
        self.assertEqual(result['class_entries'],987)
        self.assertEqual(result['untranslated'],[])
        self.assertEqual(result['missing_descriptions'],[])
        unique={s['nameEN']:s for values in data['SPELL_DATABASE'].values() for s in values}
        self.assertIn('8d6',unique['Fireball']['desc'])
        self.assertIn('异界坐骑',unique['Find Steed']['desc'])
        self.assertIn('| **护甲等级**',unique['Find Steed']['desc'])
        self.assertNotIn('#####',unique['Summon Fiend']['higherLevels'])
        self.assertIn('#####',unique['Summon Fiend']['desc'])
        self.assertIn('金币',unique['Wish']['desc'])
        self.assertNotIn('伤害抗性抵抗术',unique['Wish']['desc'])

    def test_old_character_spell_names_still_resolve_to_new_canonical_name(self):
        library=Library()
        for name in ['Charm Person','魅惑人类','魅惑类人']:
            details=library.get_spell_details(name)
            self.assertEqual(details['name'],'魅惑类人')
            self.assertEqual(rule_for(details)['id'],'charm_person')
        self.assertEqual(library.localize_game_terms('魅惑人类'),'魅惑类人')
        graph={'turn_intent':{'intent_tags':['spell_action']},'user_input':'对地精施放魅惑人类。'}
        self.assertEqual(declared_spells(graph,library),['魅惑类人'])

    def test_source_typo_and_missing_entries_are_explicit(self):
        self.assertEqual(spell_key('Lightning Arrows'),spell_key('Lightning Arrow'))
        with self.assertRaisesRegex(ValueError,'本地来源缺少法术'):
            translate({'SPELL_DATABASE':{'法师':[{'name':'Unknown','nameEN':'Unknown','level':1}]}},{})

    def test_wrapped_bilingual_labels_do_not_corrupt_other_spell_names(self):
        entries={'x':{'nameEN':'Resistance','name':'抵抗术','desc':'**伤害抗性Resistance。**\n**魔法印记Magic\n> Mark。**','higherLevels':''}}
        terms=make_terms(entries)
        text=clean_chinese('**伤害抗性Resistance。**\n**魔法印记Magic\n> Mark。**\n魔法飞弹Magic Missle',terms)
        self.assertEqual(text,'**伤害抗性**。\n**魔法印记**。\n魔法飞弹')

    def test_parser_keeps_stat_block_in_description_and_upcast_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)
            for level in range(10):
                (source/f'{level}环.md').write_text(f'''# {level}环
#### 合成{level}|Synthetic {level}
*塑能 戏法(法师)*
**施法时间:**动作
**施法距离:**30尺
**法术成分:**V、S
**持续时间:**
1小时
造成2d6伤害。
**升环施法。**每升一环增加1d6。

##### 合成数据卡
| 生命值 | 20 |
''',encoding='utf-8')
            records=source_entries(source)
            self.assertEqual(len(records),10)
            record=records['synthetic0']
            self.assertEqual(record['duration'],'1小时')
            self.assertIn('| 生命值 | 20 |',record['desc'])
            self.assertEqual(record['higherLevels'],'**升环施法。**每升一环增加1d6。')


if __name__=='__main__':
    unittest.main()
