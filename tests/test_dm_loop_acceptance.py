import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from agent_tools import AgentToolExecution
from dm_graph import DMGraphRunner, PROMPT_CONTEXT_MAX_CHARS
from game_logic import GameLogic
from langchain_core.messages import AIMessage
from models import AdventureHook, Character, ChatMessage, GameState


class DisabledRAG:
    def is_ready(self):
        return False


class RecordingModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.bound_tool_names = []

    def bind_tools(self, tools):
        self.bound_tool_names.append([tool.name for tool in tools])
        return self

    def bind(self, **_kwargs):
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("Acceptance model received an unexpected extra invocation.")
        return self.responses.pop(0)


class EvidenceService:
    def record_evidence(
        self,
        state,
        title,
        summary,
        holder_ref="",
        source_ref="",
        location="",
        tags=None,
        add_to_inventory=True,
    ):
        result = GameLogic(state).record_evidence(
            title=title,
            summary=summary,
            holder_ref=holder_ref,
            source_ref=source_ref,
            location=location,
            tags=tags,
            add_to_inventory=add_to_inventory,
        )
        return AgentToolExecution(
            ok=True,
            payload=result["evidence"].model_dump(mode="json"),
            state_patch=result["patch"],
        )


class DMLoopAcceptanceTests(unittest.TestCase):
    @staticmethod
    def build_state() -> GameState:
        state = GameState(game_id="dm-loop-acceptance", title="DM Loop Acceptance")
        character = Character(name="艾琳", class_name="Rogue")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        adventure = AdventureHook(title="旧塔回声", summary="调查旧塔中持续传出的低鸣。")
        state.campaign.available_adventures = [adventure]
        state.campaign.selected_adventure_id = adventure.adventure_id
        state.campaign.setup_complete = True
        state.campaign.phase = "exploration"
        state.scene = "exploration"
        return state

    def test_ordinary_narration_uses_one_dm_model_call(self) -> None:
        model = RecordingModel([AIMessage(content="守卫压低声音，告诉你旧塔昨夜又亮起了灯。")])
        runner = DMGraphRunner(
            rag_engine=DisabledRAG(),
            tool_service=object(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        try:
            result = runner.run_turn(self.build_state(), "我向守卫打听旧塔。")
        finally:
            runner.close()

        self.assertEqual(result.turn_status, "completed")
        self.assertEqual(len(model.calls), 1)
        node_names = [item.node_name for item in result.turn_trace.node_traces]
        self.assertIn("agent.dm.entered", node_names)
        self.assertNotIn("execute_tools", node_names)
        self.assertFalse(
            any(name.startswith(("agent.director", "agent.auditor", "agent.narrator")) for name in node_names)
        )

    def test_dm_proactively_persists_confirmed_clue_in_one_tool_round(self) -> None:
        title = "守卫的午夜证词"
        summary = "守卫亲眼看见旧塔在午夜后亮起异常蓝光。"
        model = RecordingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-record-evidence",
                            "name": "record_evidence",
                            "args": {
                                "title": title,
                                "summary": summary,
                                "source_ref": "守卫",
                                "location": "旧塔外",
                                "tags": ["目击证词", "蓝光"],
                                "add_to_inventory": False,
                            },
                        }
                    ],
                ),
                AIMessage(content="守卫压低声音：昨夜午夜过后，塔顶确实亮起过一阵不自然的蓝光。"),
            ]
        )
        runner = DMGraphRunner(
            rag_engine=DisabledRAG(),
            tool_service=EvidenceService(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        try:
            result = runner.run_turn(self.build_state(), "我问守卫，昨夜他是否亲眼看见旧塔亮灯。")
        finally:
            runner.close()

        self.assertEqual(result.turn_status, "completed")
        self.assertEqual(len(model.calls), 2)
        self.assertTrue(any(item.title == title for item in result.game_state.evidence_records))
        execute_trace = next(
            item for item in result.turn_trace.node_traces if item.node_name == "execute_tools"
        )
        self.assertEqual(execute_trace.metadata["agent_name"], "dm")
        self.assertEqual(execute_trace.metadata["tools"][0]["tool_name"], "record_evidence")

    def test_player_assertion_is_not_treated_as_authoritative_evidence(self) -> None:
        model = RecordingModel(
            [AIMessage(content="老人此前并没有说过蓝灯会闪三次；你需要先向他核实。")]
        )
        runner = DMGraphRunner(
            rag_engine=DisabledRAG(),
            tool_service=EvidenceService(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        try:
            result = runner.run_turn(
                self.build_state(),
                "我记得老人说蓝灯会闪三次，把这条线索记下来。",
            )
        finally:
            runner.close()

        self.assertEqual(result.turn_status, "completed")
        self.assertEqual(result.game_state.evidence_records, [])
        self.assertFalse(any(item.node_name == "execute_tools" for item in result.turn_trace.node_traces))

    def test_committed_narration_is_available_to_the_next_turn(self) -> None:
        first_response = "守卫说，旧塔的灯总在午夜后亮起。"
        model = RecordingModel(
            [
                AIMessage(content=first_response),
                AIMessage(content="他点点头，补充说灯光会持续大约一刻钟。"),
            ]
        )
        runner = DMGraphRunner(
            rag_engine=DisabledRAG(),
            tool_service=object(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        try:
            first = runner.run_turn(self.build_state(), "我询问旧塔灯光出现的时间。")
            second = runner.run_turn(first.game_state, "我追问灯光会持续多久。")
        finally:
            runner.close()

        self.assertEqual(second.turn_status, "completed")
        self.assertEqual(len(model.calls), 2)
        second_turn_context = "\n".join(
            str(getattr(message, "content", "")) for message in model.calls[1]
        )
        self.assertIn(first_response, second_turn_context)

    def test_exploration_phase_never_binds_combat_only_tools(self) -> None:
        model = RecordingModel([AIMessage(content="战斗尚未建立，地精仍在远处的断墙后。")])
        runner = DMGraphRunner(
            rag_engine=DisabledRAG(),
            tool_service=object(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        try:
            result = runner.run_turn(self.build_state(), "我攻击远处尚未进入战斗的地精。")
        finally:
            runner.close()

        self.assertEqual(result.turn_status, "completed")
        self.assertTrue(model.bound_tool_names)
        self.assertNotIn("attack_target", model.bound_tool_names[0])
        self.assertIn("start_encounter", model.bound_tool_names[0])

    def test_dynamic_context_blocks_have_independent_budgets(self) -> None:
        state = self.build_state()
        state.chat_history = [
            ChatMessage(role="user", content="OLDEST_HISTORY " + "旧" * 4000),
            ChatMessage(role="assistant", content="中间记录 " + "中" * 4000),
            ChatMessage(role="user", content="NEWEST_HISTORY " + "新" * 4000),
        ]
        state.adventure_log.append("超长状态 " + "态" * 12000 + " LATEST_STATE_SENTINEL")
        runner = DMGraphRunner(rag_engine=DisabledRAG(), checkpoint_mode="memory")
        try:
            routed = runner._route_phase(
                {
                    "game_state": state.model_dump(mode="json"),
                    "user_input": "继续。",
                    "state_delta": {},
                }
            )
            prepared = runner._prepare_context(
                {
                    **routed,
                    "user_input": "继续。",
                    "rag_context": "TOP_RAG " + "规" * 10000 + " BOTTOM_RAG",
                }
            )
        finally:
            runner.close()

        self.assertLessEqual(
            len(prepared["state_summary"]),
            PROMPT_CONTEXT_MAX_CHARS["state_summary"],
        )
        self.assertLessEqual(
            len(prepared["recent_history"]),
            PROMPT_CONTEXT_MAX_CHARS["recent_history"],
        )
        self.assertIn("Scene: exploration", prepared["state_summary"])
        self.assertIn("LATEST_STATE_SENTINEL", prepared["state_summary"])
        self.assertIn("NEWEST_HISTORY", prepared["recent_history"])
        self.assertNotIn("OLDEST_HISTORY", prepared["recent_history"])
        self.assertIn("TOP_RAG", prepared["instruction"])
        self.assertNotIn("BOTTOM_RAG", prepared["instruction"])
        trace = prepared["node_traces"][-1]
        self.assertEqual(
            set(trace["metadata"]["truncated_contexts"]),
            {"state_summary", "recent_history", "rag_context"},
        )


if __name__ == "__main__":
    unittest.main()
