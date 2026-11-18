"""单一目录加载、离线无损合并和旧导入工具的回归。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from library import Library
from utils.merge_spell_catalogs import merge_catalogs
from utils.extract_data import extract_spells


def catalog(name='新名字', **fields):
    return {'SPELL_DATABASE':{'法师':[{'name':name,'nameEN':'Test Spell','level':1,'desc':'完整中文规则',**fields}]}}


class SingleSpellCatalogTests(unittest.TestCase):
    def test_runtime_ignores_legacy_file_and_refreshes_alias_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'spell_catalog_2024.json').write_text(json.dumps(catalog(aliases=['旧名字'])),encoding='utf-8')
            (root/'spells.json').write_text('this old file is deliberately invalid',encoding='utf-8')
            instance=object.__new__(Library)
            instance.spells={'旧职业':[]};instance._localized_aliases=[('Test Spell','错误旧缓存')]
            instance._localized_alias_lookup={'Test Spell':'错误旧缓存'}
            with patch('library.DATA_DIR',directory):instance._load_data()
            self.assertEqual(instance.get_all_classes(),['法师'])
            self.assertEqual(instance.get_spell_details('旧名字')['name'],'新名字')
            self.assertEqual(instance.localize_game_terms('Test Spell'),'新名字')

    def test_missing_canonical_catalog_does_not_fall_back_or_cache_failed_instance(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Library,'_instance',None):
            root=Path(directory)
            (root/'spells.json').write_text(json.dumps(catalog()),encoding='utf-8')
            with patch('library.DATA_DIR',directory):
                with self.assertRaises(FileNotFoundError):Library()
                self.assertIsNone(Library._instance)
                (root/'spell_catalog_2024.json').write_text(json.dumps(catalog()),encoding='utf-8')
                self.assertEqual(Library().get_spell_details('Test Spell')['name'],'新名字')

    def test_merge_preserves_both_metadata_sets_and_is_idempotent(self):
        primary=catalog(source_page=10,aliases=['简称'])
        legacy=catalog('旧名字',id='stable-old-id',schoolEN='Evocation',aliases=['旧别名'],desc='过时正文')
        before=(deepcopy(primary),deepcopy(legacy))
        result=merge_catalogs(primary,legacy)
        row=result['SPELL_DATABASE']['法师'][0]
        self.assertEqual(row['id'],'stable-old-id')
        self.assertEqual(row['source_page'],10)
        self.assertEqual(row['schoolEN'],'Evocation')
        self.assertEqual(row['desc'],'完整中文规则')
        self.assertEqual(set(row['aliases']),{'简称','旧名字','旧别名'})
        self.assertEqual(merge_catalogs(result,legacy),result)
        self.assertEqual((primary,legacy),before)

    def test_conflicting_level_or_id_fails_without_mutation(self):
        primary=catalog(id='first')
        for legacy in [catalog(id='second'),catalog(level=2)]:
            before=deepcopy(primary)
            with self.assertRaises(ValueError):merge_catalogs(primary,legacy)
            self.assertEqual(primary,before)

    def test_legacy_extractor_merges_instead_of_overwriting_full_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);destination=root/'spell_catalog_2024.json';source=root/'inline.html'
            complete=catalog()
            complete['SPELL_DATABASE']['法师'].append({'name':'高环法术','nameEN':'High Spell','level':9,'desc':'保留'})
            destination.write_text(json.dumps(complete),encoding='utf-8')
            source.write_text('<script id="spell-db-inline" type="application/json">'+json.dumps(catalog('旧名字',id='legacy-id'))+'</script>',encoding='utf-8')
            extract_spells(source,destination)
            result=json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(len(result['SPELL_DATABASE']['法师']),2)
            self.assertEqual(result['SPELL_DATABASE']['法师'][0]['id'],'legacy-id')
            self.assertFalse((root/'spells.json').exists())

    def test_canonical_catalog_contains_legacy_low_level_ids(self):
        data=json.loads((ROOT/'backend/data/spell_catalog_2024.json').read_text(encoding='utf-8'))
        unique={spell['nameEN']:spell for spells in data['SPELL_DATABASE'].values() for spell in spells}
        self.assertEqual(len(unique),391)
        self.assertEqual(unique['Blade Ward']['id'],'spell_0_blade_ward')
        self.assertIn('魅惑人类',unique['Charm Person']['aliases'])


if __name__=='__main__':unittest.main()
