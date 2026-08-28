import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from agent_tools import AgentToolExecution
from agents.specs import AGENT_SPECS, AgentRole
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from models import ActionSuggestion, AdventureHook, Character, GameState


class DMAgentTeamTests(unittest.TestCase):
    def test_graph_registers_one_persistent_dm_brain(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            runner._graph = runner._build_graph()
            dm = runner.dm_agent
            graph_nodes = set(runner._graph.get_graph().nodes)
        finally:
            runner.close()

        self.assertIsNotNone(dm)
        self.assertIn("attack_target", dm.tool_names)
        self.assertIn("create_party_character", dm.tool_names)
        self.assertIn("record_chapter_progress", dm.tool_names)
        self.assertEqual(
            graph_nodes,
            {
                "__start__",
                "prepare_turn",
                "input_gate",
                "plan_turn",
                "route_phase",
                "rules_context",
                "memory_context",
                "dm_agent",
                "finalize_turn",
                "__end__",
            },
        )

    def test_dm_brain_registers_one_real_tool_node(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            runner._graph = runner._build_graph()
            dm = runner.dm_agent

            self.assertIsInstance(dm.tool_node, ToolNode)
            self.assertEqual(set(dm.tools), set(dm.tool_names))
            self.assertTrue(all(isinstance(tool, BaseTool) for tool in dm.tools.values()))
            self.assertIn("attack_target", dm.tools)
            self.assertIn("roll_dice", dm.tools)
            self.assertEqual(
                set(dm.graph.get_graph().nodes),
                {"__start__", "scope", "model", "tools", "validate", "__end__"},
            )
        finally:
            runner.close()

    def test_dm_brain_routes_dm_controlled_no_tool_response_to_validation(self) -> None:
        class MinimalModel:
            def bind_tools(self, tools):
                return self

        runner = DMGraphRunner(
            rag_engine=None,
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = MinimalModel()
        state = GameState(game_id="enemy-turn-route", title="Enemy Turn Route")
        character = Character(name="守誓者", class_name="Fighter")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        logic = GameLogic(state)
        logic.start_encounter(["地精"], enemy_hp=7, enemy_ac=12)
        party = next(item for item in state.encounter.combatants.values() if item.side == "party")
        enemy = next(item for item in state.encounter.combatants.values() if item.side == "enemy")
        logic.set_initiative(party.combatant_id, 18)
        logic.set_initiative(enemy.combatant_id, 8)
        logic.advance_turn()
        try:
            runner._graph = runner._build_graph()
            route = runner.dm_agent._route_after_model(
                {
                    "game_state": state.model_dump(mode="json"),
                    "messages": [AIMessage(content="地精仍在行动。")],
                    "turn_status": "running",
                    "tool_call_rounds": 0,
                    "tool_round_limit": 6,
                }
            )
        finally:
            runner.close()

        self.assertEqual(state.encounter.current_combatant_id, enemy.combatant_id)
        self.assertEqual(route, "validate_state")

    def test_dm_brain_validates_and_advances_dm_controlled_turn(self) -> None:
        class EnemyTurnModel:
            def __init__(self):
                self.calls = 0

            def bind_tools(self, tools):
                return self

            def bind(self, **kwargs):
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(content="地精仍在行动。")
                if self.calls == 2:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-advance-enemy",
                                "name": "advance_turn",
                                "args": {},
                            }
                        ],
                    )
                return AIMessage(content="地精迟疑片刻，没有抓住进攻机会；行动权回到你手中。")

        class AdvanceTurnService:
            def advance_turn(self, state):
                current = GameLogic(state).advance_turn()
                return AgentToolExecution(
                    ok=bool(current),
                    payload={
                        "current_combatant_id": current.combatant_id if current else None,
                        "current_combatant_name": current.name if current else "",
                    },
                    state_patch={
                        "encounter": state.encounter.model_dump(mode="json") if state.encounter else None,
                    },
                )

        model = EnemyTurnModel()
        runner = DMGraphRunner(
            rag_engine=None,
            tool_service=AdvanceTurnService(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        state = GameState(game_id="enemy-turn-loop", title="Enemy Turn Loop")
        character = Character(name="守誓者", class_name="Fighter")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        state.campaign.setup_complete = True
        logic = GameLogic(state)
        logic.start_encounter(["地精"], enemy_hp=7, enemy_ac=12)
        party = next(item for item in state.encounter.combatants.values() if item.side == "party")
        enemy = next(item for item in state.encounter.combatants.values() if item.side == "enemy")
        logic.set_initiative(party.combatant_id, 18)
        logic.set_initiative(enemy.combatant_id, 8)
        logic.advance_turn()
        try:
            runner._graph = runner._build_graph()
            routed = runner._route_phase(
                {
                    "game_state": state.model_dump(mode="json"),
                    "user_input": "我保持警戒。",
                    "state_delta": {},
                }
            )
            result = runner.dm_agent.as_parent_node(
                {
                    **routed,
                    "messages": [],
                    "instruction": "Resolve the authoritative combat turn.",
                    "user_input": "我保持警戒。",
                    "timeline_append": [],
                    "tool_results": [],
                    "node_traces": [],
                    "validation_notes": [],
                    "validation_issues": [],
                    "tool_call_rounds": 0,
                    "turn_status": "running",
                }
            )
        finally:
            runner.close()

        resolved = GameState.model_validate(result["game_state"])
        self.assertEqual(model.calls, 3)
        self.assertEqual(resolved.encounter.current_combatant_id, party.combatant_id)
        self.assertEqual(result["validation_status"], "ok")
        self.assertIn("行动权回到你手中", result["final_response"])
        self.assertIn("dm_controlled_turn", [item["validator"] for item in result["validation_issues"]])
        self.assertIn("execute_tools", [item["node_name"] for item in result["node_traces"]])

    def test_runtime_topology_exposes_dm_and_post_commit_suggestions(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            topology = runner.registered_agent_topology()
            expected = {
                AgentRole.DM.value: sorted(AGENT_SPECS[AgentRole.DM].tool_names),
                AgentRole.SUGGESTIONS.value: sorted(AGENT_SPECS[AgentRole.SUGGESTIONS].tool_names),
            }
            self.assertEqual(topology, expected)
            self.assertIsInstance(runner.dm_agent.tool_node, ToolNode)
            self.assertIsInstance(runner.suggestion_agent.tool_node, ToolNode)
            self.assertTrue(
                all(isinstance(tool, BaseTool) for tool in runner.dm_agent.tools.values())
            )
            self.assertTrue(
                all(isinstance(tool, BaseTool) for tool in runner.suggestion_agent.tools.values())
            )
        finally:
            runner.close()

    def test_rules_context_and_suggestion_projection_are_isolated_services(self) -> None:
        class DisabledRAG:
            def is_ready(self):
                return False

        runner = DMGraphRunner(rag_engine=DisabledRAG(), checkpoint_mode="memory")
        state = GameState(game_id="read-only-agents", title="Read-only Agents")
        character = Character(name="艾拉", class_name="Wizard")
        adventure = AdventureHook(title="旧矿坑阴影", summary="矿坑入口传来异常嗡鸣。")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        state.campaign.available_adventures = [adventure]
        state.campaign.selected_adventure_id = adventure.adventure_id
        state.campaign.setup_complete = True
        state.campaign.phase = "exploration"
        state.scene = "exploration"
        try:
            runner._graph = runner._build_graph()
            rules_result = runner._retrieve_rules(
                {
                    "game_state": state.model_dump(mode="json"),
                    "user_input": "擒抱使用什么检定？",
                    "turn_intent": {},
                    "node_traces": [],
                }
            )
            self.assertIn(
                rules_result["rag_reason"],
                {"RAG engine is not ready", "automatic retrieval disabled"},
            )
            self.assertIn("retrieve_rules", [item["node_name"] for item in rules_result["node_traces"]])

            runner._generate_action_suggestion_projection = lambda *_args, **_kwargs: (
                [
                    ActionSuggestion(label="检查门扣", action="我检查礼拜堂橡木门上的门扣。"),
                    ActionSuggestion(label="查看刮痕", action="我查看橡木门旁的刮痕。"),
                    ActionSuggestion(label="聆听嗡鸣", action="我贴近门缝聆听里面的嗡鸣。"),
                ],
                {"source": "test"},
            )
            suggestions, metadata = runner.suggestion_agent.project(
                state,
                "礼拜堂的橡木门紧闭，门扣旁留着刮痕，门缝里传出嗡鸣。",
                "我观察这扇门。",
            )
            self.assertEqual(len(suggestions), 3)
            self.assertEqual(metadata["tool_name"], "set_player_action_suggestions")
            self.assertTrue(metadata["tool_ok"])
        finally:
            runner.close()

    def test_dm_model_binds_phase_scoped_tools_and_executes_through_tool_node(self) -> None:
        class DiceService:
            def roll_dice(self, state, expression, reason=""):
                return AgentToolExecution(
                    ok=True,
                    payload={"expression": expression, "reason": reason, "total": 11},
                )

        class ToolCallingModel:
            def __init__(self):
                self.calls = 0
                self.bound_tool_batches = []

            def bind_tools(self, tools):
                self.bound_tool_batches.append(list(tools))
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-roll",
                                "name": "roll_dice",
                                "args": {"expression": "1d20", "reason": "观察环境"},
                            }
                        ],
                    )
                return AIMessage(content="骰子落定，你确认了眼前环境的细节。")

        model = ToolCallingModel()
        runner = DMGraphRunner(
            rag_engine=None,
            tool_service=DiceService(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        state = GameState(game_id="dm-tool-node", title="DM ToolNode")
        character = Character(name="艾琳", class_name="Rogue")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        adventure = AdventureHook(title="旧塔回声", summary="调查旧塔中的异响。")
        state.campaign.available_adventures = [adventure]
        state.campaign.selected_adventure_id = adventure.adventure_id
        state.campaign.setup_complete = True
        state.campaign.phase = "exploration"
        state.scene = "exploration"

        try:
            runner._graph = runner._build_graph()
            dm = runner.dm_agent
            result = dm.graph.invoke(
                {
                    "game_state": state.model_dump(mode="json"),
                    "initial_game_state": state.model_dump(mode="json"),
                    "user_input": "我观察四周。",
                    "phase": "exploration",
                    "scene": "exploration",
                    "instruction": "主持这个探索回合。",
                    "allowed_tools": ["roll_dice", "attack_target"],
                    "suggested_tools": [],
                    "tool_round_limit": 2,
                    "tool_call_rounds": 0,
                    "turn_status": "running",
                    "tool_results": [],
                    "timeline_append": [],
                    "state_delta": {},
                    "validation_notes": [],
                    "validation_issues": [],
                    "node_traces": [],
                }
            )
        finally:
            runner.close()

        self.assertEqual(model.calls, 2)
        self.assertTrue(model.bound_tool_batches)
        self.assertTrue(all(isinstance(tool, BaseTool) for tool in model.bound_tool_batches[0]))
        self.assertEqual([tool.name for tool in model.bound_tool_batches[0]], ["roll_dice"])
        self.assertTrue(any(isinstance(message, ToolMessage) for message in result["messages"]))
        self.assertEqual(result["tool_call_rounds"], 1)
        self.assertEqual(result["active_agent"], "dm")

    def test_dm_serialization_removes_unanswered_raw_tool_calls(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            runner._graph = runner._build_graph()
            dm = runner.dm_agent
            message = AIMessage(
                content="",
                additional_kwargs={
                    "tool_calls": [
                        {"id": "call-one", "type": "function", "function": {"name": "roll_dice", "arguments": "{}"}},
                        {"id": "call-two", "type": "function", "function": {"name": "append_adventure_log", "arguments": "{}"}},
                    ]
                },
                tool_calls=[
                    {"id": "call-one", "name": "roll_dice", "args": {"expression": "1d20"}},
                    {"id": "call-two", "name": "append_adventure_log", "args": {"entry": "test"}},
                ],
            )

            result = dm._serialize_tool_batch({"messages": [message], "node_traces": []})
        finally:
            runner.close()

        serialized = result["messages"][-1]
        self.assertEqual([call["id"] for call in serialized.tool_calls], ["call-one"])
        self.assertNotIn("tool_calls", serialized.additional_kwargs)
        self.assertEqual(serialized.invalid_tool_calls, [])


if __name__ == "__main__":
    unittest.main()
