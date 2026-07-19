import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from agent_tools import AgentToolExecution
from agents.specs import AGENT_SPECS, AgentRole
from dm_graph import DMGraphRunner
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from models import ActionSuggestion, AdventureHook, Character, GameState


class DMAgentTeamTests(unittest.TestCase):
    def test_graph_registers_supervisor_and_specialist_agents(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            runner._graph = runner._build_graph()
            roster = runner.specialist_agents
        finally:
            runner.close()

        self.assertEqual(
            {role.value for role in roster},
            {
                "setup",
                "exploration",
                "combat",
                "downtime",
                "level_up",
            },
        )

        combat = next(agent for role, agent in roster.items() if role.value == "combat")
        exploration = next(agent for role, agent in roster.items() if role.value == "exploration")
        self.assertIn("attack_target", combat.tool_names)
        self.assertNotIn("attack_target", exploration.tool_names)
        self.assertEqual(runner.rules_agent.tool_names, frozenset({"lookup_rules"}))

    def test_specialists_register_real_tools_in_distinct_tool_nodes(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            runner._graph = runner._build_graph()
            combat = runner.specialist_agents[AgentRole.COMBAT]
            exploration = runner.specialist_agents[AgentRole.EXPLORATION]

            self.assertIsInstance(combat.tool_node, ToolNode)
            self.assertIsInstance(exploration.tool_node, ToolNode)
            self.assertIsNot(combat.tool_node, exploration.tool_node)
            self.assertEqual(set(combat.tools), set(combat.tool_names))
            self.assertEqual(set(exploration.tools), set(exploration.tool_names))
            self.assertTrue(all(isinstance(tool, BaseTool) for tool in combat.tools.values()))
            self.assertIn("attack_target", combat.tools)
            self.assertNotIn("attack_target", exploration.tools)
            self.assertEqual(
                set(exploration.graph.get_graph().nodes),
                {"__start__", "scope", "model", "tools", "audit", "__end__"},
            )
        finally:
            runner.close()

    def test_runtime_topology_matches_every_declared_agent_tool(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            topology = runner.registered_agent_topology()
            expected = {
                role.value: sorted(AGENT_SPECS[role].tool_names)
                for role in AgentRole
            }
            self.assertEqual(topology, expected)
            self.assertIsInstance(runner.rules_agent.tool_node, ToolNode)
            self.assertIsInstance(runner.suggestion_agent.tool_node, ToolNode)
            self.assertTrue(
                all(isinstance(tool, BaseTool) for tool in runner.rules_agent.tools.values())
            )
            self.assertTrue(
                all(isinstance(tool, BaseTool) for tool in runner.suggestion_agent.tools.values())
            )
        finally:
            runner.close()

    def test_rules_and_suggestion_agents_execute_their_registered_tool_nodes(self) -> None:
        class DisabledRAG:
            def is_ready(self):
                return False

        runner = DMGraphRunner(rag_engine=DisabledRAG(), checkpoint_mode="memory")
        state = GameState(game_id="read-only-agents", title="Read-only Agents")
        try:
            runner._graph = runner._build_graph()
            rules_result = runner.rules_agent.as_parent_node(
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

    def test_specialist_model_binds_owned_tools_and_executes_through_tool_node(self) -> None:
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
        state = GameState(game_id="specialist-tool-node", title="Specialist ToolNode")
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
            specialist = runner.specialist_agents[AgentRole.EXPLORATION]
            result = specialist.graph.invoke(
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
        self.assertEqual(result["active_agent"], "exploration")


if __name__ == "__main__":
    unittest.main()
