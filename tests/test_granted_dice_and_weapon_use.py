"""合成检定、投掷、失败选择恢复；不访问实际游戏。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV', '1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE', 'memory')
from game_logic import GameLogic
from models import Character, GameState, Stats, ResourcePool, InventoryItem
from rules_catalog import RuleCatalog
from d20_bonuses import decision_context, graph_decision, expire, replay_pending_rolls
from roll_capture import capture_rolls, tool_roll_context
from weapon_use import profile
from combat_status import combat_status_entries
from action_service import GameActionService
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from typing import TypedDict


class GrantedDiceTests(unittest.TestCase):
    def setUp(self):
        self.bard = Character(name='合成诗人', class_name='Bard', stats=Stats(strength=8, dexterity=14, charisma=16),
            resources={'Bardic Inspiration': ResourcePool(current_value=3, max_value=3)},
            inventory=[InventoryItem(name='Scimitar', type='weapon'), InventoryItem(name='Dagger', type='weapon', quantity=2)])
        self.target = Character(name='合成队友', class_name='Fighter', hp_current=30, hp_max=30)
        self.state = GameState(scene='exploration', characters={c.character_id:c for c in [self.bard,self.target]},
                               primary_character_id=self.bard.character_id, active_character_id=self.bard.character_id)
        self.logic = GameLogic(self.state)
        self.catalog = RuleCatalog()

    def grant(self, source=None, target=None, **kwargs):
        return self.logic.resolve_feature_use((source or self.bard).character_id, 'Bardic Inspiration',
            target_ref=(target or self.target).character_id, distance_feet=kwargs.get('distance',30),
            target_can_perceive=kwargs.get('perceive',True))

    def test_target_expiry_scaling_and_failure_atomicity(self):
        for level, sides in [(1,6),(5,8),(10,10),(15,12)]:
            self.bard.level=level
            self.bard.resources['Bardic Inspiration'].current_value=3
            self.state.granted_dice=[]
            result=self.grant()
            self.assertEqual(result['granted_die']['expression'],f'1d{sides}')
            self.assertEqual(len(combat_status_entries(self.state,self.target.character_id)),1)
        before=self.state.model_dump(mode='json')
        with self.assertRaises(ValueError): self.grant()
        self.assertEqual(before,self.state.model_dump(mode='json'))
        self.state.rules_time_seconds=3600; expire(self.state)
        self.assertEqual(self.state.granted_dice,[])
        for args in [{'target':self.bard},{'distance':61},{'perceive':False}]:
            before=self.state.model_dump(mode='json')
            with self.assertRaises(ValueError): self.grant(**args)
            self.assertEqual(before,self.state.model_dump(mode='json'))

    def test_failed_skill_and_save_consume_once_success_keeps(self):
        self.grant()
        with patch('game_logic.random.randint',return_value=15):
            self.assertTrue(self.logic.roll_saving_throw(self.target.character_id,'wisdom',0,10)['success'])
        self.assertEqual(len(self.state.granted_dice),1)
        with capture_rolls() as capture, patch('game_logic.random.randint',side_effect=[8,3]):
            result=self.logic.roll_skill_check(self.target.character_id,'Athletics',0,10)
        self.assertTrue(result['success'])
        self.assertEqual(result['total'],11)
        self.assertEqual(len(capture.records),2)
        self.assertTrue(capture.records[0].success)
        self.assertEqual(self.state.granted_dice,[])
        self.grant()
        with patch('game_logic.random.randint',side_effect=[1,2]):
            self.assertFalse(self.logic.roll_saving_throw(self.target.character_id,'wisdom',0,15)['success'])
        self.assertEqual(self.state.granted_dice,[])

    def test_attack_bonus_precedes_damage_and_natural_one_is_miss(self):
        self.grant()
        with capture_rolls() as capture, patch('game_logic.random.randint',side_effect=[8,4,3]):
            result=self.logic.resolve_attack(self.target.character_id,self.bard.character_id,0,'1d4')
        self.assertTrue(result['hit']); self.assertEqual(result['damage_total'],3)
        self.assertEqual([r.label for r in capture.records],['攻击检定','诗人激励','攻击伤害'])
        self.grant()
        with patch('game_logic.random.randint',return_value=1):
            result=self.logic.resolve_attack(self.target.character_id,self.bard.character_id,100,'1d4')
        self.assertFalse(result['hit']); self.assertEqual(len(self.state.granted_dice),1)

    def test_durable_failure_choice_keeps_original_roll_and_state(self):
        self.grant(); self.state.combat_controllers[self.target.character_id]='player'
        original=self.state.model_dump(mode='json')
        class State(TypedDict):
            game:dict
            result:dict
        def check(data):
            state=GameState.model_validate(data['game'])
            with decision_context(graph_decision),tool_roll_context() as outcome:
                result=GameLogic(state).roll_saving_throw(self.target.character_id,'wisdom',0,10)
                outcome['ok']=True
            return {'game':state.model_dump(mode='json'),'result':result}
        builder=StateGraph(State);builder.add_node('check',check);builder.add_edge(START,'check');builder.add_edge('check',END)
        graph=builder.compile(checkpointer=InMemorySaver()); config={'configurable':{'thread_id':'synthetic-die'}}
        with capture_rolls() as capture,patch('game_logic.random.randint',side_effect=[8,4]) as random:
            paused=graph.invoke({'game':original},config)
            self.assertIn('__interrupt__',paused);self.assertEqual(paused['game'],original)
            self.assertEqual(random.call_count,1)
            with replay_pending_rolls(paused['__interrupt__'][0].value['details']['_dice_replay']):
                result=graph.invoke(Command(resume={'message':'使用激励'}),config)
        self.assertEqual(random.call_count,2)
        self.assertEqual(result['result']['total'],12)
        self.assertEqual(result['game']['granted_dice'],[])
        self.assertEqual(len(capture.records),2)
        self.assertTrue(capture.records[0].success)
        self.assertTrue(all(r.tool_status=='succeeded' for r in capture.records))

    def test_weapon_modes_and_ranges(self):
        def use(name='Scimitar',mode='thrown',distance=10,**kwargs):
            return profile(self.catalog,self.bard,name,mode,distance,'slashing',kwargs.get('equivalent',''),'合成投掷测试',kwargs.get('roll_mode','normal'))
        result=use();self.assertEqual(result['attack_bonus'],2);self.assertEqual(result['damage_expression'],'1d4+2')
        self.assertEqual(use(distance=30)['roll_mode'],'disadvantage')
        self.assertEqual(use(distance=30,roll_mode='advantage')['roll_mode'],'normal')
        with self.assertRaises(ValueError):use(distance=61)
        result=use('Dagger');self.assertFalse(result['improvised']);self.assertEqual(result['attack_bonus'],4)
        self.assertEqual(result['damage_expression'],'1d4+2')
        self.bard.origin_feat='Tavern Brawler';self.assertEqual(use()['attack_bonus'],4)
        self.bard.inventory.append(InventoryItem(name='桌腿'))
        self.assertEqual(use('桌腿','improvised_melee',3,equivalent='Club')['damage_expression'],'1d4-1')

    def test_thrown_inventory_released_on_miss(self):
        service=GameActionService()
        with patch('game_logic.random.randint',return_value=1):
            service.attack_target(self.state,self.bard.character_id,self.target.character_id,attack_name='Scimitar',
                attack_mode='thrown',distance_feet=10,damage_type='slashing',reason='朝目标投掷弯刀')
        self.assertNotIn('Scimitar',[i.name for i in self.bard.inventory])
        self.assertEqual(self.target.hp_current,30)

    def test_declined_die_and_failure_rollback_keep_resource(self):
        self.grant();self.state.combat_controllers[self.target.character_id]='player'
        with decision_context(lambda info:False),patch('game_logic.random.randint',return_value=8):
            result=self.logic.roll_saving_throw(self.target.character_id,'wisdom',0,12)
        self.assertFalse(result['success']);self.assertEqual(len(self.state.granted_dice),1)
        before=self.state.model_dump(mode='json')
        with decision_context(lambda info:True),patch('game_logic.random.randint',side_effect=[8,4]):
            with self.assertRaises(ValueError):
                self.logic.resolve_attack(self.target.character_id,self.bard.character_id,0,'101d6')
        self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_internal_replay_is_not_a_player_payload_or_display_record(self):
        from player_projection import player_payload
        payload={'details':{'_dice_replay':[{'count':1,'sides':20,'values':[8],'record_id':'x'}], 'options':['使用激励','保留激励']}}
        self.assertNotIn('_dice_replay',player_payload(payload)['details'])
        from d20_bonuses import draw
        with replay_pending_rolls(payload['details']['_dice_replay']),patch('game_logic.random.randint',side_effect=AssertionError('不能重掷')):
            self.assertEqual(draw(1,20),([8],'x'))
        with replay_pending_rolls(payload['details']['_dice_replay']),self.assertRaises(ValueError):draw(1,6)

    def test_long_range_cancels_all_advantage_sources_together(self):
        from models import HidingState
        self.bard.hiding=HidingState(stealth_total=20,cover='total',reason='合成掩体')
        with capture_rolls() as rolls,patch('game_logic.random.randint',return_value=1):
            result=GameActionService().attack_target(self.state,self.bard.character_id,self.target.character_id,
                attack_name='Scimitar',attack_mode='thrown',distance_feet=30,damage_type='slashing',
                reason='从掩体远距离投掷，另有战术优势',roll_mode='advantage')
        self.assertEqual(result['tool_result'].payload['roll_mode'],'normal')
        self.assertEqual(len(rolls.records[0].dice),1)


if __name__=='__main__':unittest.main()
