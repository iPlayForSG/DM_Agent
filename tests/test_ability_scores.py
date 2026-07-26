import os
import random
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from ability_scores import ABILITY_NAMES, AbilityScoreService
from agent_tools import AgentToolService
from models import AbilityScoreRoll, Character, GameState, Stats
from rules_catalog import RuleCatalog


class AbilityScoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = RuleCatalog()

    def test_standard_array_uses_catalog_values(self) -> None:
        result = AbilityScoreService(self.catalog).generate("standard_array")

        self.assertEqual(result["method"], "standard_array")
        self.assertEqual([entry["score"] for entry in result["pool"]], [15, 14, 13, 12, 10, 8])
        self.assertEqual(result["rolls"], [])

    def test_point_buy_reports_budget_and_rejects_overspend(self) -> None:
        service = AbilityScoreService(self.catalog)
        scores = dict(zip(ABILITY_NAMES, [15, 15, 15, 8, 8, 8]))

        result = service.generate("point_buy", scores)

        self.assertEqual(result["point_buy"]["spent"], 27)
        self.assertEqual(result["point_buy"]["remaining"], 0)
        with self.assertRaisesRegex(ValueError, "exceeds budget"):
            service.generate("point_buy", dict(zip(ABILITY_NAMES, [15, 15, 15, 15, 8, 8])))

    def test_rolled_generation_records_reproducible_four_d6_drop_lowest(self) -> None:
        first = AbilityScoreService(self.catalog, random.Random(2024)).generate("rolled")
        second = AbilityScoreService(self.catalog, random.Random(2024)).generate("rolled")

        self.assertEqual(first, second)
        self.assertEqual(len(first["rolls"]), 6)
        for roll in first["rolls"]:
            self.assertEqual(len(roll["dice"]), 4)
            self.assertEqual(roll["dice"][roll["dropped_index"]], min(roll["dice"]))
            self.assertEqual(roll["total"], sum(roll["dice"]) - min(roll["dice"]))

    def test_catalog_accepts_recorded_pool_and_rejects_tampering(self) -> None:
        generated = AbilityScoreService(self.catalog, random.Random(9)).generate("rolled")
        scores = {name: generated["pool"][index]["score"] for index, name in enumerate(ABILITY_NAMES)}
        character = Character(
            name="Ability Tester",
            class_name="",
            ability_generation_method="rolled",
            ability_rolls=[AbilityScoreRoll.model_validate(item) for item in generated["rolls"]],
            stats=Stats.model_validate(scores),
        )

        valid_errors = self.catalog.validate_character(character)
        self.assertNotIn("Assigned ability scores do not match the recorded rolled pool", valid_errors)
        self.assertFalse(any("Ability roll" in error for error in valid_errors))

        character.ability_rolls[0].dropped_index = (
            character.ability_rolls[0].dropped_index + 1
        ) % 4
        while (
            character.ability_rolls[0].dice[character.ability_rolls[0].dropped_index]
            == min(character.ability_rolls[0].dice)
        ):
            character.ability_rolls[0].dropped_index = (
                character.ability_rolls[0].dropped_index + 1
            ) % 4

        tampered_errors = self.catalog.validate_character(character)
        self.assertTrue(any("must drop one of its lowest dice" in error for error in tampered_errors))

    def test_agent_tool_uses_same_service_without_mutating_game_state(self) -> None:
        service = AgentToolService(MagicMock(), MagicMock(), self.catalog)
        state = GameState(game_id="ability-tool-test")
        before = state.model_dump(mode="json")

        execution = service.generate_ability_scores(state, "standard_array")

        self.assertTrue(execution.ok)
        self.assertEqual(execution.payload["method"], "standard_array")
        self.assertEqual(execution.tool_result.tool_name, "character.generate_ability_scores")
        self.assertEqual(state.model_dump(mode="json"), before)


if __name__ == "__main__":
    unittest.main()
