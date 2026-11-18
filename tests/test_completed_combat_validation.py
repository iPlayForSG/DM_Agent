"""攻击成功、附赠行动和遭遇结束后，旧修复不能再次成为当前指令。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV','1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE','memory')
from game_logic import GameLogic
from models import GameState, ResourcePool, InventoryItem, GrantedDie
from combat_flow import initial_flow
from roll_capture import capture_rolls
from langchain_core.messages import AIMessage
import test_generic_spell_resolution as fixtures
from test_combat_control import Script, call


class CompletedCombatTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.GenericSpellTests(); fixture.setUp()
        self.state=fixture.state;self.hero=fixture.hero;self.ids=fixture.ids;self.service=fixture.service
        self.runner=fixture.runner();self.addCleanup(self.runner.close)
        hero=self.state.get_active_char();hero.inventory=[InventoryItem(name='Scimitar',type='weapon')]
        hero.resources={'Bardic Inspiration':ResourcePool(current_value=3,max_value=3)}
        self.state.scene_actors[self.ids[0]].hp_current=1
        self.state.scene_actors[self.ids[0]].ac=10
        hero.stats.dexterity=14
        logic=GameLogic(self.state);enc=logic.start_encounter([self.ids[0]])
        for c in enc.combatants.values():logic.set_initiative(c.combatant_id,20 if c.side=='party' else 10)

    def test_real_tool_node_interrupt_restores_snapshot_then_resumes_original_roll(self):
        self.state.encounter=None;self.state.scene=self.state.campaign.phase='exploration'
        self.state.granted_dice=[GrantedDie(bonus_id='synthetic',source_id=self.ids[1],target_id=self.hero,
                                           expression='1d6',expires_at_seconds=3600)]
        self.runner._model=Script([call('roll_skill_check',actor_ref=self.hero,skill_name='Investigation',dc=12),
                                   AIMessage(content='你辨认出了线索。')])
        with patch('game_logic.random.randint',side_effect=[8,4]) as random, capture_rolls() as capture:
            paused=self.runner.run_turn(self.state,'调查石门上的线索。')
            self.assertEqual(paused.turn_status,'input_required',paused.response)
            self.assertEqual(len(paused.game_state.granted_dice),1)
            self.assertEqual(len(capture.records),1)
            self.assertEqual(capture.records[0].tool_status,'pending')
            # 与HTTP/SSE入口一致：将实际骰点保存进服务端pending_turn。
            paused.game_state.pending_turn.roll_records=[r.model_copy(deep=True) for r in capture.records]
            result=self.runner.resume_turn(paused.game_state,'使用激励')
        self.assertEqual(result.turn_status,'completed', str([n.metadata for n in result.turn_trace.node_traces if n.node_name=='execute_tools']))
        self.assertEqual(random.call_count,2)
        self.assertEqual(len(capture.records),2)
        self.assertEqual(capture.records[0].total,12)
        self.assertEqual(result.game_state.granted_dice,[])

    def test_kill_then_grant_then_end_rejects_false_feedback_and_commits(self):
        seen=[]
        class InspectScript(Script):
            def invoke(self,messages):
                seen.append(messages)
                return super().invoke(messages)
        self.runner._model=InspectScript([
            call('attack_target',attacker_ref=self.hero,target_ref=self.ids[0],attack_name='Scimitar (thrown)'),
            call('attack_target',attacker_ref=self.hero,target_ref=self.ids[0],attack_name='Scimitar',
                 attack_mode='thrown',distance_feet=10,damage_type='slashing',reason='投掷弯刀'),
            call('use_feature',actor_ref=self.hero,feature_name='Bardic Inspiration',target_ref=self.ids[1],
                 distance_feet=10,target_can_perceive=True),
            call('end_encounter'),
            call('report_rule_conflict',message='攻击已经杀死目标，无法再次攻击，请调整。'),
            AIMessage(content='弯刀飞向守卫并将它击倒。你随即鼓励另一位守卫；战斗结束。')])
        with patch('game_logic.random.randint',side_effect=lambda a,b:min(10,b)),capture_rolls() as capture:
            result=self.runner.run_turn(self.state,'将弯刀扔向持刀地精攻击，随后给持弓地精诗人激励。')
        self.assertEqual(result.turn_status,'completed', str([n.metadata for n in result.turn_trace.node_traces if n.node_name=='execute_tools']) if result.turn_trace else result.response)
        self.assertFalse(result.game_state.encounter.active)
        self.assertEqual(len(result.game_state.granted_dice),1)
        self.assertEqual(result.game_state.granted_dice[0].target_id,self.ids[1])
        self.assertEqual(result.game_state.characters[self.hero].resources['Bardic Inspiration'].current_value,2)
        self.assertEqual(len(capture.records),2)
        self.assertNotIn('行动需要调整',result.response)
        latest=[m.content for m in seen[-1] if getattr(m,'id',None)=='current-state-validation']
        self.assertEqual(len(latest),1)
        self.assertIn('校验已通过',latest[0])
        self.assertNotIn('requires repair',latest[0])

    def test_current_validation_does_not_resend_historical_errors(self):
        # 此场景尚未攻击，当前只应要求真正缺少的结算；无关历史不进入修复内容。
        state={'game_state':self.state.model_dump(mode='json'),'initial_game_state':self.state.model_dump(mode='json'),
               'messages':[],'validation_notes':['OBSOLETE_REPAIR_ATTACK'],
               'validation_issues':[], 'combat_flow':initial_flow(self.state), 'user_input':'观察', 'tool_results':[]}
        result=self.runner._validate_state(state)
        self.assertTrue(any('OBSOLETE_REPAIR_ATTACK'==note for note in result['validation_notes']))
        self.assertNotIn('OBSOLETE_REPAIR_ATTACK',' '.join(str(m.content) for m in result['messages']))

    def test_time_and_hide_clone_preserve_bonus_consumption(self):
        from d20_bonuses import decision_context
        self.state.encounter=None;self.state.scene=self.state.campaign.phase='exploration'
        self.state.granted_dice=[GrantedDie(bonus_id='synthetic',source_id=self.ids[1],target_id=self.hero,
                                           expression='1d6',expires_at_seconds=3600)]
        with decision_context(lambda info:True),patch('game_logic.random.randint',side_effect=[10,4]):
            result=self.service.hide_actor(self.state,self.hero,'total',False,'合成完整掩体')
        self.assertTrue(result.ok,result.error)
        self.assertEqual(self.state.granted_dice,[])
        self.state.granted_dice=[GrantedDie(bonus_id='second',source_id=self.ids[1],target_id=self.hero,
                                           expression='1d6',expires_at_seconds=3600)]
        result=self.service.advance_time(self.state,3600,'合成等待一小时')
        self.assertTrue(result.ok,result.error);self.assertEqual(self.state.granted_dice,[])


if __name__=='__main__':unittest.main()
