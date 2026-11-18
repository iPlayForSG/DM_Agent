import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
import main as api
from agent_tools import AgentToolService
from level_creation import options, progression
from models import Character, GameState, Stats
from rules_catalog import RuleCatalog
from library import Library


def complete_draft(name="Bard", level=5, subclass_id=""):
    rules = RuleCatalog()
    data = progression()[name]
    character = Character(name="合成建卡", class_name=name, level=level, background_name="Acolyte",
                          stats=Stats(strength=8, dexterity=14, constitution=13, intelligence=10, wisdom=12, charisma=15))
    if level >= 3:
        character.subclass_id = subclass_id or data["subclasses"][0]["id"]
    profile = options(rules, character)
    scores = character.stats.model_dump()
    for unlock in profile["ability_increase_levels"]:
        chosen = min(scores, key=scores.get)
        character.ability_increases[str(unlock)] = [chosen, chosen]
        scores[chosen] += 2
    definition = rules.get_class_def(name)
    background_skills = rules.get_background("Acolyte")["skill_proficiencies"]
    initial = [skill for skill in definition["skill_choices"] if skill not in background_skills][:definition["skills_to_choose"]]
    character.skill_proficiencies = {skill: 1 for skill in [*initial, *background_skills]}
    profile = options(rules, character)
    expertise_pool = list(character.skill_proficiencies)
    if name == "Wizard":
        expertise_pool = [s for s in expertise_pool if s in {"Arcana", "History", "Investigation", "Medicine", "Nature", "Religion"}]
    character.expertise_skills = expertise_pool[:profile["expertise_count"]]
    for spell_level in profile["arcanum_levels"]:
        character.mystic_arcanum[str(spell_level)] = next(spell["name"] for spell in profile["spells"] if spell.get("level") == spell_level)
    if profile["bonus_spell_count"]:
        character.bonus_spells = [s["name"] for s in profile["bonus_spell_options"][:2]]
    profile = options(rules, character)
    character.spells.cantrips = [s["name"] for s in profile["spells"] if s.get("level") == 0 and s["name"] not in profile["forced_cantrips"]][:profile["class_config"]["starting_cantrips"]]
    character.spells.prepared = [s["name"] for s in profile["spells"] if 0 < s.get("level", 0) <= profile["max_spell_level"] and s["name"] not in profile["forced_spells"]][:profile["class_config"]["starting_prepared_spells"]]
    starter = rules.get_starter_options(definition)[0]
    character.starter_option_id = starter["id"]
    character.starter_choice_ids = {group["id"]: group["options"][0]["id"] for group in starter.get("choices", [])}
    return character


class LevelCreationTests(unittest.TestCase):
    def setUp(self):
        self.rules = RuleCatalog()

    def test_level_five_bard_uses_progression_instead_of_level_one(self):
        character = complete_draft()
        character.ability_increases = {"4": ["charisma", "charisma"]}
        result = self.rules.apply_builder_defaults(character)
        self.assertEqual(result.level, 5)
        self.assertEqual(result.experience_points, 6500)
        self.assertEqual(result.hp_max, 33)
        self.assertEqual(result.stats.charisma, 17)
        self.assertEqual(result.base_stats.charisma, 15)
        self.assertEqual({k: v.total for k, v in result.spells.slots.items()}, {"1": 4, "2": 3, "3": 2})
        self.assertEqual(len(result.spells.cantrips), 3)
        self.assertEqual(len(result.spells.prepared), 9)
        self.assertEqual(result.resources["Bardic Inspiration"].max_value, 3)
        self.assertEqual(result.resources["Bardic Inspiration"].recovery, "short_rest")
        self.assertIn("Extra Attack", [f["name"] for f in options(self.rules, complete_draft("Fighter", 5))["features"]])
        self.assertEqual(self.rules.validate_character(result, for_creation=True), [])
        repeated = self.rules.apply_builder_defaults(result.model_copy(deep=True))
        self.assertEqual(repeated.stats.charisma, 17)
        self.assertEqual(repeated.hp_max, 33)
        profile = options(self.rules, result)
        self.assertEqual(profile["weapon_previews"]["Dagger"]["damage_expression"], "1d4+2")
        self.assertEqual(profile["weapon_previews"]["匕首"]["damage_expression"], "1d4+2")

    def test_all_supported_classes_at_representative_levels_create_valid_sheets(self):
        for name in progression():
            for level in (2, 3, 5, 11, 20):
                with self.subTest(name=name, level=level):
                    result = self.rules.apply_builder_defaults(complete_draft(name, level))
                    self.assertEqual(self.rules.validate_character(result, for_creation=True), [])
                    self.assertEqual(result.hp_current, result.hp_max)
                    self.assertTrue(all(feature["level"] <= level for feature in result.class_features))

    def test_subclass_spell_progression_and_automatic_spells_are_separate(self):
        rogue = self.rules.apply_builder_defaults(complete_draft("Rogue", 3, "arcane-trickster"))
        self.assertEqual(rogue.spells.ability, "INT")
        self.assertEqual(rogue.spells.slots["1"].total, 2)
        self.assertEqual(len(rogue.spells.cantrips), 3)  # 两项选择加法师之手。
        self.assertEqual(self.rules.validate_character(rogue, for_creation=True), [])
        cleric = self.rules.apply_builder_defaults(complete_draft("Cleric", 5, "life-domain"))
        self.assertEqual(len(cleric.spells.prepared), 9 + 6)

    def test_land_subclass_does_not_grant_all_four_environment_lists(self):
        character = complete_draft("Druid", 5, "circle-of-the-land")
        arid = options(self.rules, character)
        character.subclass_spell_variant = "Polar Land"
        polar = options(self.rules, character)
        self.assertNotEqual(arid["forced_spells"], polar["forced_spells"])
        fireball = self.rules.library.get_spell_details("Fireball")["name"]
        self.assertIn(fireball, arid["forced_spells"])
        self.assertNotIn(fireball, polar["forced_spells"])

    def test_pact_magic_uses_pact_slots_and_separate_arcanum_resources(self):
        warlock = self.rules.apply_builder_defaults(complete_draft("Warlock", 11))
        self.assertEqual({k: v.total for k, v in warlock.spells.slots.items()}, {"5": 3})
        self.assertEqual(warlock.resources["Mystic Arcanum (6)"].max_value, 1)
        self.assertNotIn("6", warlock.spells.slots)

    def test_invalid_advancement_and_spell_choices_cannot_save(self):
        storage = SimpleNamespace(save_character=Mock())
        for mutate in (
            lambda c: setattr(c, "subclass_id", "not-a-subclass"),
            lambda c: setattr(c, "ability_increases", {"4": ["charisma"]}),
            lambda c: c.ability_increases.update({"2": ["charisma", "charisma"]}),
            lambda c: c.spells.prepared.append(self.rules.library.get_spell_details("Wish")["name"]),
            lambda c: setattr(c, "expertise_skills", ["Athletics", "Athletics"]),
        ):
            character = complete_draft()
            mutate(character)
            with patch.object(api, "char_storage", storage), TestClient(api.app) as client:
                response = client.post("/api/v1/characters", json=character.model_dump(mode="json"))
            self.assertEqual(response.status_code, 400, response.text)
        storage.save_character.assert_not_called()

    def test_api_recomputes_hp_and_slots_and_round_trips_level_choices(self):
        character = complete_draft("Fighter", 8, "champion")
        character.hp_current = character.hp_max = 999
        storage = SimpleNamespace(save_character=Mock())
        with patch.object(api, "char_storage", storage), TestClient(api.app) as client:
            response = client.post("/api/v1/characters", json=character.model_dump(mode="json"))
        self.assertEqual(response.status_code, 200, response.text)
        saved = storage.save_character.call_args.args[0]
        self.assertLess(saved.hp_max, 999)
        restored = Character.model_validate_json(saved.model_dump_json())
        self.assertEqual(restored.level, 8)
        self.assertEqual(restored.subclass_id, "champion")
        self.assertEqual(restored.ability_increases, character.ability_increases)

    def test_options_are_read_only_and_level_limits_are_enforced(self):
        character = complete_draft()
        before = character.model_dump(mode="json")
        options(self.rules, character)
        self.assertEqual(character.model_dump(mode="json"), before)
        with TestClient(api.app) as client:
            for level in (0, 21, 2.5, True):
                response = client.post("/api/v1/rules/character-creation-options", json={"class_name": "Bard", "level": level})
                self.assertEqual(response.status_code, 422)
            response = client.post("/api/v1/rules/character-creation-options", json={"class_name": "Bard"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["level"], 1)

    def test_agent_failure_preserves_party_and_success_uses_selected_level(self):
        service = AgentToolService(None, None, self.rules)
        state = GameState(game_id="level-agent-fixture")
        before = state.model_dump(mode="json")
        failure = service.create_party_character(state, name="测试", class_name="Bard", level=5)
        self.assertFalse(failure.ok)
        self.assertEqual(state.model_dump(mode="json"), before)
        character = complete_draft("Fighter", 2)
        result = service.create_party_character(state, name="测试", class_name="Fighter", level=2,
            species=character.species, background_name=character.background_name,
            ability_scores=character.stats.model_dump(), ability_generation_method="point_buy",
            skill_proficiencies=list(character.skill_proficiencies), starter_option_id=character.starter_option_id,
            starter_choice_ids=character.starter_choice_ids)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(next(iter(state.characters.values())).level, 2)

    def test_bundled_catalog_provides_high_spells_without_private_local_library(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).resolve().parents[1] / "backend/data/spell_catalog_2024.json"
            shutil.copyfile(source, Path(directory) / source.name)
            library = object.__new__(Library)
            library.spells = {}
            library._localized_aliases = None
            library._localized_alias_lookup = None
            with patch("library.DATA_DIR", directory):
                library._load_data()
            self.assertEqual(library.get_spell_details("Wish")["level"], 9)
            self.assertEqual(library.get_spell_details("Fireball")["level"], 3)
            self.assertTrue(any(spell["level"] == 6 for spell in library.get_spells_by_class("魔契师")))
            self.assertNotIn("鍚熸父璇椾汉", library.get_all_classes())


if __name__ == "__main__":
    unittest.main()
