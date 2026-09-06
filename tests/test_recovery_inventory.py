"""连接失败不重掷；明确失败反馈与权威物品变化。"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV','1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE','memory')
from langchain_core.messages import AIMessage
from codex_transport import TransientModelConnectionError
from dm_graph import DMGraphRunner
from agent_tools import AgentToolService
from models import ChatMessage, InventoryItem, TurnResult
from game_logic import GameLogic
from inventory_narration import inventory_annotations,ensure_inventory_annotations
from roll_capture import capture_rolls
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from turn_stream import turn_time_budget,turn_stream_context
import test_dm_graph_workflow as fixtures


class RecoveryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.state=fixtures.DMGraphWorkflowTests()._build_state(True)
        self.hero=self.state.active_character_id
        self.runner=DMGraphRunner(fixtures.DummyRAGEngine(),tool_service=AgentToolService(fixtures.DummyRAGEngine(),MonsterStorage(),RuleCatalog()),enable_model=True,checkpoint_mode='memory')
        self.addCleanup(self.runner.close)

    def model(self,replies):
        class Model:
            calls=0
            def bind_tools(self,tools):return self
            def bind(self,**kwargs):return self
            def invoke(self,messages):
                item=replies[self.calls];self.calls+=1
                if isinstance(item,Exception):raise item
                return item
        result=Model();self.runner._model=result;return result

    def test_connection_retry_after_dice_does_not_replay_roll_or_tool(self):
        response=AIMessage(content='先调查。',tool_calls=[{'id':'check','name':'roll_skill_check','args':{'actor_ref':self.hero,'skill_name':'Investigation','dc':10}}])
        model=self.model([response,TransientModelConnectionError('temporary'),AIMessage(content='你没发现新的线索。')])
        with patch('game_logic.random.randint',return_value=1) as rng,capture_rolls() as capture:
            result=self.runner.run_turn(self.state,'我调查尸体，寻找线索。')
        self.assertEqual(result.turn_status,'completed',result.response)
        self.assertEqual(model.calls,3)
        self.assertEqual(rng.call_count,1)
        self.assertEqual(len(capture.records),1)
        self.assertFalse(capture.records[0].success)
        self.assertEqual(len(result.tool_results),1)

    def test_second_connection_failure_stops_without_third_attempt(self):
        model=self.model([TransientModelConnectionError('first'),TransientModelConnectionError('second')])
        with self.assertRaises(TransientModelConnectionError):self.runner._invoke_dm_model(model,[])
        self.assertEqual(model.calls,2)

    def test_non_connection_errors_never_retry(self):
        model=self.model([RuntimeError('invalid schema')])
        with self.assertRaisesRegex(RuntimeError,'invalid schema'):self.runner._invoke_dm_model(model,[])
        self.assertEqual(model.calls,1)

    def test_retry_does_not_extend_deadline(self):
        clock=[0.0]
        class Model:
            calls=0
            def invoke(self,messages):
                self.calls+=1;clock[0]=31
                raise TransientModelConnectionError('temporary')
        model=Model()
        with patch('turn_stream.time.monotonic',side_effect=lambda:clock[0]),turn_time_budget(30):
            with self.assertRaisesRegex(RuntimeError,'等待时限'):self.runner._invoke_dm_model(model,[])
        self.assertEqual(model.calls,1)

    def test_inventory_markers_cover_gain_loss_equipment_gold_and_reject_fakes(self):
        before=self.state.model_copy(deep=True)
        before.characters[self.hero].inventory=[InventoryItem(name='Dagger',quantity=2,type='weapon'),InventoryItem(name='Potion',quantity=2)]
        after=before.model_copy(deep=True)
        after.characters[self.hero].inventory[0].quantity=3
        after.characters[self.hero].inventory[0].is_equipped=True
        after.characters[self.hero].inventory[1].quantity=1
        after.characters[self.hero].gold_gp+=2
        records=inventory_annotations(before,after)
        response=ensure_inventory_annotations('你拿起 Dagger，喝下 Potion。\n\n**物品｜凭空获得钻石 +99**',records)
        for term in ['Dagger +1','Potion -1','已装备','金币 +2']:self.assertIn(term,response)
        self.assertNotIn('钻石',response)
        self.assertEqual(ensure_inventory_annotations(response,records),response)

    def test_committed_tool_inventory_change_is_in_final_narrative(self):
        self.model([AIMessage(content='拿走绳索。',tool_calls=[{'id':'loot','name':'add_inventory_item','args':{'character_ref':self.hero,'item_name':'Rope','quantity':2}}]),AIMessage(content='你收好了绳索。')])
        result=self.runner.run_turn(self.state,'拿走两根绳索，放入物品栏。')
        self.assertEqual(result.turn_status,'completed',result.response)
        self.assertIn('**物品｜',result.response)
        self.assertIn('+2（现有 2）',result.response)
        self.assertEqual(result.game_state.chat_history[-1].content,result.response)

    def test_failed_turn_does_not_publish_staged_inventory_gain(self):
        self.model([AIMessage(content='',tool_calls=[{'id':'loot','name':'add_inventory_item','args':{'character_ref':self.hero,'item_name':'Rope','quantity':2}}]),RuntimeError('outage')])
        result=self.runner.run_turn(self.state,'拿走两根绳索，放入物品栏。')
        self.assertEqual(result.turn_status,'failed')
        self.assertNotIn('**物品｜',result.response)
        self.assertEqual(result.game_state.characters[self.hero].inventory,self.state.characters[self.hero].inventory)

    def test_failed_retry_stream_reports_rollback_and_preserves_branch(self):
        from fastapi.testclient import TestClient
        import main as api
        from test_main_streaming import FakeStorage,FakeAgent,patched_runtime,parse_sse_events
        self.state.chat_history=[ChatMessage(role='user',content='old action'),ChatMessage(role='assistant',content='old reply')]
        store=FakeStorage(self.state)
        store.save_rewind_snapshot(self.state.game_id,0,self.state)
        before=self.state.model_dump(mode='json')
        class FailedAgent(FakeAgent):
            async def run_turn(inner,state,message):
                GameLogic(state).roll_skill_check(self.hero,'Investigation',0,10)
                return TurnResult(response='模型连接失败。',turn_status='failed',game_state=state)
        with patched_runtime(FailedAgent(None),store),TestClient(api.app) as client:
            response=client.post(f'/api/v1/games/{self.state.game_id}/messages/1/retry?stream=true')
        events=parse_sse_events(response.text.splitlines())
        event=next(e for e in events if e['event']=='turn.error')
        payload=event['data']
        if isinstance(payload,str):payload=json.loads(payload)
        self.assertEqual(payload['code'],'turn_not_committed')
        self.assertTrue(payload['branch_preserved'])
        self.assertEqual(len(payload['roll_records']),1)
        self.assertEqual(payload['roll_records'][0]['settlement'],'rolled_back')
        self.assertEqual(store.state.model_dump(mode='json'),before)

    def test_codex_connection_failure_is_typed_but_auth_is_not(self):
        from test_codex_transport import CodexTransportTests,protocol_events,notification
        fixture=CodexTransportTests()
        for status,expected in [(None,TransientModelConnectionError),(503,TransientModelConnectionError),(401,RuntimeError)]:
            with self.subTest(status=status),self.assertRaises(expected) as error:
                fixture.run_transport(protocol_events(notification('turn/completed',turn={'id':'turn','status':'failed','error':{'codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':status}}}})))
            if status==401:self.assertNotIsInstance(error.exception,TransientModelConnectionError)

    def test_length_rewrite_cannot_change_inventory_marker_quantity(self):
        after=self.state.model_copy(deep=True)
        after.characters[self.hero].inventory.append(InventoryItem(name='Rope',quantity=2))
        after.campaign.reply_min_chars=100
        with patch.object(self.runner,'_rewrite_response_to_length',return_value=('扩写叙事。**物品｜凭空获得 Rope +99**',[])):
            result=self.runner._finalize_turn({'game_state':after.model_dump(mode='json'),'initial_game_state':self.state.model_dump(mode='json'),'final_response':'拿好了。','turn_status':'completed'})
        self.assertEqual(result['turn_status'],'completed')
        self.assertIn('+2（现有 2）',result['final_response'])
        self.assertNotIn('+99',result['final_response'])
        self.assertEqual(result['final_response'].count('**物品｜'),1)
