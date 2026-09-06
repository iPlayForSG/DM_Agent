"""合成队伍回合：真实工具结算、明确玩家交接、失败回滚。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV','1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE','memory')
from langchain_core.messages import AIMessage
from agent_tools import AgentToolService
from combat_flow import initial_flow, handoff_ready
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import Character, GameState, InventoryItem, PendingTurnState, ResourcePool
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from roll_capture import capture_rolls
import test_dm_graph_workflow as fixtures


def call(name, **args):
    return AIMessage(content='正在结算。', tool_calls=[{'id':name,'name':name,'args':args}])


class Script:
    def __init__(self, replies): self.replies=iter(replies); self.calls=0; self.tool_sets=[]
    def bind(self, **kwargs): return self
    def bind_tools(self, tools): self.tool_sets.append([t.name for t in tools]); return self
    def invoke(self, messages): self.calls+=1; return next(self.replies)


class CombatControlTests(unittest.TestCase):
    def setUp(self):
        self.state=fixtures.DMGraphWorkflowTests()._build_state(True)
        self.hero=self.state.get_active_char()
        self.hero.hp_max=self.hero.hp_current=100
        self.hero.inventory=[InventoryItem(name='Dagger',type='weapon',damage_expression='1d4',is_equipped=True)]
        self.ally=Character(name='DM companion',class_name='Fighter',hp_current=100,hp_max=100)
        self.buddy=Character(name='Player companion',class_name='Fighter',hp_current=100,hp_max=100)
        for c in [self.ally,self.buddy]:
            c.inventory=[InventoryItem(name='Dagger',type='weapon',damage_expression='1d4',is_equipped=True)]
            self.state.characters[c.character_id]=c
        self.state.combat_controllers[self.buddy.character_id]='player'
        logic=GameLogic(self.state)
        encounter=logic.start_encounter(['Enemy'],enemy_hp=100,enemy_ac=10)
        self.enemy=next(c for c in encounter.combatants.values() if c.side=='enemy')
        for ref, initiative in [(self.hero.character_id,20),(self.enemy.combatant_id,18),(self.ally.character_id,16),(self.buddy.character_id,14)]: logic.set_initiative(ref,initiative)
        self.service=AgentToolService(fixtures.DummyRAGEngine(),MonsterStorage(),RuleCatalog())
        self.runner=DMGraphRunner(fixtures.DummyRAGEngine(),tool_service=self.service,enable_model=True,checkpoint_mode='memory')
        self.addCleanup(self.runner.close)

    def run_turn(self,replies,text='我用匕首攻击敌人。'):
        model=Script(replies);self.runner._model=model
        with patch('game_logic.random.randint',return_value=10),capture_rolls() as capture:
            result=self.runner.run_turn(self.state,text)
        self.assertEqual(result.turn_status,'completed',result.response)
        return result,capture.records,model

    def attack(self,actor,target):
        return call('attack_target',attacker_ref=actor,target_ref=target,attack_name='Dagger',attack_bonus=4,damage_expression='1d4')

    def test_party_defaults_survive_current_actor_change(self):
        data=self.state.model_dump(mode='json');data.pop('primary_character_id');data.pop('combat_controllers')
        data['active_character_id']=self.ally.character_id
        migrated=GameState.model_validate(data)
        self.assertEqual(migrated.get_primary_character_id(),self.hero.character_id)
        self.assertTrue(migrated.is_player_controlled(self.hero.character_id))
        self.assertFalse(migrated.is_player_controlled(self.ally.character_id))
        migrated.combat_controllers[self.hero.character_id]='dm'
        self.assertTrue(migrated.is_player_controlled(self.hero.character_id))

    def test_player_enemy_dm_companion_then_player_companion(self):
        result,rolls,model=self.run_turn([
            self.attack(self.hero.character_id,self.enemy.combatant_id),call('advance_turn'),
            self.attack(self.enemy.combatant_id,self.hero.character_id),call('advance_turn'),
            self.attack(self.ally.character_id,self.enemy.combatant_id),call('advance_turn'),
            AIMessage(content='双方交锋后，轮到玩家控制的队员行动。')])
        state=result.game_state
        self.assertEqual(state.encounter.get_current_combatant().linked_character_id,self.buddy.character_id)
        self.assertEqual(state.active_character_id,self.buddy.character_id)
        self.assertFalse(state.encounter.turn_action_used)
        self.assertEqual(len([r for r in rolls if r.kind=='attack']),3)
        self.assertLess(state.characters[self.hero.character_id].hp_current,100)
        self.assertLess(state.encounter.combatants[self.enemy.combatant_id].hp_current,100)
        self.assertEqual(state.chat_history[-1].narrative_mode,'combat')
        self.assertEqual(model.calls,7)

    def test_already_spent_action_advances_without_replaying(self):
        self.state.encounter.turn_action_used=True
        self.state.encounter.turn_action_tool='attack_target'
        result,rolls,model=self.run_turn([call('advance_turn'),call('advance_turn'),call('advance_turn'),AIMessage(content='先前动作已经用完。敌人与队友放弃动作，轮到另一位玩家队员。')])
        self.assertIn('advance_turn',model.tool_sets[0])
        self.assertNotIn('attack_target',model.tool_sets[0])
        self.assertEqual(rolls,[])
        self.assertEqual(result.game_state.encounter.get_current_combatant().linked_character_id,self.buddy.character_id)

    def test_dm_current_stops_before_player_without_consuming_input(self):
        GameLogic(self.state).advance_turn()
        result,rolls,_=self.run_turn([call('advance_turn'),call('advance_turn'),AIMessage(content='轮到玩家队员；请选择行动。')])
        self.assertEqual(rolls,[])
        self.assertFalse(result.game_state.encounter.turn_action_used)
        self.assertEqual(result.game_state.encounter.get_current_combatant().linked_character_id,self.buddy.character_id)

    def test_short_combat_does_not_rewrite_minimum_or_change_preference(self):
        self.state.campaign.reply_min_chars=1000
        self.state.campaign.reply_max_chars=1200
        GameLogic(self.state).advance_turn()
        with patch.object(self.runner,'_rewrite_response_to_length',side_effect=AssertionError('must not pad combat')):
            result,_,_=self.run_turn([call('advance_turn'),call('advance_turn'),AIMessage(content='轮到你的队员。')],'继续战斗。')
        self.assertEqual(result.game_state.campaign.reply_min_chars,1000)

    def test_no_capable_player_stops_for_companion_takeover(self):
        for c in [self.hero,self.buddy]:
            GameLogic(self.state).update_target_hp(c.character_id,-1000)
        self.assertTrue(handoff_ready(self.state,initial_flow(self.state)))
        result,rolls,_=self.run_turn([AIMessage(content='玩家角色都无法行动。可以接管仍站着的队友。')],'继续战斗。')
        self.assertEqual(rolls,[])
        self.assertEqual(result.game_state.characters[self.hero.character_id].hp_current,0)

    def test_repeated_failure_rolls_back_and_never_publishes_progress_as_final(self):
        wrong=call('attack_target',attacker_ref='missing',target_ref=self.enemy.combatant_id)
        self.runner._model=Script([wrong.model_copy(deep=True) for _ in range(4)])
        with capture_rolls() as capture: result=self.runner.run_turn(self.state,'我攻击敌人。')
        self.assertEqual(result.turn_status,'failed')
        self.assertEqual(self.runner._model.calls,3)
        self.assertNotIn('正在结算',result.response)
        self.assertEqual(capture.records,[])
        self.assertEqual(result.game_state.encounter.model_dump(),self.state.encounter.model_dump())
        self.assertTrue(any(x.validator=='repeated_tool_error' for x in result.validation_issues))

    def test_cannot_execute_old_action_after_player_handoff(self):
        graph={'game_state':self.state.model_dump(mode='json'),'combat_flow':{'stop_at_player':True}}
        self.assertIn('Next player decision',self.runner._repair_tool_call_error(graph,'attack_target',{}))

    def test_control_endpoint_blocks_primary_stale_and_pending(self):
        from fastapi.testclient import TestClient
        import main as api
        from test_main_streaming import FakeStorage
        fake=FakeStorage(self.state)
        prefix=f'/api/v1/games/{self.state.game_id}/characters/'
        with patch.object(api,'game_storage',fake),TestClient(api.app) as client:
            original=self.state.encounter.model_dump()
            url=prefix+self.ally.character_id+'/combat-control'
            payload={'controller':'player','state_version':self.state.state_version}
            result=client.put(url,json=payload)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['game_state']['encounter'],original)
            self.assertEqual(result.json()['game_state']['combat_controllers'][self.ally.character_id],'player')
            self.assertEqual(client.put(prefix+self.hero.character_id+'/combat-control',json={**payload,'controller':'dm'}).status_code,400)
            self.assertEqual(client.put(url,json={**payload,'state_version':'stale'}).status_code,409)
            fake.state.pending_turn=PendingTurnState(thread_id='test',kind='player_choice',prompt='test')
            self.assertEqual(client.put(url,json=payload).status_code,409)

    def test_declared_bonus_action_can_finish_before_handoff(self):
        self.hero.resources['Second Wind']=ResourcePool(current_value=1,max_value=1)
        result,_,_=self.run_turn([
            self.attack(self.hero.character_id,self.enemy.combatant_id),
            call('use_feature',actor_ref=self.hero.character_id,feature_name='Second Wind'),
            call('advance_turn'),call('advance_turn'),call('advance_turn'),
            AIMessage(content='你完成攻击与回气后，轮到另一位队员。')], '我攻击敌人，然后用 Second Wind，结束回合。')
        self.assertEqual(result.game_state.characters[self.hero.character_id].resources['Second Wind'].current_value,0)
        self.assertEqual(result.game_state.encounter.get_current_combatant().linked_character_id,self.buddy.character_id)

    def test_changing_companion_to_player_moves_the_handoff_earlier(self):
        self.state.combat_controllers[self.ally.character_id]='player'
        result,_,_=self.run_turn([
            self.attack(self.hero.character_id,self.enemy.combatant_id),
            call('advance_turn'),call('advance_turn'),AIMessage(content='轮到新接管的队员。')])
        self.assertEqual(result.game_state.encounter.get_current_combatant().linked_character_id,self.ally.character_id)
        self.assertFalse(result.game_state.encounter.turn_action_used)

    def test_next_input_can_control_companion_without_changing_primary(self):
        logic=GameLogic(self.state)
        for _ in range(3): logic.advance_turn()
        result,_,_=self.run_turn([self.attack(self.buddy.character_id,self.enemy.combatant_id),call('advance_turn'),AIMessage(content='队员完成行动，轮到主控。')])
        self.assertEqual(result.game_state.encounter.get_current_combatant().linked_character_id,self.hero.character_id)
        self.assertEqual(result.game_state.get_primary_character_id(),self.hero.character_id)

    def test_combat_mode_survives_encounter_end(self):
        self.state.campaign.reply_min_chars=1000
        self.state.campaign.reply_max_chars=1500
        with patch.object(self.runner,'_rewrite_response_to_length',side_effect=AssertionError('do not pad combat ending')):
            result,_,_=self.run_turn([call('end_encounter'),AIMessage(content='双方脱离战斗。')],'双方脱离战斗。')
        self.assertFalse(result.game_state.encounter.active)
        self.assertEqual(result.game_state.chat_history[-1].narrative_mode,'combat')

    def test_advance_turn_synchronizes_party_actor_in_both_tool_paths(self):
        from action_service import GameActionService
        for service in [self.service, GameActionService()]:
            with self.subTest(service=type(service).__name__):
                state=self.state.model_copy(deep=True)
                service.advance_turn(state)
                result=service.advance_turn(state)
                self.assertEqual(state.active_character_id,self.ally.character_id)
                self.assertEqual(state.get_primary_character_id(),self.hero.character_id)
                patch=result.state_patch if hasattr(result,'state_patch') else result['state_delta']
                self.assertEqual(patch['active_character_id'],self.ally.character_id)

    def test_dm_context_refreshes_equipment_for_current_companion(self):
        from combat_flow import guidance
        flow=initial_flow(self.state)
        logic=GameLogic(self.state)
        logic.advance_turn(); logic.advance_turn()
        context=guidance(self.state,flow)
        self.assertIn('Current authoritative party actor sheet:',context)
        self.assertIn(self.ally.character_id,context)
        self.assertIn('Dagger',context)
        self.assertIn('"action_used": false',context)
