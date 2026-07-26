import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from agent_tools import AgentToolService
from agents.specs import AGENT_SPECS, AgentRole
from dm_graph import LANGGRAPH_TOOL_SCHEMAS, PHASE_POLICIES, DMGraphRunner
from models import AdventureHook, GameState
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from tool_registry import ToolRegistry


VALID_CLERIC = {
    "name": "塞琳·晨星",
    "class_name": "Cleric",
    "species": "Human",
    "background_name": "Acolyte",
    "ability_scores": {
        "strength": 12,
        "dexterity": 13,
        "constitution": 14,
        "intelligence": 8,
        "wisdom": 15,
        "charisma": 10,
    },
    "ability_generation_method": "standard_array",
    "skill_proficiencies": ["Medicine", "Persuasion"],
    "cantrips": ["圣火术", "光亮术", "修复术"],
    "prepared_spells": ["祝福术", "疗伤术", "命令术", "防护善恶"],
    "starter_option_id": "package_a",
    "starter_choice_ids": {"holy_symbol": "amulet"},
}


def build_service() -> AgentToolService:
    return AgentToolService(
        rag_engine=None,
        monster_storage=MonsterStorage(),
        rules_catalog=RuleCatalog(),
    )


class SetupCatalogToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = build_service()
        self.state = GameState(game_id="setup-tools", title="setup-tools")

    def test_list_character_options_returns_authoritative_catalog(self) -> None:
        execution = self.service.list_character_options(self.state)

        self.assertTrue(execution.ok)
        self.assertIn("standard_array", execution.payload["ability_generation"])
        self.assertIn("Human", [entry["name"] for entry in execution.payload["species"]])
        self.assertIn("Cleric", [entry["name"] for entry in execution.payload["classes"]])
        self.assertIn("Acolyte", [entry["name"] for entry in execution.payload["backgrounds"]])

    def test_list_character_options_expands_one_named_entry(self) -> None:
        execution = self.service.list_character_options(self.state, "classes", "Cleric")

        self.assertTrue(execution.ok)
        self.assertEqual(execution.payload["entry"]["name"], "Cleric")
        self.assertEqual(execution.payload["entry"]["skills_to_choose"], 2)

    def test_list_character_options_rejects_unknown_category_and_name(self) -> None:
        self.assertFalse(self.service.list_character_options(self.state, "weapons").ok)
        self.assertFalse(self.service.list_character_options(self.state, "classes", "Artificer").ok)
        # 名称过滤只对有解析器的类别有效，起源专长没有独立解析入口。
        self.assertFalse(self.service.list_character_options(self.state, "origin_feats", "Alert").ok)

    def test_list_class_spells_resolves_localized_library_key(self) -> None:
        execution = self.service.list_class_spells(self.state, "Cleric", max_level=0)

        self.assertTrue(execution.ok)
        levels = {entry["level"] for entry in execution.payload["spells"]}
        self.assertEqual(levels, {0})
        self.assertIn("圣火术", [entry["name"] for entry in execution.payload["spells"]])

    def test_list_class_spells_supports_class_listing_and_spell_details(self) -> None:
        listing = self.service.list_class_spells(self.state)
        self.assertTrue(listing.ok)
        self.assertTrue(listing.payload["classes"])

        details = self.service.list_class_spells(self.state, spell_name="疗伤术")
        self.assertTrue(details.ok)
        self.assertEqual(details.payload["spell"]["name"], "疗伤术")

        self.assertFalse(self.service.list_class_spells(self.state, spell_name="不存在的法术").ok)
        self.assertFalse(self.service.list_class_spells(self.state, "Artificer").ok)

    def test_list_starter_equipment_exposes_option_and_choice_ids(self) -> None:
        execution = self.service.list_starter_equipment(self.state, "Cleric")

        self.assertTrue(execution.ok)
        option_ids = [option["id"] for option in execution.payload["options"]]
        self.assertIn("package_a", option_ids)
        package = next(option for option in execution.payload["options"] if option["id"] == "package_a")
        self.assertIn("holy_symbol", [group["id"] for group in package["choices"]])
        self.assertTrue(execution.payload["shop_catalog"])
        self.assertGreater(execution.payload["custom_purchase_budget_gp"], 0)

        self.assertFalse(self.service.list_starter_equipment(self.state, "Cleric", "package_z").ok)
        self.assertFalse(self.service.list_starter_equipment(self.state, "Artificer").ok)


class PartyCharacterToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = build_service()
        self.state = GameState(game_id="party-tools", title="party-tools")

    def test_create_party_character_persists_a_validated_sheet(self) -> None:
        execution = self.service.create_party_character(self.state, **VALID_CLERIC)

        self.assertTrue(execution.ok, execution.error)
        self.assertEqual(len(self.state.characters), 1)
        character = next(iter(self.state.characters.values()))
        self.assertEqual(character.name, "塞琳·晨星")
        self.assertEqual(self.state.active_character_id, character.character_id)
        self.assertEqual(self.state.campaign.phase, "adventure_selection")
        # 派生值来自规则层，不接受模型自报。
        self.assertGreater(character.hp_max, 0)
        self.assertGreater(character.ac, 10)
        self.assertIn(character.character_id, execution.state_patch["characters"])

    def test_create_party_character_rejects_invalid_build_without_partial_write(self) -> None:
        execution = self.service.create_party_character(
            self.state,
            name="半成品",
            class_name="Cleric",
            ability_generation_method="standard_array",
        )

        self.assertFalse(execution.ok)
        self.assertEqual(self.state.characters, {})
        self.assertIsNone(self.state.active_character_id)
        self.assertTrue(execution.error_response["errors"])

    def test_create_party_character_enforces_uniqueness_size_and_setup_window(self) -> None:
        self.assertTrue(self.service.create_party_character(self.state, **VALID_CLERIC).ok)

        duplicate = self.service.create_party_character(self.state, **VALID_CLERIC)
        self.assertFalse(duplicate.ok)
        self.assertIn("already exists", duplicate.error)

        self.state.campaign.party_size_limit = 1
        second = dict(VALID_CLERIC, name="另一个牧师")
        limited = self.service.create_party_character(self.state, **second)
        self.assertFalse(limited.ok)
        self.assertIn("Party size limit", limited.error)

        self.state.campaign.party_size_limit = 4
        self.state.campaign.setup_complete = True
        closed = self.service.create_party_character(self.state, **second)
        self.assertFalse(closed.ok)
        self.assertIn("already complete", closed.error)

    def test_validate_character_sheet_reports_errors_without_mutating(self) -> None:
        self.assertTrue(self.service.create_party_character(self.state, **VALID_CLERIC).ok)
        character = next(iter(self.state.characters.values()))

        ok_result = self.service.validate_character_sheet(self.state, character.name)
        self.assertTrue(ok_result.ok)
        self.assertTrue(ok_result.payload["valid"])
        self.assertEqual(ok_result.payload["errors"], [])

        character.species = "Aarakocra"
        broken = self.service.validate_character_sheet(self.state, character.character_id)
        self.assertTrue(broken.ok)
        self.assertFalse(broken.payload["valid"])
        self.assertTrue(broken.payload["errors"])
        self.assertEqual(broken.state_patch, {})

        self.assertFalse(self.service.validate_character_sheet(self.state, "不存在").ok)


class AdventureSelectionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = build_service()
        self.state = GameState(game_id="adventure-tools", title="adventure-tools")
        self.hook = AdventureHook(
            title="无月钟声",
            summary="钟声在无月之夜响起。",
            opening_scene="你站在钟楼下。",
        )

    def test_select_adventure_hook_requires_a_party(self) -> None:
        self.state.campaign.available_adventures = [self.hook]

        execution = self.service.select_adventure_hook(self.state, self.hook.adventure_id)

        self.assertFalse(execution.ok)
        self.assertIsNone(self.state.campaign.selected_adventure_id)

    def test_select_adventure_hook_advances_campaign_into_chapter_one(self) -> None:
        self.assertTrue(self.service.create_party_character(self.state, **VALID_CLERIC).ok)
        self.state.campaign.available_adventures = [self.hook]

        execution = self.service.select_adventure_hook(self.state, self.hook.adventure_id)

        self.assertTrue(execution.ok, execution.error)
        self.assertEqual(self.state.campaign.selected_adventure_id, self.hook.adventure_id)
        self.assertEqual(self.state.campaign.phase, "exploration")
        self.assertEqual(self.state.scene, "exploration")
        self.assertTrue(self.state.campaign.setup_complete)
        self.assertEqual(self.state.campaign.current_chapter_number, 1)
        self.assertIn("无月钟声", self.state.campaign.current_chapter_title)
        self.assertIn("选择冒险：无月钟声", self.state.adventure_log)

    def test_select_adventure_hook_rejects_unknown_and_repeat_selection(self) -> None:
        self.assertTrue(self.service.create_party_character(self.state, **VALID_CLERIC).ok)
        self.state.campaign.available_adventures = [self.hook]

        self.assertFalse(self.service.select_adventure_hook(self.state, "adv-missing").ok)
        self.assertTrue(self.service.select_adventure_hook(self.state, self.hook.adventure_id).ok)

        repeat = self.service.select_adventure_hook(self.state, self.hook.adventure_id)
        self.assertFalse(repeat.ok)
        self.assertIn("already locked in", repeat.error)


class RemoveCombatantToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = build_service()
        self.state = GameState(game_id="combat-tools", title="combat-tools")
        self.assertTrue(self.service.create_party_character(self.state, **VALID_CLERIC).ok)
        self.assertTrue(self.service.start_encounter(self.state, ["石缚守卫"], 15, 14).ok)

    def test_remove_combatant_drops_one_enemy_from_the_encounter(self) -> None:
        execution = self.service.remove_combatant(self.state, "石缚守卫")

        self.assertTrue(execution.ok, execution.error)
        names = [entry.name for entry in self.state.encounter.combatants.values()]
        self.assertNotIn("石缚守卫", names)

    def test_remove_combatant_refuses_party_members_and_unknown_refs(self) -> None:
        party = self.service.remove_combatant(self.state, "塞琳·晨星")
        self.assertFalse(party.ok)
        self.assertIn("Party members cannot be removed", party.error)

        self.assertFalse(self.service.remove_combatant(self.state, "不存在").ok)
        self.assertIn(
            "塞琳·晨星",
            [entry.name for entry in self.state.encounter.combatants.values()],
        )


class NewToolRegistrationTests(unittest.TestCase):
    """每个新工具都必须同时存在于 schema、guardrail、Agent 归属和阶段白名单。"""

    NEW_TOOLS = (
        "list_character_options",
        "list_class_spells",
        "list_starter_equipment",
        "validate_character_sheet",
        "create_party_character",
        "select_adventure_hook",
        "remove_combatant",
    )

    def test_every_new_tool_has_a_schema_and_a_service_implementation(self) -> None:
        schema_names = {str(schema.get("name") or "") for schema in LANGGRAPH_TOOL_SCHEMAS}
        service = build_service()
        for tool_name in self.NEW_TOOLS:
            self.assertIn(tool_name, schema_names, msg=f"{tool_name} is missing a registered schema")
            self.assertTrue(
                callable(getattr(service, tool_name, None)),
                msg=f"{tool_name} has no AgentToolService implementation",
            )

    def test_every_new_tool_has_a_guardrail_contract(self) -> None:
        registry = ToolRegistry.from_schemas(LANGGRAPH_TOOL_SCHEMAS)
        for tool_name in self.NEW_TOOLS:
            self.assertIsNotNone(registry.get(tool_name), msg=f"{tool_name} has no tool contract")

        self.assertTrue(registry.get("create_party_character").requires_confirmation)
        self.assertTrue(registry.get("select_adventure_hook").requires_confirmation)
        self.assertTrue(registry.get("remove_combatant").needs_active_encounter)
        self.assertEqual(registry.get("list_character_options").side_effect, "read")

    def test_new_tools_reach_the_right_specialists_and_phases(self) -> None:
        setup_tools = set(AGENT_SPECS[AgentRole.SETUP].tool_names)
        combat_tools = set(AGENT_SPECS[AgentRole.COMBAT].tool_names)
        level_up_tools = set(AGENT_SPECS[AgentRole.LEVEL_UP].tool_names)

        self.assertLessEqual(
            {
                "list_character_options",
                "list_class_spells",
                "list_starter_equipment",
                "validate_character_sheet",
                "create_party_character",
                "select_adventure_hook",
            },
            setup_tools,
        )
        self.assertIn("remove_combatant", combat_tools)
        self.assertNotIn("remove_combatant", setup_tools)
        self.assertIn("validate_character_sheet", level_up_tools)
        self.assertNotIn("create_party_character", level_up_tools)

        self.assertIn("create_party_character", PHASE_POLICIES["character_creation"]["tools"])
        self.assertIn("create_party_character", PHASE_POLICIES["party_creation"]["tools"])
        self.assertNotIn("create_party_character", PHASE_POLICIES["adventure_selection"]["tools"])
        self.assertIn("select_adventure_hook", PHASE_POLICIES["adventure_selection"]["tools"])
        self.assertIn("remove_combatant", PHASE_POLICIES["combat"]["tools"])
        self.assertNotIn("remove_combatant", PHASE_POLICIES["exploration"]["tools"])

    def test_compiled_specialists_expose_the_new_tools_at_runtime(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            topology = runner.registered_agent_topology()
        finally:
            runner.close()

        self.assertIn("create_party_character", topology["setup"])
        self.assertIn("select_adventure_hook", topology["setup"])
        self.assertIn("remove_combatant", topology["combat"])
        self.assertNotIn("create_party_character", topology["combat"])


if __name__ == "__main__":
    unittest.main()
