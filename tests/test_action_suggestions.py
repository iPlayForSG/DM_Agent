import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_tools import AgentToolService
from dm_graph import DMGraphRunner, LANGGRAPH_TOOL_SCHEMAS
from game_logic import GameLogic
from prompts import build_dm_instruction
from models import AdventureHook, Character, GameState
from tool_registry import ToolRegistry


class ActionSuggestionTest(unittest.TestCase):
    def _exploration_state(self) -> GameState:
        state = GameState(game_id="suggestions-test", title="Suggestions Test")
        character = Character(name="艾拉", class_name="Wizard", species="Elf", level=1)
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id
        state.scene = "exploration"
        state.campaign.phase = "exploration"
        state.campaign.setup_complete = True
        state.campaign.available_adventures = [
            AdventureHook(
                adventure_id="adv-mine",
                title="旧矿坑阴影",
                summary="商队护卫失踪，线索指向旧矿坑。",
                opening_scene="旧矿坑入口旁有血迹和断裂的短矛。",
            )
        ]
        state.campaign.selected_adventure_id = "adv-mine"
        return state

    def test_trailing_choice_sentence_is_removed_from_player_response(self) -> None:
        response = (
            "你们抵达旧矿坑时，雨水从木梁裂缝里滴落。入口处有血迹，"
            "一截断裂的短矛卡在泥里。你该先调查血迹，还是立刻进入矿坑？"
        )

        cleaned = DMGraphRunner._strip_inline_action_options(response)

        self.assertIn("旧矿坑", cleaned)
        self.assertNotIn("你该先", cleaned)
        self.assertNotIn("还是立刻", cleaned)

    def test_prefixed_inline_choice_sentence_is_removed_from_opening_scene(self) -> None:
        response = (
            "你站在石桥村的烂醉巨人酒馆前，冷雨洒落石板路。"
            "酒馆老板在吧台后压低嗓子提醒，最近有个陌生兜帽人常在黄昏时分向废弃矿道走去。"
            "此刻，你可以先去调查哈拉尔家的现场，或者追踪兜帽人的行迹，"
            "抑或直接深入灰岩矿坑寻找声源。"
        )

        cleaned = DMGraphRunner._strip_inline_action_options(response)

        self.assertIn("烂醉巨人酒馆", cleaned)
        self.assertIn("陌生兜帽人", cleaned)
        self.assertNotIn("此刻，你可以", cleaned)
        self.assertNotIn("抑或直接深入", cleaned)

    def test_trailing_option_list_is_removed_from_player_response(self) -> None:
        response = """守卫把灯举高，门后的走廊传来潮湿的回声。

你可以：
1. 检查门框上的刻痕
2. 询问守卫昨夜看见了谁
3. 点燃火把进入走廊"""

        cleaned = DMGraphRunner._strip_inline_action_options(response)

        self.assertEqual(cleaned, "守卫把灯举高，门后的走廊传来潮湿的回声。")

    def test_builds_three_structured_action_suggestions(self) -> None:
        suggestions = DMGraphRunner._build_action_suggestions(
            self._exploration_state(),
            "守卫指向旧矿坑入口。门边有血迹、脚印和一只被撬开的箱子。",
        )

        self.assertEqual(len(suggestions), 3)
        self.assertTrue(all(item.label and item.action for item in suggestions))
        combined = "\n".join(f"{item.label} {item.action}" for item in suggestions)
        self.assertTrue(any(anchor in combined for anchor in ["旧矿坑", "血迹", "脚印", "箱子"]))
        self.assertFalse(any(item.label in {"询问知情者", "调查线索", "调查现场"} for item in suggestions))

    def test_opening_scene_suggestions_are_scene_specific(self) -> None:
        state = self._exploration_state()
        state.campaign.available_adventures = [
            AdventureHook(
                adventure_id="adv-gray",
                title="灰岩下的低语",
                summary="灰岩矿坑传出嗡鸣，羊群失踪后只留下焦黑蹄印。",
                opening_scene=(
                    "老巡林客哈拉尔递来沾着暗色污迹的碎布，边缘绣有齿痕状符文。"
                    "酒馆老板说陌生兜帽人每到黄昏都会前往废弃矿道。"
                ),
            )
        ]
        state.campaign.selected_adventure_id = "adv-gray"

        suggestions = DMGraphRunner._build_action_suggestions(
            state,
            (
                "哈拉尔的羊群昨夜遭殃，只留下焦黑蹄印。"
                "酒馆老板提到陌生兜帽人，灰岩矿坑方向仍传来低沉嗡鸣。"
            ),
        )

        combined = "\n".join(f"{item.label} {item.action}" for item in suggestions)
        self.assertEqual(len(suggestions), 3)
        self.assertTrue(any(anchor in combined for anchor in ["哈拉尔", "兜帽人", "灰岩矿坑", "碎布", "符文", "蹄印"]))
        self.assertNotIn("最近的知情者", combined)
        self.assertNotIn("眼前最可疑的线索", combined)

    def test_suggestion_tool_requires_exactly_three_items(self) -> None:
        registry = ToolRegistry.from_schemas(LANGGRAPH_TOOL_SCHEMAS)
        state = self._exploration_state()

        result = registry.validate_call(
            state=state,
            tool_name="set_player_action_suggestions",
            args={"suggestions": [{"label": "调查", "action": "我调查现场。"}]},
            allowed_tools=["set_player_action_suggestions"],
        )

        self.assertFalse(result.ok)
        self.assertIn("exactly three", result.error)

    def test_suggestion_tool_rejects_generic_boilerplate(self) -> None:
        registry = ToolRegistry.from_schemas(LANGGRAPH_TOOL_SCHEMAS)
        state = self._exploration_state()

        result = registry.validate_call(
            state=state,
            tool_name="set_player_action_suggestions",
            args={
                "suggestions": [
                    {"label": "询问知情者", "action": "我找最近的知情者交谈，询问这里发生了什么，以及谁掌握更多线索。"},
                    {"label": "调查线索", "action": "我仔细调查眼前最可疑的线索，寻找痕迹、机关或隐藏的信息。"},
                    {"label": "调查现场", "action": "我仔细查看现场，寻找能说明下一步方向的细节。"},
                ]
            },
            allowed_tools=["set_player_action_suggestions"],
        )

        self.assertFalse(result.ok)
        self.assertIn("scene-specific", result.error)

    def test_suggestion_tool_returns_structured_payload_without_state_mutation(self) -> None:
        service = AgentToolService(rag_engine=None, monster_storage=None, rules_catalog=None)
        execution = service.set_player_action_suggestions(
            self._exploration_state(),
            [
                {"label": "查看蹄印", "action": "我仔细调查羊圈附近的焦黑蹄印。"},
                {"label": "追踪兜帽人", "action": "我沿着兜帽人前往废弃矿道的路线寻找足迹。"},
                {"label": "前往矿坑", "action": "我直接去灰岩矿坑入口，但先在外面观察动静。"},
            ],
        )

        self.assertTrue(execution.ok)
        self.assertEqual(len(execution.payload["suggestions"]), 3)
        self.assertIsNone(execution.tool_result)
        self.assertIsNone(execution.timeline_event)
        self.assertEqual(execution.state_patch, {})

    def test_conversation_question_gets_optional_scene_suggestions(self) -> None:
        state = self._exploration_state()
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "询问他报酬如何",
                "final_response": "奥德里克摊开手掌，报出镇议会能凑出的金币、补给和一封公会证明。",
                "allowed_tools": ["set_player_action_suggestions"],
                "turn_profile": "conversation",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertIsInstance(result["action_suggestions"], list)
        self.assertIn("报出镇议会", result["final_response"])

    def test_conversation_finalize_does_not_synthesize_fallback_suggestions(self) -> None:
        state = self._exploration_state()
        state.campaign.available_adventures = [
            AdventureHook(
                adventure_id="adv-blood-moon",
                title="荒原血月",
                summary="鸦林镇东边干河床出现巨型鬣狗爪印，牧童失踪，传闻豺狼人会在古老哨岩等待满月。",
                opening_scene=(
                    "镇长奥德里克·灰木在轮辐与鞍囊酒馆摊开地图，指向东边干河床、"
                    "古老哨岩、老兰登牧童留下的撕烂衬衣和巨型鬣狗爪印。"
                ),
            )
        ]
        state.campaign.selected_adventure_id = "adv-blood-moon"
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "询问他报酬如何",
                "final_response": "奥德里克说镇议会能凑出五十枚金币、一个月免费食宿，还能让你去旧军械库挑一件盾牌或药水。",
                "allowed_tools": ["set_player_action_suggestions"],
                "turn_profile": "conversation",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertEqual(result["action_suggestions"], [])

    def test_conversation_turn_requests_structured_suggestions_without_making_them_transactional(self) -> None:
        state = self._exploration_state()

        self.assertTrue(
            DMGraphRunner._action_suggestions_required(
                state,
                {
                    "turn_profile": "conversation",
                    "allowed_tools": ["set_player_action_suggestions"],
                },
            )
        )

    def test_combat_suggestions_wait_until_control_returns_to_player(self) -> None:
        state = self._exploration_state()
        logic = GameLogic(state)
        logic.start_encounter(["地精"], enemy_hp=7, enemy_ac=12)
        party = next(item for item in state.encounter.combatants.values() if item.side == "party")
        enemy = next(item for item in state.encounter.combatants.values() if item.side == "enemy")
        logic.set_initiative(party.combatant_id, 18)
        logic.set_initiative(enemy.combatant_id, 8)

        self.assertTrue(DMGraphRunner._action_suggestions_required(state, {"turn_profile": "combat_resolution"}))

        logic.advance_turn()

        self.assertEqual(state.encounter.current_combatant_id, enemy.combatant_id)
        self.assertFalse(DMGraphRunner._action_suggestions_required(state, {"turn_profile": "combat_resolution"}))

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        runner._generate_action_suggestion_projection = lambda *_args, **_kwargs: self.fail(
            "Suggestion projection must not call the model during a DM-controlled turn."
        )
        suggestions, metadata = runner.suggestion_agent.project(
            state,
            "地精仍在行动。",
            "我保持警戒。",
        )
        self.assertEqual(suggestions, [])
        self.assertTrue(metadata["skipped"])
        self.assertEqual(metadata["skipped_reason"], "not_player_decision_point")

    def test_action_resolution_commits_before_async_suggestion_projection(self) -> None:
        state = self._exploration_state()
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "我观察矿坑入口。",
                "final_response": "矿坑入口的木梁已经腐烂，里面传来低沉嗡鸣。",
                "allowed_tools": ["set_player_action_suggestions"],
                "turn_profile": "action_resolution",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertEqual(result["action_suggestions"], [])
        self.assertIn("矿坑入口", result["final_response"])
        self.assertFalse(
            any(issue["validator"] == "action_suggestion_protocol" for issue in result["validation_issues"])
        )

    def test_inline_action_options_still_fail_player_facing_narration(self) -> None:
        state = self._exploration_state()
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "我观察矿坑入口。",
                "final_response": "矿坑里传来嗡鸣。你可以调查血迹，或者立刻进入矿坑。",
                "allowed_tools": ["set_player_action_suggestions"],
                "turn_profile": "action_resolution",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "failed")
        self.assertEqual(result["action_suggestions"], [])
        self.assertIn("叙事正文", result["final_response"])

    def test_action_suggestion_tool_can_run_after_regular_tool_budget(self) -> None:
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        decision = runner._should_continue_after_model(
            {
                "messages": [
                    type(
                        "Message",
                        (),
                        {
                            "tool_calls": [
                                {
                                    "name": "set_player_action_suggestions",
                                    "args": {
                                        "suggestions": [
                                            {"label": "侦察矿坑", "action": "我侦察旧矿坑入口。"},
                                            {"label": "追踪兜帽人", "action": "我追踪兜帽人。"},
                                            {"label": "查看蹄印", "action": "我查看蹄印。"},
                                        ]
                                    },
                                }
                            ]
                        },
                    )()
                ],
                "tool_call_rounds": 2,
                "tool_round_limit": 1,
            }
        )

        self.assertEqual(decision, "execute_tools")

    def test_reply_length_preferences_are_prompted_and_measured(self) -> None:
        state = self._exploration_state()
        state.campaign.reply_min_chars = 80
        state.campaign.reply_max_chars = 160
        instruction = build_dm_instruction(
            state_summary="当前在旧矿坑入口。",
            recent_history="玩家：我靠近入口。",
            reply_min_chars=state.campaign.reply_min_chars,
            reply_max_chars=state.campaign.reply_max_chars,
        )

        self.assertIn("minimum 80", instruction)
        self.assertIn("maximum 160", instruction)
        self.assertEqual(DMGraphRunner._visible_reply_char_count("  旧矿坑\n入口  "), 5)
        self.assertEqual(
            DMGraphRunner._reply_length_issue("太短", state)["kind"],
            "too_short",
        )
        self.assertEqual(DMGraphRunner._reply_output_token_limit(state), 192)
        state.campaign.reply_max_chars = 220
        self.assertEqual(DMGraphRunner._reply_output_token_limit(state), 242)
        self.assertIsNone(DMGraphRunner._reply_length_issue("这是一段足够长的回复。" * 8, state))

    def test_tool_call_keeps_complete_arguments_under_reply_token_budget(self) -> None:
        state = self._exploration_state()
        state.campaign.reply_min_chars = 80
        state.campaign.reply_max_chars = 220

        class ToolBudgetModel:
            def __init__(self) -> None:
                self.bind_calls = []

            def bind_tools(self, _schemas):
                return self

            def bind(self, **kwargs):
                self.bind_calls.append(kwargs)
                return self

            def invoke(self, _messages):
                return type(
                    "ToolResponse",
                    (),
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-skill",
                                "name": "roll_skill_check",
                                "args": {
                                    "actor_ref": state.active_character_id,
                                    "skill_name": "Religion",
                                    "dc": 13,
                                    "reason": "辨认礼拜堂石刻",
                                },
                            }
                        ],
                    },
                )()

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        budget_model = ToolBudgetModel()
        runner._model = budget_model

        result = runner._call_model(
            {
                "game_state": state.model_dump(mode="json"),
                "messages": [runner._human_prompt_message("我辨认礼拜堂石刻。")],
                "allowed_tools": ["roll_skill_check"],
                "validation_notes": [],
                "validation_issues": [],
            }
        )

        self.assertIn({"max_tokens": 242}, budget_model.bind_calls)
        tool_call = result["messages"][-1].tool_calls[0]
        self.assertEqual(tool_call["args"]["skill_name"], "Religion")
        self.assertEqual(tool_call["args"]["reason"], "辨认礼拜堂石刻")

    def test_reply_length_editor_uses_plain_model_and_returns_valid_text(self) -> None:
        state = self._exploration_state()
        state.campaign.reply_min_chars = 80
        state.campaign.reply_max_chars = 160

        class EditorModel:
            def __init__(self) -> None:
                self.calls = []

            def invoke(self, messages):
                self.calls.append(messages)
                return type(
                    "EditorResponse",
                    (),
                    {
                        "content": "钟楼石阶上的血迹仍未干涸，祭司确认三名失踪者都曾听见无月钟声。" * 3,
                        "tool_calls": [],
                    },
                )()

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        editor_model = EditorModel()
        runner._model = editor_model

        rewritten, attempts = runner._rewrite_response_to_length("冗长的原始叙事。" * 100, state)

        self.assertEqual(len(editor_model.calls), 1)
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(DMGraphRunner._reply_length_issue(rewritten, state))
        self.assertNotIn("冗长的原始叙事", rewritten)

    def test_action_suggestion_projection_returns_scene_specific_items(self) -> None:
        state = self._exploration_state()

        class ProjectionModel:
            def bind(self, **_kwargs):
                return self

            def invoke(self, _messages):
                return type(
                    "ProjectionResponse",
                    (),
                    {
                        "content": (
                            '{"suggestions":['
                            '{"anchor":"血迹","label":"检查血迹","action":"我检查旧矿坑入口旁的血迹，判断留下它的时间。"},'
                            '{"anchor":"短矛","label":"查看短矛","action":"我查看旧矿坑木梁旁的断裂短矛，寻找所属势力的标记。"},'
                            '{"anchor":"矿坑","label":"侦察矿坑","action":"我绕着旧矿坑入口侦察，确认里面是否有近期活动。"}'
                            "]}"
                        ),
                        "tool_calls": [],
                    },
                )()

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        runner._model = ProjectionModel()
        response = "旧矿坑入口旁有新鲜血迹，腐朽木梁下压着一截断裂短矛。"

        suggestions, metadata = runner._generate_action_suggestion_projection(
            state,
            {"user_input": "我观察旧矿坑入口。"},
            response,
        )

        self.assertEqual(len(suggestions), 3)
        self.assertEqual(metadata["status"], "completed")
        self.assertTrue(all("旧矿坑" in item.action for item in suggestions))

    def test_action_suggestion_projection_falls_back_to_confirmed_scene_anchors(self) -> None:
        state = self._exploration_state()

        class InvalidProjectionModel:
            def bind(self, **_kwargs):
                return self

            def invoke(self, _messages):
                return type(
                    "ProjectionResponse",
                    (),
                    {
                        "content": (
                            '{"suggestions":['
                            '{"label":"调查现场","action":"我寻找能说明下一步方向的细节。"},'
                            '{"label":"保持警戒","action":"我观察可能的伏击。"},'
                            '{"label":"谨慎前进","action":"我沿着最可疑的方向前进。"}'
                            "]}"
                        ),
                        "tool_calls": [],
                    },
                )()

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        runner._model = InvalidProjectionModel()
        response = "礼拜堂橡木门虚掩着，锈锁有三道新刮痕，门缝里传来低沉嗡鸣。"

        suggestions, metadata = runner._generate_action_suggestion_projection(
            state,
            {"user_input": "我检查门扣、锈锁和门缝。"},
            response,
        )

        self.assertEqual(len(suggestions), 3)
        self.assertEqual(metadata["status"], "fallback")
        combined = "\n".join(f"{item.label} {item.action}" for item in suggestions)
        self.assertTrue(all(any(anchor in item.action for anchor in ["礼拜堂", "橡木门", "门扣", "锈锁", "门缝", "刮痕", "嗡鸣"]) for item in suggestions))
        self.assertNotIn("调查现场", combined)

    def test_action_suggestion_fallback_ignores_unconfirmed_player_nouns_and_negated_facts(self) -> None:
        state = self._exploration_state()
        response = "你没有看到任何钥匙或守卫，只有空荡的石室和地上灰尘。"

        suggestions = DMGraphRunner._grounded_action_suggestion_fallback(
            state,
            {"user_input": "我检查祭坛上的红宝石钥匙和躲在柱后的守卫。"},
            response,
        )

        combined = "\n".join(f"{item.label} {item.action}" for item in suggestions)
        self.assertEqual(suggestions, [])
        self.assertNotIn("钥匙", combined)
        self.assertNotIn("守卫", combined)
        self.assertNotIn("祭坛", combined)

    def test_action_suggestion_anchors_ignore_negated_and_figurative_nouns(self) -> None:
        response = (
            "橡木门虚掩着，锈锁有三道新痕。内里无足音，也无烛火。"
            "低沉嗡鸣宛如石棺余震，门缝渗出腐殖土气味。"
        )

        anchors = DMGraphRunner._confirmed_action_anchor_terms(response, limit=24)

        self.assertIn("橡木门", anchors)
        self.assertIn("锈锁", anchors)
        self.assertIn("嗡鸣", anchors)
        self.assertNotIn("足音", anchors)
        self.assertNotIn("烛火", anchors)
        self.assertNotIn("石棺", anchors)


if __name__ == "__main__":
    unittest.main()
