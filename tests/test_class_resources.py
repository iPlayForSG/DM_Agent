"""职业资源等级、旧表迁移和资源消耗的合成回归。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from class_resources import resource_profile,migrate_character,migrate_game,catalog
from models import Character, GameState, ResourcePool, Stats, SpellSlot
from game_logic import GameLogic
from rules_catalog import RuleCatalog
from level_creation import options
from storage import GameStorage,atomic_write
import storage


class ClassResourceTests(unittest.TestCase):
    def setUp(self):
        self.scores=Stats(charisma=15,wisdom=14).model_dump()

    def test_first_level_counts_and_unlock_boundaries_for_all_supported_classes(self):
        expected={'Bard':{'Bardic Inspiration':2},'Cleric':{},'Druid':{},'Fighter':{'Second Wind':2},'Monk':{},
            'Paladin':{'Lay on Hands':5},'Ranger':{'Favored Enemy':2},'Rogue':{},'Sorcerer':{'Innate Sorcery':2},
            'Warlock':{},'Wizard':{'Arcane Recovery':1}}
        self.assertEqual(set(expected),set(catalog()))
        for name,counts in expected.items():
            actual=resource_profile(name,1,self.scores)
            self.assertEqual({key:row['max_value'] for key,row in actual.items()},counts,name)
        for name,key,count in [('Cleric','Channel Divinity',2),('Druid','Wild Shape',2),('Monk','Focus Points',2),
            ('Sorcerer','Sorcery Points',2),('Warlock','Magical Cunning',1),('Fighter','Action Surge',1)]:
            self.assertEqual(resource_profile(name,2,self.scores)[key]['max_value'],count)
        for name in expected:
            for level in range(1,21):
                for row in resource_profile(name,level,self.scores).values():
                    self.assertGreater(row['max_value'],0)
                    self.assertEqual(row['current_value'],row['max_value'])
                    self.assertTrue(row['description'])

    def test_bard_dice_scale_and_recovery_and_charisma_minimum(self):
        for level,die in [(1,'1d6'),(5,'1d8'),(10,'1d10'),(15,'1d12')]:
            row=resource_profile('Bard',level,self.scores)['Bardic Inspiration']
            self.assertIn(die,row['description'])
            self.assertEqual(row['max_value'],2)
            self.assertEqual(row['recovery'],'long_rest' if level<5 else 'short_rest')
        self.assertEqual(resource_profile('Bard',1,{**self.scores,'charisma':8})['Bardic Inspiration']['max_value'],1)

    def test_builder_and_runtime_migration_share_counts(self):
        rules=RuleCatalog()
        hero=Character(name='合成诗人',class_name='Bard',stats=Stats(**self.scores))
        preview=options(rules,hero)['class_config']['resources']
        migrate_character(hero,{})
        self.assertEqual(hero.resources['Bardic Inspiration'].model_dump(),preview['Bardic Inspiration'])
        self.assertEqual(hero.resources['Bardic Inspiration'].display_name,'吟游激励')

    def test_migration_preserves_spent_resources_hp_slots_and_custom_pools(self):
        hero=Character(name='合成战士',class_name='Fighter',hp_current=3,hp_max=12,gold_gp=19,
            resources={'Second Wind':ResourcePool(max_value=1,current_value=0), 'Custom':ResourcePool(max_value=3,current_value=1)})
        hero.spells.slots={'1':SpellSlot(total=2,used=2)}
        migrate_character(hero,{})
        self.assertEqual((hero.resources['Second Wind'].max_value,hero.resources['Second Wind'].current_value),(2,1))
        self.assertEqual(hero.resources['Second Wind'].short_rest_recovery,1)
        self.assertEqual(hero.resources['Custom'].current_value,1)
        from money import balance_cp
        self.assertEqual((hero.hp_current,hero.hp_max,balance_cp(hero),hero.spells.slots['1'].used),(3,12,1900,2))
        hero.resources['Second Wind'].current_value=0
        before=hero.model_dump(mode='json')
        migrate_character(hero,before)
        self.assertEqual(hero.model_dump(mode='json'),before)

    def test_old_druid_does_not_gain_second_level_feature_at_first_level(self):
        hero=Character(name='合成德鲁伊',class_name='Druid',resources={'Wild Shape':ResourcePool(max_value=2,current_value=2)})
        migrate_character(hero,{})
        self.assertNotIn('Wild Shape',hero.resources)

    def test_storage_load_migrates_without_writing_or_resetting_again(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(storage,'GAME_DIR',directory):
            store=GameStorage()
            hero=Character(name='旧诗人',class_name='Bard',stats=Stats(**self.scores),hp_current=5,hp_max=9)
            state=GameState(game_id='legacy-resources',characters={hero.character_id:hero})
            raw=state.model_dump(mode='json');raw['characters'][hero.character_id].pop('class_resource_version')
            path=Path(store._get_path(state.game_id));blob=json.dumps(raw,ensure_ascii=False).encode()
            atomic_write(str(path),blob)
            loaded=store.load_game(state.game_id)
            self.assertEqual(loaded.characters[hero.character_id].resources['Bardic Inspiration'].current_value,2)
            self.assertEqual(path.read_bytes(),blob)
            loaded.characters[hero.character_id].resources['Bardic Inspiration'].current_value=0
            store.save_game(state.game_id,loaded)
            self.assertEqual(store.load_game(state.game_id).characters[hero.character_id].resources['Bardic Inspiration'].current_value,0)

    def test_bard_use_consumes_bonus_action_and_cannot_be_free_or_repeated(self):
        hero=Character(name='合成诗人',class_name='Bard',stats=Stats(**self.scores))
        migrate_character(hero,{})
        state=GameState(game_id='resource-use',characters={hero.character_id:hero})
        logic=GameLogic(state);encounter=logic.start_encounter(['合成敌人'])
        for actor in encounter.combatants.values():logic.set_initiative(actor.combatant_id,20 if actor.side=='party' else 10)
        target=next(actor for actor in encounter.combatants.values() if actor.side=='enemy')
        logic.resolve_feature_use(hero.character_id,'吟游激励', target_ref=target.combatant_id,
                                  distance_feet=30, target_can_perceive=True)
        self.assertEqual(hero.resources['Bardic Inspiration'].current_value,1)
        self.assertTrue(encounter.turn_bonus_action_used)
        self.assertFalse(encounter.turn_action_used)
        before=state.model_dump(mode='json')
        with self.assertRaises(ValueError):logic.resolve_feature_use(hero.character_id,'吟游激励')
        self.assertEqual(state.model_dump(mode='json'),before)
        empty=Character(name='未配置资源',class_name='Bard')
        state=GameState(game_id='missing',characters={empty.character_id:empty})
        with self.assertRaises(ValueError):GameLogic(state).resolve_feature_use(empty.character_id,'Bardic Inspiration')


if __name__=='__main__':unittest.main()
