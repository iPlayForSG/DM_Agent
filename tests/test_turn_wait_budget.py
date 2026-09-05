import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")
from turn_stream import turn_time_budget, remaining_turn_seconds
from langchain_core.messages import AIMessage
import test_dm_graph_workflow as fixtures


class TurnWaitBudgetTests(unittest.TestCase):
    def test_model_calls_share_remaining_budget_and_context_resets(self):
        with patch("turn_stream.time.monotonic", side_effect=[100, 110, 129, 131]):
            with turn_time_budget(30):
                self.assertEqual(remaining_turn_seconds(300), 20)
                self.assertEqual(remaining_turn_seconds(300), 1)
                with self.assertRaisesRegex(RuntimeError, "等待时限"):
                    remaining_turn_seconds(300)
        self.assertEqual(remaining_turn_seconds(300), 300)

    def test_expired_real_graph_rolls_back_successful_tool_before_final_response(self):
        state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        character = state.characters[state.active_character_id]
        # 用独立 Runner 和合成模型验证：第一次工具成功后，下一次模型调用不能续期。
        from dm_graph import DMGraphRunner
        from agent_tools import AgentToolService
        from rules_catalog import RuleCatalog
        from storage import MonsterStorage
        service = AgentToolService(fixtures.DummyRAGEngine(), MonsterStorage(), RuleCatalog())
        runner = DMGraphRunner(rag_engine=fixtures.DummyRAGEngine(), tool_service=service, enable_model=True, checkpoint_mode="memory")
        clock = [0.0]
        class Model(fixtures.StagedWriteThenChoiceModel):
            def bind(self, **_kwargs): return self
            def invoke(self, _messages):
                if self.calls == 0:
                    return super().invoke(_messages)
                self.calls += 1
                clock[0] = 31.0
                return AIMessage(content="late")
        model = Model(character.character_id)
        successful_writes = []
        original_adjust = service.adjust_hp
        def record_adjust(*args, **kwargs):
            execution = original_adjust(*args, **kwargs)
            successful_writes.append(execution.ok)
            return execution
        try:
            with patch.object(runner, "_create_model", return_value=model), patch.object(service, "adjust_hp", side_effect=record_adjust), patch("turn_stream.time.monotonic", side_effect=lambda: clock[0]):
                with turn_time_budget(30):
                    result = runner.run_turn(state, "请用 adjust_hp 扣除1点生命，再描述结果。")
            self.assertEqual(result.turn_status, "failed")
            self.assertEqual(successful_writes, [True])
            self.assertEqual(result.game_state.characters[character.character_id].hp_current, character.hp_current)
            self.assertEqual(result.game_state.turn_number, state.turn_number)
        finally:
            runner.close()

    def test_enemy_first_downs_last_player_then_encounter_ends_without_turn_loop(self):
        from dm_graph import DMGraphRunner
        from agent_tools import AgentToolService
        from rules_catalog import RuleCatalog
        from storage import MonsterStorage
        from game_logic import GameLogic
        state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        character = state.get_active_char()
        character.hp_current = 1
        logic = GameLogic(state)
        encounter = logic.start_encounter(["合成地精"], enemy_hp=7, enemy_ac=12)
        party = next(c for c in encounter.combatants.values() if c.side == "party")
        enemy = next(c for c in encounter.combatants.values() if c.side == "enemy")
        logic.set_initiative(party.combatant_id, 12)
        logic.set_initiative(enemy.combatant_id, 18)
        service = AgentToolService(fixtures.DummyRAGEngine(), MonsterStorage(), RuleCatalog())
        runner = DMGraphRunner(rag_engine=fixtures.DummyRAGEngine(), tool_service=service, enable_model=True, checkpoint_mode="memory")
        class Model:
            calls = 0
            tool_sets = []
            def bind_tools(self, tools):
                self.tool_sets.append([tool.name for tool in tools])
                return self
            def bind(self, **_kwargs): return self
            def invoke(self, _messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(content="先按先攻顺序结算敌方动作。", tool_calls=[{
                        "id": "attack", "name": "attack_target", "args": {
                            "attacker_ref": enemy.combatant_id, "target_ref": character.character_id,
                            "attack_bonus": 3, "damage_expression": "1d6",
                        }}])
                if self.calls == 2:
                    return AIMessage(content="战斗进入收尾。", tool_calls=[{"id":"end", "name":"end_encounter", "args":{}}])
                return AIMessage(content="你倒在地上，暂时无法继续攻击。")
        model = Model()
        runner._model = model
        try:
            with patch("game_logic.random.randint", side_effect=[15, 3]):
                result = runner.run_turn(state, "找准角度再次偷袭地精。")
            self.assertEqual(result.turn_status, "completed")
            self.assertFalse(result.game_state.encounter.active)
            self.assertEqual(result.game_state.get_active_char().defeat_state, "unconscious")
            self.assertEqual(model.calls, 3)
            self.assertIn("end_encounter", model.tool_sets[1])
            self.assertNotIn("advance_turn", model.tool_sets[1])
        finally:
            runner.close()

    def test_validation_repairs_cannot_extend_tool_budget_forever(self):
        from dm_graph import DMGraphRunner
        from game_logic import GameLogic
        state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        encounter = logic.start_encounter(["合成敌人"])
        for combatant in encounter.combatants.values():
            logic.set_initiative(combatant.combatant_id, 18 if combatant.side == "enemy" else 12)
        runner = DMGraphRunner(rag_engine=fixtures.DummyRAGEngine(), tool_service=object(), checkpoint_mode="memory")
        try:
            validated = runner._validate_state({"game_state": state.model_dump(mode="json"), "messages": [],
                                                "tool_call_rounds": 12, "tool_round_limit": 12})
            self.assertEqual(validated["turn_status"], "failed")
            self.assertTrue(any(issue["validator"] == "repair_budget" for issue in validated["validation_issues"]))
        finally:
            runner.close()
