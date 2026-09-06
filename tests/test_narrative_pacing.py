"""卡片战斗标识不等于整条回复篇幅豁免。"""
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV','1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE','memory')
from langchain_core.messages import AIMessage
from combat_flow import initial_flow,after_tool,narrative_scope,guidance
from game_logic import GameLogic
from dm_graph import DMGraphRunner
from models import GameState
from prompts import build_dm_instruction,NARRATIVE_PACING_VERSION
import test_dm_graph_workflow as fixtures


class NarrativePacingTests(unittest.TestCase):
    def setUp(self):
        self.state=fixtures.DMGraphWorkflowTests()._build_state(True)
        self.state.campaign.reply_min_chars=300
        self.state.campaign.reply_max_chars=900
        self.runner=DMGraphRunner(fixtures.DummyRAGEngine(),checkpoint_mode='memory')
        self.addCleanup(self.runner.close)

    def start_combat(self,state):
        logic=GameLogic(state);enc=logic.start_encounter(['Test enemy'])
        for c in enc.combatants.values():logic.set_initiative(c.combatant_id,20 if c.side=='party' else 10)

    def finalize(self,before,after,text,flow):
        return self.runner._finalize_turn({'initial_game_state':before.model_dump(mode='json'),'game_state':after.model_dump(mode='json'),'combat_flow':flow,'final_response':text,'turn_status':'completed'})

    def test_scope_tracks_scene_entry_instead_of_combat_message_color(self):
        before=self.state.model_copy(deep=True);flow=initial_flow(before)
        self.assertEqual(narrative_scope(before,flow),'story')
        self.start_combat(self.state)
        flow=after_tool(before,self.state,flow,'start_encounter')
        self.assertEqual(narrative_scope(self.state,flow),'mixed')
        self.assertEqual(narrative_scope(self.state,initial_flow(self.state)),'combat')
        GameLogic(self.state).end_encounter()
        self.assertEqual(narrative_scope(self.state,flow,before.model_dump(mode='json')),'mixed')

    def test_mixed_reply_keeps_minimum_and_protects_story_in_editor(self):
        before=self.state.model_copy(deep=True)
        self.start_combat(self.state)
        with patch.object(self.runner,'_rewrite_response_to_length',return_value=('有层次的剧情铺垫。'*40+'敌人逼近，交锋已停在玩家决策点。',[])) as editor:
            result=self.finalize(before,self.state,'先交谈，再交锋。',{'combat':True})
        self.assertEqual(result['turn_status'],'completed')
        self.assertEqual(result['game_state']['chat_history'][-1]['narrative_mode'],'combat')
        self.assertEqual(editor.call_args.args[1].campaign.reply_min_chars,300)
        self.assertEqual(editor.call_args.kwargs['pacing_scope'],'mixed')
        self.assertEqual(result['game_state']['campaign']['reply_min_chars'],300)

    def test_short_combat_is_optional_but_rich_combat_is_not_trimmed(self):
        self.start_combat(self.state)
        before=self.state.model_copy(deep=True)
        for text in ['刀锋相交，轮到你了。','盾沿震颤，守住的门仍在身后，敌人收刀盯住缺口。'*25]:
            with self.subTest(length=len(text)),patch.object(self.runner,'_rewrite_response_to_length',side_effect=AssertionError('within bounds')):
                result=self.finalize(before,self.state,text,initial_flow(before))
                self.assertEqual(result['final_response'],text)

    def test_pure_combat_ending_does_not_reintroduce_minimum(self):
        self.start_combat(self.state);before=self.state.model_copy(deep=True)
        GameLogic(self.state).end_encounter()
        with patch.object(self.runner,'_rewrite_response_to_length',side_effect=AssertionError('do not pad')):
            result=self.finalize(before,self.state,'交锋已结束。',{'combat':True})
        self.assertEqual(result['turn_status'],'completed')

    def test_maximum_still_applies_to_combat(self):
        self.start_combat(self.state);before=self.state.model_copy(deep=True)
        with patch.object(self.runner,'_rewrite_response_to_length',return_value=('可读的战斗过程。',[])) as editor:
            self.finalize(before,self.state,'战斗叙事。'*300,initial_flow(before))
        self.assertEqual(editor.call_args.args[1].campaign.reply_min_chars,0)
        self.assertEqual(editor.call_args.args[1].campaign.reply_max_chars,900)

    def test_prompt_allows_detail_and_keeps_precombat_story(self):
        for scope in ['story','mixed','combat']:
            prompt=build_dm_instruction(state_summary='synthetic',recent_history='',rag_enabled=False,pacing_scope=scope,reply_min_chars=300,reply_max_chars=900)
            self.assertIn(NARRATIVE_PACING_VERSION,prompt)
            self.assertIn('关键命中',prompt)
            self.assertIn('进入战斗后不要在最终回复中丢掉这段铺垫',prompt)
            self.assertEqual('minimum 300 visible Chinese characters' in prompt,scope!='combat')
        self.assertNotIn('combat recap',guidance(self.state,{'combat':True,'started_in_combat':True,'stop_at_player':True}))

    def test_mixed_editor_preserves_pacing_and_markers(self):
        class Editor:
            messages=[]
            def bind(self,**kwargs):return self
            def invoke(self,messages):
                self.messages=messages
                return AIMessage(content='有意义的进战前剧情。'*40)
        editor=Editor();self.runner._model=editor
        self.runner._rewrite_response_to_length('很短的进战前剧情。战斗已结束。',self.state,pacing_scope='mixed')
        request=editor.messages[-1].content
        self.assertIn('扩写优先补足进战前',request)
        self.assertIn('不要把缺少的字数转嫁成战斗流水账',request)
        self.assertNotIn('唯一验收标准',request)

    def test_no_limits_and_no_new_action_still_have_scene_pacing(self):
        prompt=build_dm_instruction(state_summary='Only established facts; no new player action.',recent_history='',rag_enabled=False,reply_min_chars=0,reply_max_chars=0)
        self.assertIn('No explicit per-reply character limit',prompt)
        self.assertIn('不能为写得精彩而增添',prompt)
