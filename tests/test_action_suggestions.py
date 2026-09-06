import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dm_graph import DMGraphRunner
from prompts import build_dm_instruction
from models import AdventureHook, Character, ChatMessage, GameState


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


    def test_conversation_commits_without_reply_suggestions(self) -> None:
        state = self._exploration_state()
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "询问他报酬如何",
                "final_response": "奥德里克摊开手掌，报出镇议会能凑出的金币、补给和一封公会证明。",
                "allowed_tools": [],
                "turn_profile": "conversation",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertNotIn("action_suggestions", result)
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
                "allowed_tools": [],
                "turn_profile": "conversation",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertNotIn("action_suggestions", result)


    def test_action_resolution_commits_without_reply_suggestions(self) -> None:
        state = self._exploration_state()
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "我观察矿坑入口。",
                "final_response": "矿坑入口的木梁已经腐烂，里面传来低沉嗡鸣。",
                "allowed_tools": [],
                "turn_profile": "action_resolution",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertNotIn("action_suggestions", result)
        self.assertIn("矿坑入口", result["final_response"])
        self.assertFalse(
            any(issue["validator"] == "action_suggestion_protocol" for issue in result["validation_issues"])
        )

    def test_inline_action_options_are_removed_without_rolling_back_turn(self) -> None:
        state = self._exploration_state()
        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "我观察矿坑入口。",
                "final_response": "矿坑里传来嗡鸣。你可以调查血迹，或者立刻进入矿坑。",
                "allowed_tools": [],
                "turn_profile": "action_resolution",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "completed")
        self.assertNotIn("action_suggestions", result)
        self.assertEqual(result["final_response"], "矿坑里传来嗡鸣。")

    def test_dm_loop_never_runs_post_commit_suggestion_tool(self) -> None:
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

        self.assertEqual(decision, "finalize_turn")

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

        result = runner._run_dm_model_step(
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
                self.bind_calls = []

            def bind(self, **kwargs):
                self.bind_calls.append(kwargs)
                return self

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
        self.assertEqual(editor_model.bind_calls, [{"max_tokens": 192}])
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(DMGraphRunner._reply_length_issue(rewritten, state))
        self.assertNotIn("冗长的原始叙事", rewritten)
        self.assertIn("压缩", editor_model.calls[0][-1].content)
        self.assertIn("事实与叙事节奏不变", editor_model.calls[0][-1].content)

    def test_finalize_rewrites_short_response_before_committing(self) -> None:
        state = self._exploration_state()
        state.campaign.reply_min_chars = 1000
        state.campaign.reply_max_chars = 2000

        class EditorModel:
            def __init__(self) -> None:
                self.calls = []

            def bind(self, **_kwargs):
                return self

            def invoke(self, messages):
                self.calls.append(messages)
                return type(
                    "EditorResponse",
                    (),
                    {
                        "content": "钟楼石阶上的血迹仍未干涸，祭司确认三名失踪者都曾听见无月钟声。" * 40,
                        "tool_calls": [],
                    },
                )()

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        editor_model = EditorModel()
        runner._model = editor_model

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "我检查钟楼石阶。",
                "final_response": "石阶上有血迹。",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        committed = GameState.model_validate(result["game_state"])
        self.assertEqual(result["turn_status"], "completed")
        self.assertIsNone(DMGraphRunner._reply_length_issue(result["final_response"], committed))
        self.assertNotEqual(result["final_response"], "石阶上有血迹。")
        self.assertEqual(committed.chat_history[-1].content, result["final_response"])
        self.assertIn("扩写", editor_model.calls[0][-1].content)
        self.assertIn("事实与叙事节奏不变", editor_model.calls[0][-1].content)
        length_trace = next(item for item in result["node_traces"] if item["node_name"] == "enforce_reply_length")
        self.assertEqual(length_trace["status"], "completed")
        self.assertEqual(length_trace["metadata"]["attempt_count"], 1)

    def test_finalize_keeps_completed_turn_when_length_expansion_remains_short(self) -> None:
        initial_state = self._exploration_state()
        initial_state.turn_number = 7
        initial_state.campaign.reply_min_chars = 80
        initial_state.campaign.reply_max_chars = 160
        staged_state = initial_state.model_copy(deep=True)
        staged_state.scene = "combat"

        class ShortEditorModel:
            def __init__(self) -> None:
                self.calls = 0

            def bind(self, **_kwargs):
                return self

            def invoke(self, _messages):
                self.calls += 1
                return type(
                    "EditorResponse",
                    (),
                    {"content": "你进入钟楼，湿冷石阶上方传来一阵急促脚步声。", "tool_calls": []},
                )()

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        editor_model = ShortEditorModel()
        runner._model = editor_model

        result = runner._finalize_turn(
            {
                "game_state": staged_state.model_dump(mode="json"),
                "initial_game_state": initial_state.model_dump(mode="json"),
                "user_input": "我冲进钟楼。",
                "final_response": "你进入钟楼。",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        committed = GameState.model_validate(result["game_state"])
        self.assertEqual(editor_model.calls, 3)
        self.assertEqual(result["turn_status"], "completed")
        self.assertNotIn("长度要求", result["final_response"])
        self.assertEqual(committed.turn_number, staged_state.turn_number + 1)
        self.assertEqual(committed.scene, staged_state.scene)
        length_issue = next(issue for issue in result["validation_issues"] if issue["validator"] == "reply_length")
        self.assertEqual(length_issue["severity"], "warning")
        self.assertEqual(length_issue["action"], "accept_best_effort")
        length_trace = next(item for item in result["node_traces"] if item["node_name"] == "enforce_reply_length")
        self.assertEqual(length_trace["status"], "warning")

    def test_failed_turn_skips_reply_length_rewrite(self) -> None:
        state = self._exploration_state()
        state.campaign.reply_min_chars = 80
        state.campaign.reply_max_chars = 160

        class UnexpectedEditorModel:
            def bind(self, **_kwargs):
                return self

            def invoke(self, _messages):
                raise AssertionError("Failed turns must not invoke the reply-length editor.")

        runner = DMGraphRunner(rag_engine=None, tool_service=None, enable_model=False)
        runner._model = UnexpectedEditorModel()
        failure_message = "规则校验失败，本回合没有提交。"

        result = runner._finalize_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": "我发动攻击。",
                "final_response": failure_message,
                "turn_status": "failed",
                "tool_results": [],
                "timeline_append": [],
            }
        )

        self.assertEqual(result["turn_status"], "failed")
        self.assertEqual(result["final_response"], failure_message)
        self.assertFalse(any(item["node_name"] == "enforce_reply_length" for item in result["node_traces"]))


if __name__ == "__main__":
    unittest.main()
