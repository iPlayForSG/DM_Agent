import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.factory import DMAgentFactory
from agents.specs import AGENT_SPECS, AgentRole
from dm_graph import LANGGRAPH_TOOL_SCHEMAS


class DMAgentFactoryTests(unittest.TestCase):
    def test_each_role_receives_only_its_declared_tools(self) -> None:
        tools = {name: object() for name in {
            "lookup_rules", "roll_dice", "roll_skill_check", "roll_saving_throw", "cast_spell", "use_item", "use_feature",
            "record_evidence", "record_search_outcome", "append_adventure_log", "set_scene", "start_encounter",
            "attack_target", "adjust_hp", "add_status", "remove_status", "set_initiative", "roll_initiative",
            "advance_turn", "end_encounter", "set_defeat_state", "add_enemy", "spawn_monster_from_template",
            "add_inventory_item", "record_major_experience", "record_chapter_progress", "set_active_character",
            "save_monster_template",
        }}
        factory = DMAgentFactory(model=object(), tools=tools)

        self.assertEqual(factory.tools_for(AgentRole.RULES), [tools["lookup_rules"]])
        self.assertEqual(factory.tools_for(AgentRole.NARRATOR), [])
        self.assertNotIn(tools["attack_target"], factory.tools_for(AgentRole.EXPLORATION))
        self.assertIn(tools["attack_target"], factory.tools_for(AgentRole.COMBAT))

    def test_create_agent_uses_distinct_name_prompt_and_tool_list(self) -> None:
        lookup = object()
        with patch("agents.factory.create_agent", return_value="compiled") as create_agent:
            result = DMAgentFactory(object(), {"lookup_rules": lookup}).create(AgentRole.RULES)

        self.assertEqual(result, "compiled")
        kwargs = create_agent.call_args.kwargs
        self.assertEqual(kwargs["name"], "dm_rules_agent")
        self.assertEqual(kwargs["tools"], [lookup])
        self.assertIn("Research only", kwargs["system_prompt"])

    def test_agent_roster_owns_every_registered_backend_tool(self) -> None:
        schema_names = {str(schema.get("name") or "") for schema in LANGGRAPH_TOOL_SCHEMAS}
        owned_names = {name for spec in AGENT_SPECS.values() for name in spec.tool_names}
        self.assertEqual(schema_names, owned_names)


if __name__ == "__main__":
    unittest.main()
