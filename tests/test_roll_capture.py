import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DM_AGENT_SKIP_DOTENV", "1")
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from langchain_core.messages import AIMessage, ToolMessage
import main as api
from ability_scores import AbilityScoreService
from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from game_logic import DiceRoller, GameLogic
from models import Character, ChatMessage, GameState, RollRecord, TurnResult
from player_projection import player_payload
from roll_capture import capture_rolls, dice_context, settle_rolls
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from test_main_streaming import FakeStorage, patched_runtime, parse_sse_events
from turn_stream import emit_turn_stream_event
import test_dm_graph_workflow as fixtures


class RollCaptureTests(unittest.TestCase):
    def service(self):
        return AgentToolService(fixtures.DummyRAGEngine(), MonsterStorage(), RuleCatalog())

    def test_advantage_keeps_every_die_without_changing_result(self):
        with capture_rolls() as capture, dice_context(actor="Hero"), patch("game_logic.random.randint", side_effect=[4, 18]):
            result = DiceRoller.roll_d20(3, "advantage")
        self.assertEqual(result[:2], (18, 21))
        record = capture.records[0]
        self.assertEqual((record.dice, record.kept, record.modifier, record.total), ([4, 18], [18], 3, 21))

    def test_hidden_and_public_identical_rolls_remain_distinct(self):
        with capture_rolls() as capture, patch("game_logic.random.randint", return_value=5):
            service = self.service()
            service.roll_dice(GameState(), "1d6", "hidden reason", "hidden")
            service.roll_dice(GameState(), "1d6", "public reason", "public")
        self.assertEqual(len({record.record_id for record in capture.records}), 2)
        payload = player_payload({"roll_records": [record.model_dump() for record in capture.records]})
        self.assertEqual([record["visibility"] for record in payload["roll_records"]], ["hidden", "public"])
        self.assertEqual([record["total"] for record in payload["roll_records"]], [5, 5])

    def test_attack_damage_and_nested_concentration_are_all_captured(self):
        hero = Character(name="Hero", hp_current=20, hp_max=20, concentration_spell="Bless")
        state = GameState(characters={hero.character_id: hero})
        with capture_rolls() as capture, patch("game_logic.random.randint", side_effect=[15, 2, 3, 1]):
            result = GameLogic(state).resolve_attack("Enemy", hero.character_id, 5, "2d6")
        self.assertEqual(result["damage_total"], 5)
        self.assertEqual([record.kind for record in capture.records], ["attack", "damage", "save"])
        self.assertEqual([record.dice for record in capture.records], [[15], [2, 3], [1]])
        self.assertFalse(capture.records[-1].success)
        self.assertIn("专注", capture.records[-1].reason)

    def test_automatic_initiative_and_ability_pool_are_not_lost(self):
        hero = Character(name="Hero", level=3)
        state = GameState(characters={hero.character_id: hero})
        with capture_rolls() as capture:
            result = self.service().start_encounter(state, ["Enemy"])
        self.assertTrue(result.ok)
        self.assertEqual(len(capture.records), 2)
        self.assertEqual({record.actor for record in capture.records}, {"Hero", "Enemy"})
        self.assertTrue(all(record.kind == "initiative" for record in capture.records))
        with capture_rolls() as abilities:
            AbilityScoreService().generate("rolled")
        self.assertEqual(len(abilities.records), 6)
        for record in abilities.records:
            self.assertEqual(len(record.dice), 4)
            self.assertEqual(record.total, sum(record.dice) - min(record.dice))

    def test_capture_is_request_local(self):
        def worker(actor):
            with capture_rolls() as capture, dice_context(actor=actor):
                DiceRoller.roll("1d1")
            return capture.records
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(worker, ["A", "B"]))
        self.assertEqual([item.actor for item in first], ["A"])
        self.assertEqual([item.actor for item in second], ["B"])

    def test_failed_tool_roll_is_shown_as_not_applied(self):
        class Service:
            def roll_dice(self, state, **args):
                DiceRoller.roll("1d1")
                raise ValueError("synthetic tool failure")
        runner = DMGraphRunner(rag_engine=fixtures.DummyRAGEngine(), tool_service=Service(), enable_model=False)
        try:
            with capture_rolls() as capture:
                result = runner._execute_single_tool(GameState(), "roll_dice", {"expression": "1d1"}, ["roll_dice"])
            self.assertFalse(result.ok)
            self.assertEqual(settle_rolls(capture.records, "completed")[0].settlement, "not_applied")
        finally:
            runner.close()

    def test_reply_binding_and_serialization_do_not_touch_previous_reply(self):
        class Agent:
            async def run_turn(self, state, message):
                with dice_context(visibility="hidden", reason="synthetic hidden check"):
                    DiceRoller.roll("1d1")
                appended = [ChatMessage(role="user", content=message), ChatMessage(role="assistant", content="same reply")]
                state.chat_history.extend(appended)
                return TurnResult(response="same reply", game_state=state, history=state.chat_history, history_append=appended)
        state = GameState(game_id="test", chat_history=[ChatMessage(role="assistant", content="same reply")])
        store = FakeStorage(state)
        with patched_runtime(Agent(), store):
            result, _ = asyncio.run(api._execute_turn_and_save("test", state, "action"))
        self.assertEqual(result.game_state.chat_history[0].roll_records, [])
        saved = GameState.model_validate_json(result.game_state.model_dump_json())
        self.assertEqual(saved.chat_history[-1].roll_records[0].visibility, "hidden")
        self.assertTrue(saved.chat_history[-1].roll_records_recorded)
        self.assertEqual(saved.chat_history[-1].roll_records[0].settlement, "committed")

    def test_roll_receipt_whitelist_does_not_export_extra_fields(self):
        record = RollRecord(record_id="test", expression="1d20", visibility="hidden", total=19).model_dump()
        record["private_reasoning"] = "synthetic excluded metadata"
        projected = player_payload({"roll_records": [record], "tool_results": [{"payload": {"visibility": "hidden", "total": 19}}]})
        self.assertEqual(projected["roll_records"][0]["total"], 19)
        self.assertNotIn("private_reasoning", projected["roll_records"][0])
        self.assertEqual(projected["tool_results"], [])

    def test_paused_rolls_survive_resume_without_duplicate_rolls(self):
        class Model:
            def bind_tools(self, _tools):
                return self
            def invoke(self, messages):
                tools = [message for message in messages if isinstance(message, ToolMessage)]
                if not tools:
                    return AIMessage(content="", tool_calls=[{"id": "roll", "name": "roll_dice", "args": {"expression": "1d1", "visibility": "hidden"}}])
                if tools[-1].name == "roll_dice":
                    return AIMessage(content="", tool_calls=[{"id": "choice", "name": "request_player_choice", "args": {"prompt": "你要继续前进还是返回入口？", "options": ["继续前进", "返回入口"]}}])
                return AIMessage(content="你继续向前。")
        runner = DMGraphRunner(rag_engine=fixtures.DummyRAGEngine(), tool_service=self.service(), enable_model=True,
                               api_key="synthetic", checkpoint_mode="memory")
        runner._model = Model()
        class Agent:
            async def run_turn(self, state, message):
                return runner.run_turn(state, message)
            async def resume_turn(self, state, message):
                return runner.resume_turn(state, message)
        state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        try:
            with patched_runtime(Agent(), FakeStorage(state)):
                paused, _ = asyncio.run(api._execute_turn_request(state, "请先 roll_dice 做一次暗骰，再让我决定是否继续。"))
                self.assertEqual(paused.turn_status, "input_required", paused.response)
                saved = GameState.model_validate_json(paused.game_state.model_dump_json())
                resumed, _ = asyncio.run(api._execute_turn_request(saved, "继续前进"))
            self.assertEqual(resumed.turn_status, "completed", resumed.response)
            self.assertEqual(len(resumed.roll_records), 1)
            self.assertEqual(resumed.roll_records[0].record_id, paused.roll_records[0].record_id)
            self.assertEqual(resumed.roll_records[0].settlement, "committed")
        finally:
            runner.close()

    def test_retry_and_rewrite_stream_real_rolls_before_completion(self):
        class Agent:
            checkpoint_backend = "memory"
            checkpoint_db_path = ""
            async def run_turn(self, state, message):
                emit_turn_stream_event("agent.output.delta", {"text": "先检查门锁。"})
                await asyncio.sleep(.01)
                with dice_context(visibility="hidden"):
                    DiceRoller.roll("1d1")
                state.chat_history.extend([ChatMessage(role="user", content=message), ChatMessage(role="assistant", content="门已经打开。")])
                return TurnResult(response="门已经打开。", game_state=state)

        async def consume(response):
            chunks = [chunk async for chunk in response.body_iterator]
            return parse_sse_events("".join(chunks).splitlines())

        for mode in ("retry", "rewrite"):
            with self.subTest(mode=mode):
                state = GameState(game_id="test", chat_history=[ChatMessage(role="user", content="open"), ChatMessage(role="assistant", content="old")])
                store = FakeStorage(state)
                store.save_rewind_snapshot("test", 0, GameState(game_id="test"))
                with patched_runtime(Agent(), store):
                    if mode == "retry":
                        response = asyncio.run(api.retry_game_message("test", 1, stream=True))
                    else:
                        response = asyncio.run(api.rewrite_game_message("test", 0, api.RewriteMessageRequest(message="open again"), stream=True))
                    events = asyncio.run(consume(response))
                names = [event["event"] for event in events]
                self.assertLess(names.index("agent.output.delta"), names.index("turn.completed"))
                self.assertLess(names.index("roll.recorded"), names.index("turn.completed"))
                self.assertEqual(store.state.chat_history[-1].roll_records[0].visibility, "hidden")

    def test_failed_round_keeps_rolls_but_labels_them_rolled_back(self):
        class Agent:
            async def run_turn(self, state, message):
                DiceRoller.roll("1d1")
                state.chat_history.append(ChatMessage(role="assistant", content="failed"))
                return TurnResult(response="failed", turn_status="failed", game_state=state)
        with patched_runtime(Agent(), FakeStorage(GameState())):
            result, _ = asyncio.run(api._execute_turn_request(GameState(), "action"))
        self.assertEqual(result.roll_records[0].settlement, "rolled_back")
        self.assertEqual(result.game_state.chat_history[-1].roll_records[0].total, 1)


if __name__ == "__main__":
    unittest.main()
