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
        # 工具面从 schema 派生，新增工具时这里不会再因为硬编码清单而漂移。
        tools = {str(schema["name"]): object() for schema in LANGGRAPH_TOOL_SCHEMAS}
        factory = DMAgentFactory(model=object(), tools=tools)

        self.assertEqual(factory.tools_for(AgentRole.RULES), [tools["lookup_rules"]])
        self.assertEqual(factory.tools_for(AgentRole.NARRATOR), [])
        self.assertNotIn(tools["attack_target"], factory.tools_for(AgentRole.EXPLORATION))
        self.assertIn(tools["attack_target"], factory.tools_for(AgentRole.COMBAT))
        self.assertIn(tools["remove_combatant"], factory.tools_for(AgentRole.COMBAT))
        self.assertNotIn(tools["remove_combatant"], factory.tools_for(AgentRole.EXPLORATION))
        self.assertIn(tools["create_party_character"], factory.tools_for(AgentRole.SETUP))
        self.assertNotIn(tools["create_party_character"], factory.tools_for(AgentRole.LEVEL_UP))

        for role, spec in AGENT_SPECS.items():
            self.assertEqual(
                [tools[name] for name in spec.tool_names],
                factory.tools_for(role),
                msg=f"{role.value} received a tool list that does not match its declaration",
            )

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
