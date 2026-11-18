"""资源原文展示不依赖存档旧摘要，也不改动资源计数。"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from models import Character,ResourcePool,Stats,GameState
from resource_rule_text import tooltip_fields,project_resources
from class_resources import resource_profile,catalog
from utils.import_resource_rule_text import extract
import main as api


class ResourceRuleTextTests(unittest.TestCase):
    def test_bard_contains_complete_original_rule_sections_at_correct_levels(self):
        low=tooltip_fields('Bard','Bardic Inspiration',1)
        text=low['rules_text']
        self.assertIn('你可以用语言,音乐或舞蹈的形式对他人进行超自然的激励',text)
        self.assertIn('使用次数Number of',text)
        self.assertIn('更高等级At Higher',text)
        self.assertIn('这可能将失败变为成功',text)
        self.assertNotIn('激励之源',text)
        self.assertIn('激励之源',tooltip_fields('Bard','Bardic Inspiration',5)['rules_text'])
        self.assertIn('《玩家手册2024》',low['rules_source'])

    def test_old_summary_is_overlaid_without_refilling_or_rewriting_state(self):
        hero=Character(name='合成诗人',class_name='Bard',resources={'Bardic Inspiration':ResourcePool(current_value=0,max_value=2,description='旧摘要')})
        raw=hero.model_dump(mode='json');before=deepcopy(raw)
        shown=api._add_display_fields(raw)
        self.assertEqual(raw,before)
        resource=shown['resources']['Bardic Inspiration']
        self.assertEqual(resource['current_value'],0)
        self.assertEqual(resource['description'],'旧摘要')
        self.assertIn('你可以用语言',resource['rules_text'])
        state=GameState(game_id='source-text',characters={hero.character_id:hero},active_character_id=hero.character_id)
        actor=api.action_options_payload(state)['actors'][0]
        self.assertEqual(actor['resources']['Bardic Inspiration']['rules_text'],resource['rules_text'])
        self.assertEqual(hero.resources['Bardic Inspiration'].current_value,0)

    def test_current_supported_resource_bindings_have_source_text(self):
        for owner,data in catalog().items():
            for level in (1,2,3,5,10,15,20):
                for subclass in ['',*[entry['id'] for entry in data['subclasses']]]:
                    for name in resource_profile(owner,level,Stats().model_dump(),subclass):
                        self.assertTrue(tooltip_fields(owner,name,level,subclass),(owner,level,subclass,name))
        custom={'自定义':{'current_value':1,'max_value':2,'description':'自定义说明'}}
        self.assertEqual(project_resources(custom,'Bard'),custom)

    def test_extraction_preserves_original_words_punctuation_and_line_breaks(self):
        original='**1级:合成能力 Synthetic Power**\n保留原文,以及D6。\n**使用方法。**全部保留。'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'class.md'
            path.write_text('# 标题\n\n'+original+'\n\n**2级:另一能力 Other Power**\n另一段。',encoding='utf-8')
            entry=extract(path,'class.md')['syntheticpower']
            self.assertEqual(entry['text'],original)
            self.assertEqual(entry['source_line'],3)


if __name__=='__main__':unittest.main()
