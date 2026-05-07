import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("RAG_AUTO_CONTEXT_RESULTS", "0")

from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import AdventureHook, Character, GameState


class DummyRAGEngine:
    def is_ready(self) -> bool:
        return False


class DMGraphWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=object(),
            enable_model=False,
        )

    @staticmethod
    def _build_state(with_selected_adventure: bool = False) -> GameState:
        state = GameState(game_id="qa-workflow", title="QA Workflow")
        character = Character(name="凯德", class_name="Fighter")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id

        hook = AdventureHook(
            title="黑冢余烬",
            summary="矿村下方的封闭墓道重新冒出了烟。",
        )
        state.campaign.available_adventures = [hook]

        if with_selected_adventure:
            state.campaign.selected_adventure_id = hook.adventure_id
            state.campaign.setup_complete = True
            state.scene = "exploration"
            state.campaign.phase = "exploration"
        else:
            state.scene = "exploration"
            state.campaign.phase = "exploration"

        return state

    def test_route_phase_normalizes_to_adventure_selection_before_setup(self) -> None:
        state = self._build_state(with_selected_adventure=False)

        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )

        normalized = GameState.model_validate(routed["game_state"])
        self.assertEqual(routed["phase"], "adventure_selection")
        self.assertEqual(normalized.scene, "setup")
        self.assertEqual(normalized.campaign.phase, "adventure_selection")
        self.assertNotIn("start_encounter", routed["allowed_tools"])
        self.assertIn("No selected adventure is locked in yet.", routed["phase_blockers"])
        self.assertEqual(routed["state_delta"]["scene"], "setup")
        self.assertEqual(routed["state_delta"]["campaign"]["phase"], "adventure_selection")

    def test_prepare_context_includes_phase_guidance(self) -> None:
        state = self._build_state(with_selected_adventure=False)
        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )

        prepared = self.runner._prepare_context(
            {
                **routed,
                "game_state": routed["game_state"],
                "user_input": "给我介绍这几个冒险",
                "rag_context": "",
            }
        )

        instruction = prepared["instruction"]
        self.assertIn("Current workflow phase:", instruction)
        self.assertIn("adventure_selection", instruction)
        self.assertIn("Do not begin active exploration or combat until an adventure hook is selected.", instruction)

    def test_validate_state_restores_combat_phase_for_active_encounter(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["地精"], enemy_hp=7, enemy_ac=12)

        state.scene = "exploration"
        state.campaign.phase = "exploration"

        validated = self.runner._validate_state(
            {
                "game_state": state.model_dump(mode="json"),
                "messages": [],
                "timeline_append": [],
                "state_delta": {},
            }
        )

        normalized = GameState.model_validate(validated["game_state"])
        self.assertEqual(normalized.scene, "combat")
        self.assertEqual(normalized.campaign.phase, "combat")
        self.assertIn("attack_target", validated["allowed_tools"])
        self.assertIn("advance_turn", validated["allowed_tools"])
        self.assertIn(
            "Forced campaign phase back to combat while encounter is active.",
            validated["validation_notes"],
        )

    def test_level_up_phase_disables_encounter_tools(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        state.scene = "level_up"
        state.campaign.phase = "level_up"

        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )

        self.assertEqual(routed["phase"], "level_up")
        self.assertEqual(routed["scene"], "level_up")
        self.assertIn("record_major_experience", routed["allowed_tools"])
        self.assertNotIn("start_encounter", routed["allowed_tools"])
        self.assertNotIn("attack_target", routed["allowed_tools"])


if __name__ == "__main__":
    unittest.main()
