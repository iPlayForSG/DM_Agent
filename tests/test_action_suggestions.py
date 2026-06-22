import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dm_graph import DMGraphRunner
from models import AdventureHook, Character, GameState


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
        self.assertTrue(any("询问" in item.action or "交谈" in item.action for item in suggestions))


if __name__ == "__main__":
    unittest.main()
