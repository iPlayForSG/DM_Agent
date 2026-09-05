import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from agent_tools import AgentToolExecution
from dm_graph import DMGraphRunner, PROMPT_CONTEXT_MAX_CHARS
from game_logic import GameLogic
from langchain_core.messages import AIMessage
from models import AdventureHook, Character, ChatMessage, EvidenceRecord, GameState, ToolResult


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


class HostileCombatService:
    def start_encounter(self, state, enemy_names, enemy_hp=7, enemy_ac=12, auto_roll_initiative=True):
        del auto_roll_initiative
        logic = GameLogic(state)
        encounter = logic.start_encounter(enemy_names, enemy_hp=enemy_hp, enemy_ac=enemy_ac)
        for combatant in encounter.combatants.values():
            logic.set_initiative(combatant.combatant_id, 30 if combatant.linked_character_id else 5)
        return AgentToolExecution(
            ok=True,
            tool_result=ToolResult(
                tool_name="encounter.start",
                summary="遭遇开始",
                payload={"enemy_names": enemy_names},
            ),
            state_patch={
                "scene": state.scene,
                "campaign": {"phase": state.campaign.phase},
                "encounter": state.encounter.model_dump(mode="json"),
            },
        )

    def attack_target(self, state, attacker_ref, target_ref, **_kwargs):
        outcome = GameLogic(state).resolve_attack(
            attacker_ref=attacker_ref,
            target_ref=target_ref,
            attack_bonus=99,
            damage_expression="1d4",
            damage_type="piercing",
        )
        return AgentToolExecution(
            ok=bool(outcome),
            tool_result=(
                ToolResult(
                    tool_name="combat.attack_target",
                    summary="玩家攻击已结算",
                    payload={
                        "attacker_name": outcome["attacker_name"],
                        "target_name": outcome["target_name"],
                        "hit": outcome["hit"],
                    },
                )
                if outcome
                else None
            ),
            state_patch={"encounter": state.encounter.model_dump(mode="json")} if outcome else {},
            error="" if outcome else "attack failed",
        )


class HostileCombatModel:
    def __init__(self):
        self.bound_tool_names = []
        self.active_tool_names = []
        self.attacked = False

    def bind_tools(self, tools):
        self.active_tool_names = [tool.name for tool in tools]
        self.bound_tool_names.append(list(self.active_tool_names))
        return self

    def bind(self, **_kwargs):
        return self

    def invoke(self, _messages):
        if self.attacked:
            return AIMessage(content="你抢在地精反应前刺出匕首，刀锋与命中结果已经完成结算。")
        if "start_encounter" in self.active_tool_names and "attack_target" not in self.active_tool_names:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-start-ambush",
                        "name": "start_encounter",
                        "args": {"enemy_names": ["地精"], "enemy_hp": 7, "enemy_ac": 12},
                    }
                ],
            )
        if "attack_target" in self.active_tool_names:
            self.attacked = True
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-resolve-ambush",
                        "name": "attack_target",
                        "args": {"attacker_ref": "艾琳", "target_ref": "地精", "attack_name": "匕首"},
                    }
                ],
            )
        raise AssertionError(f"Unexpected hostile combat tool scope: {self.active_tool_names}")


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
        model_trace = next(item for item in result.turn_trace.node_traces if item.node_name == "draft_response")
        self.assertEqual(model_trace.metadata["model_call_count"], 1)
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
        traced_model_calls = sum(
            int(item.metadata.get("model_call_count", 0))
            for item in result.turn_trace.node_traces
            if item.node_name == "draft_response"
        )
        self.assertEqual(traced_model_calls, 2)
        self.assertEqual(execute_trace.metadata["agent_name"], "dm")
        self.assertEqual(execute_trace.metadata["tools"][0]["tool_name"], "record_evidence")
        first_turn_context = "\n".join(
            str(getattr(message, "content", "")) for message in model.calls[0]
        )
        self.assertIn("handed to, accepted by, or kept", first_turn_context)

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

        self.assertEqual(result.turn_status, "failed")
        self.assertTrue(model.bound_tool_names)
        self.assertNotIn("attack_target", model.bound_tool_names[0])
        self.assertIn("start_encounter", model.bound_tool_names[0])

    def test_hostile_exploration_action_starts_and_attacks_in_same_player_turn(self) -> None:
        model = HostileCombatModel()
        runner = DMGraphRunner(
            rag_engine=DisabledRAG(),
            tool_service=HostileCombatService(),
            enable_model=True,
            api_key="test-key",
            checkpoint_mode="memory",
        )
        runner._model = model
        try:
            # 此用例只验证普通敌对行动；需要 Hide 裁定的伏击由 surprise_rules 回归覆盖。
            result = runner.run_turn(self.build_state(), "攻击我面前的地精")
        finally:
            runner.close()

        self.assertEqual(result.turn_status, "completed")
        self.assertIsNotNone(result.game_state.encounter)
        self.assertTrue(result.game_state.encounter.active)
        self.assertEqual(
            [item.tool_name for item in result.tool_results],
            ["encounter.start", "combat.attack_target"],
        )
        self.assertNotIn("attack_target", model.bound_tool_names[0])
        self.assertIn("start_encounter", model.bound_tool_names[0])
        self.assertTrue(any(scope == ["attack_target"] for scope in model.bound_tool_names[1:]))

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

    def test_long_history_keeps_current_scene_latest_decision_and_unresolved_clue(self) -> None:
        state = self.build_state()
        state.campaign.current_chapter_number = 2
        state.campaign.current_chapter_title = "第二章：西侧回廊"
        state.campaign.current_chapter_summary = "队伍正在断钟塔西侧回廊搜寻失踪的书记员。"
        active = state.get_active_char()
        self.assertIsNotNone(active)
        active.major_experiences.append("队伍最新决定：先救书记员，不追黑袍人。")
        state.evidence_records.extend(
            EvidenceRecord(title=f"旧线索 {index}", summary="只用于挤压长期上下文预算。" + "旧" * 260)
            for index in range(12)
        )
        state.evidence_records.append(
            EvidenceRecord(
                title="西墙冷风",
                summary="第三块石砖后持续渗出冷风，来源尚未解决。",
                location="断钟塔西侧回廊",
                tags=["未解决"],
            )
        )
        state.chat_history = [
            ChatMessage(
                role="assistant" if index % 2 else "user",
                content=f"过往闲谈 {index}：" + "噪" * 900,
            )
            for index in range(12)
        ]

        runner = DMGraphRunner(rag_engine=DisabledRAG(), checkpoint_mode="memory")
        try:
            routed = runner._route_phase(
                {
                    "game_state": state.model_dump(mode="json"),
                    "user_input": "回想我们现在的位置、最新决定和未解决线索。",
                    "state_delta": {},
                }
            )
            prepared = runner._prepare_context({**routed, "rag_context": ""})
        finally:
            runner.close()

        instruction = prepared["instruction"]
        self.assertIn("第二章：西侧回廊", instruction)
        self.assertIn("先救书记员", instruction)
        self.assertIn("第三块石砖", instruction)
        self.assertLessEqual(
            len(prepared["recent_history"]),
            PROMPT_CONTEXT_MAX_CHARS["recent_history"],
        )
        self.assertIn(
            "recent_history",
            prepared["node_traces"][-1]["metadata"]["truncated_contexts"],
        )


if __name__ == "__main__":
    unittest.main()
