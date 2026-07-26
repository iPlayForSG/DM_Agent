import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from agent_tools import AgentToolService
from agents.specs import AGENT_SPECS, AgentRole
from dm_graph import LANGGRAPH_TOOL_SCHEMAS, PHASE_POLICIES
from encounter_math import (
    MAX_CHARACTER_LEVEL,
    TIER_ABSURD,
    XP_BY_CR,
    _decimal_to_cr,
    classify_encounter,
    estimate_challenge_rating,
    estimate_encounter_difficulty,
    normalize_cr,
    party_xp_budget,
    xp_for_cr,
)
from models import GameState
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from tool_registry import ToolRegistry


def build_service() -> AgentToolService:
    return AgentToolService(
        rag_engine=None,
        monster_storage=MonsterStorage(),
        rules_catalog=RuleCatalog(),
    )


class ChallengeRatingNormalizationTests(unittest.TestCase):
    def test_normalize_cr_accepts_fraction_decimal_and_glyph_forms(self) -> None:
        self.assertEqual(normalize_cr("1/2"), "1/2")
        self.assertEqual(normalize_cr(0.5), "1/2")
        self.assertEqual(normalize_cr("0.25"), "1/4")
        self.assertEqual(normalize_cr("½"), "1/2")
        self.assertEqual(normalize_cr("3"), "3")
        self.assertEqual(normalize_cr(3.0), "3")

    def test_normalize_cr_rejects_unusable_input(self) -> None:
        for value in ("", "bogus", None, "99"):
            self.assertEqual(normalize_cr(value), "", msg=f"{value!r} should not normalize")
        self.assertIsNone(xp_for_cr("bogus"))
        self.assertEqual(xp_for_cr("1/4"), 50)


class DecimalToCrParityTests(unittest.TestCase):
    """The averaged CR buckets must match the 5e.tools calculator exactly."""

    def test_fractional_buckets_match_the_reference_implementation(self) -> None:
        expected = {
            0.0: "0",
            0.0625: "1/8",
            0.125: "1/8",
            0.1875: "1/8",
            0.25: "1/4",
            0.3125: "1/4",
            0.375: "1/4",
            0.5: "1/2",
            0.5625: "1/2",
        }
        for value, cr in expected.items():
            self.assertEqual(_decimal_to_cr(value), cr, msg=f"{value} should bucket to {cr}")

    def test_non_bucketed_decimals_round_half_up_like_javascript(self) -> None:
        # Python 的内建 round 会把 0.625 舍成 0；JS 的 Math.round 舍成 1。
        self.assertEqual(_decimal_to_cr(0.625), "1")
        self.assertEqual(_decimal_to_cr(0.75), "1")
        self.assertEqual(_decimal_to_cr(1.5), "2")
        self.assertEqual(_decimal_to_cr(2.5), "3")
        self.assertEqual(_decimal_to_cr(4.0), "4")


class PartyBudgetTests(unittest.TestCase):
    def test_budget_sums_per_character_thresholds(self) -> None:
        budget = party_xp_budget([1, 1, 1, 1])

        self.assertEqual(budget["low"], 200)
        self.assertEqual(budget["moderate"], 300)
        self.assertEqual(budget["high"], 400)
        # absurd 是 high + (high - moderate) 的外推档。
        self.assertEqual(budget[TIER_ABSURD], 500)

    def test_budget_handles_mixed_levels_and_clamps_out_of_range(self) -> None:
        mixed = party_xp_budget([1, 5])
        self.assertEqual(mixed["low"], 50 + 500)

        clamped = party_xp_budget([99])
        self.assertEqual(clamped["low"], party_xp_budget([MAX_CHARACTER_LEVEL])["low"])

    def test_classification_walks_from_trivial_up_to_absurd(self) -> None:
        budget = party_xp_budget([1, 1, 1, 1])

        self.assertEqual(classify_encounter(0, budget), "trivial")
        self.assertEqual(classify_encounter(199, budget), "trivial")
        self.assertEqual(classify_encounter(200, budget), "low")
        self.assertEqual(classify_encounter(300, budget), "moderate")
        self.assertEqual(classify_encounter(400, budget), "high")
        self.assertEqual(classify_encounter(5000, budget), TIER_ABSURD)


class EncounterDifficultyTests(unittest.TestCase):
    def test_four_quarter_cr_enemies_are_a_low_encounter_for_four_level_ones(self) -> None:
        result = estimate_encounter_difficulty(
            [1, 1, 1, 1],
            [{"name": "Goblin", "challenge_rating": "1/4", "count": 4}],
        )

        self.assertEqual(result["encounter_xp"], 200)
        self.assertEqual(result["difficulty"], "low")
        self.assertEqual(result["breakdown"][0]["xp_each"], XP_BY_CR["1/4"])
        self.assertEqual(result["breakdown"][0]["xp_total"], 200)

    def test_solo_level_one_against_cr_two_is_over_budget(self) -> None:
        result = estimate_encounter_difficulty([1], [{"name": "Ogre", "challenge_rating": "2"}])

        self.assertEqual(result["encounter_xp"], 450)
        self.assertEqual(result["difficulty"], TIER_ABSURD)

    def test_unknown_challenge_ratings_are_reported_not_silently_dropped(self) -> None:
        result = estimate_encounter_difficulty(
            [1, 1],
            [
                {"name": "Goblin", "challenge_rating": "1/4"},
                {"name": "Mystery", "challenge_rating": "unknown"},
            ],
        )

        self.assertEqual(result["encounter_xp"], 50)
        self.assertEqual(result["unknown_challenge_ratings"], ["Mystery(unknown)"])

    def test_empty_party_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            estimate_encounter_difficulty([], [{"challenge_rating": "1"}])


class ChallengeRatingEstimateTests(unittest.TestCase):
    def test_goblin_shaped_statistics_land_on_cr_one_quarter(self) -> None:
        result = estimate_challenge_rating(hp=7, ac=15, damage_per_round=5, attack_bonus=4)

        self.assertEqual(result["challenge_rating"], "1/4")
        self.assertEqual(result["defensive_cr"], "1/4")
        self.assertEqual(result["offensive_cr"], "1/4")
        self.assertEqual(result["experience_points"], 50)
        self.assertEqual(result["attack_metric"], "attack_bonus")

    def test_save_dc_replaces_attack_bonus_when_supplied(self) -> None:
        result = estimate_challenge_rating(hp=60, ac=13, damage_per_round=20, save_dc=15)

        self.assertEqual(result["attack_metric"], "save_dc")
        self.assertEqual(result["attack_value"], 15)

    def test_extreme_statistics_clamp_instead_of_indexing_past_cr_thirty(self) -> None:
        result = estimate_challenge_rating(hp=99999, ac=30, damage_per_round=99999, attack_bonus=30)

        self.assertTrue(result["clamped"])
        self.assertEqual(result["challenge_rating"], "30")
        self.assertEqual(result["effective_hp"], 99999)

    def test_invalid_statistics_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            estimate_challenge_rating(hp=0, ac=10, damage_per_round=5)
        with self.assertRaises(ValueError):
            estimate_challenge_rating(hp=10, ac=0, damage_per_round=5)
        with self.assertRaises(ValueError):
            estimate_challenge_rating(hp=10, ac=10, damage_per_round=-1)


class EncounterMathToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = build_service()
        self.state = GameState(game_id="encounter-math", title="encounter-math")
        self.assertTrue(
            self.service.create_party_character(
                self.state,
                name="格雷姆",
                class_name="Fighter",
                species="Goliath",
                background_name="Guard",
                ability_scores={
                    "strength": 15,
                    "dexterity": 13,
                    "constitution": 14,
                    "intelligence": 8,
                    "wisdom": 10,
                    "charisma": 12,
                },
                ability_generation_method="standard_array",
                skill_proficiencies=["Survival", "Intimidation"],
                starter_option_id="package_a",
            ).ok
        )

    def test_tool_defaults_to_live_party_levels(self) -> None:
        execution = self.service.estimate_encounter_difficulty(
            self.state,
            enemies=[{"name": "Goblin", "challenge_rating": "1/4", "count": 2}],
        )

        self.assertTrue(execution.ok, execution.error)
        self.assertEqual(execution.payload["party_levels"], [1])
        self.assertEqual(execution.payload["encounter_xp"], 100)
        self.assertEqual(execution.payload["enemy_source"], "arguments")
        self.assertEqual(execution.state_patch, {})

    def test_tool_scores_the_active_encounter_when_enemies_are_omitted(self) -> None:
        self.assertTrue(self.service.start_encounter(self.state, ["石缚守卫"], 15, 14).ok)

        execution = self.service.estimate_encounter_difficulty(self.state)

        self.assertTrue(execution.ok, execution.error)
        self.assertEqual(execution.payload["enemy_source"], "active_encounter")
        # 即兴敌人没有模板 CR，必须按防御面估算并如实标注来源。
        row = next(item for item in execution.payload["breakdown"] if item["name"] == "石缚守卫")
        self.assertEqual(row["cr_source"], "estimated_from_defense")
        self.assertTrue(row["challenge_rating"])

    def test_template_backed_combatants_keep_their_declared_challenge_rating(self) -> None:
        saved = self.service.save_monster_template(
            self.state, name="石缚守卫", challenge_rating="1/2", hp_max=15, ac=14
        )
        self.assertTrue(saved.ok, saved.error)
        self.assertTrue(self.service.start_encounter(self.state, [], 0, 0).ok)
        self.assertTrue(self.service.spawn_monster_from_template(self.state, "石缚守卫", 2).ok)

        execution = self.service.estimate_encounter_difficulty(self.state)

        self.assertTrue(execution.ok, execution.error)
        # spawn 会给每只怪单独命名，所以按名称分组后是多行；聚合后才是这一组的总量。
        template_rows = [item for item in execution.payload["breakdown"] if item["cr_source"] == "template"]
        self.assertEqual({row["challenge_rating"] for row in template_rows}, {"1/2"})
        self.assertEqual(sum(row["count"] for row in template_rows), 2)
        self.assertEqual(sum(row["xp_total"] for row in template_rows), 200)

    def test_tool_reports_when_nothing_can_be_scored(self) -> None:
        execution = self.service.estimate_encounter_difficulty(self.state)

        self.assertFalse(execution.ok)
        self.assertIn("challenge ratings", execution.error)

    def test_monster_cr_tool_compares_against_a_declared_template(self) -> None:
        saved = self.service.save_monster_template(
            self.state,
            name="石缚守卫",
            challenge_rating="1/4",
            hp_max=7,
            ac=15,
        )
        self.assertTrue(saved.ok, saved.error)

        execution = self.service.estimate_monster_cr(
            self.state,
            hp=7,
            ac=15,
            damage_per_round=5,
            attack_bonus=4,
            monster_ref="石缚守卫",
        )

        self.assertTrue(execution.ok, execution.error)
        self.assertEqual(execution.payload["challenge_rating"], "1/4")
        self.assertEqual(execution.payload["declared_challenge_rating"], "1/4")
        self.assertTrue(execution.payload["matches_declared"])
        self.assertEqual(execution.state_patch, {})

    def test_monster_cr_tool_rejects_unknown_reference_and_bad_statistics(self) -> None:
        self.assertFalse(
            self.service.estimate_monster_cr(
                self.state, hp=7, ac=15, damage_per_round=5, monster_ref="不存在的怪物"
            ).ok
        )
        self.assertFalse(self.service.estimate_monster_cr(self.state, hp=0, ac=15, damage_per_round=5).ok)


class EncounterMathRegistrationTests(unittest.TestCase):
    NEW_TOOLS = ("estimate_encounter_difficulty", "estimate_monster_cr")

    def test_tools_are_registered_as_read_only_across_play_phases(self) -> None:
        schema_names = {str(schema.get("name") or "") for schema in LANGGRAPH_TOOL_SCHEMAS}
        registry = ToolRegistry.from_schemas(LANGGRAPH_TOOL_SCHEMAS)
        service = build_service()

        for tool_name in self.NEW_TOOLS:
            self.assertIn(tool_name, schema_names)
            self.assertTrue(callable(getattr(service, tool_name, None)))
            contract = registry.get(tool_name)
            self.assertIsNotNone(contract)
            self.assertEqual(contract.side_effect, "read")
            self.assertFalse(contract.requires_confirmation)
            self.assertFalse(contract.needs_active_encounter)

            for role in (AgentRole.EXPLORATION, AgentRole.COMBAT, AgentRole.DOWNTIME):
                self.assertIn(tool_name, AGENT_SPECS[role].tool_names)
            for phase in ("exploration", "combat", "downtime"):
                self.assertIn(tool_name, PHASE_POLICIES[phase]["tools"])
            self.assertNotIn(tool_name, AGENT_SPECS[AgentRole.SETUP].tool_names)


class ImportedBuilderCatalogTests(unittest.TestCase):
    """The 5e.tools import must stay usable by the authoritative build validator."""

    def setUp(self) -> None:
        self.catalog = RuleCatalog()

    def test_imported_species_and_backgrounds_are_resolvable(self) -> None:
        for species in ("Human", "Goliath", "Tiefling", "Dragonborn"):
            self.assertIsNotNone(self.catalog.get_species(species), msg=species)
        for background in ("Acolyte", "Guard", "Noble", "Scribe"):
            self.assertIsNotNone(self.catalog.get_background(background), msg=background)

    def test_every_background_origin_feat_exists_in_the_catalog(self) -> None:
        feat_names = {entry["name"] for entry in self.catalog.data.get("origin_feats", [])}
        for background in self.catalog.data.get("backgrounds", []):
            origin_feat = background.get("origin_feat")
            if origin_feat:
                self.assertIn(origin_feat, feat_names, msg=f"{background['name']} -> {origin_feat}")

    def test_every_background_skill_is_a_known_skill(self) -> None:
        from rules_catalog import SKILL_TO_ABILITY

        for background in self.catalog.data.get("backgrounds", []):
            for skill in background.get("skill_proficiencies", []):
                self.assertIn(skill, SKILL_TO_ABILITY, msg=f"{background['name']} -> {skill}")

    def test_imported_options_build_a_valid_character(self) -> None:
        service = build_service()
        state = GameState(game_id="imported-build", title="imported-build")

        execution = service.create_party_character(
            state,
            name="格雷姆",
            class_name="Fighter",
            species="Goliath",
            background_name="Guard",
            ability_scores={
                "strength": 15,
                "dexterity": 13,
                "constitution": 14,
                "intelligence": 8,
                "wisdom": 10,
                "charisma": 12,
            },
            ability_generation_method="standard_array",
            skill_proficiencies=["Survival", "Intimidation"],
            starter_option_id="package_a",
        )

        self.assertTrue(execution.ok, execution.error)
        self.assertEqual(execution.payload["species"], "Goliath")


if __name__ == "__main__":
    unittest.main()
