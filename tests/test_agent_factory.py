import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.specs import AGENT_SPECS, PHASE_CAPABILITY_TOOL_NAMES, AgentRole
from dm_graph import LANGGRAPH_TOOL_SCHEMAS


class DMAgentSpecTests(unittest.TestCase):
    def test_runtime_has_one_dm_identity_and_one_post_commit_projection(self) -> None:
        self.assertEqual(set(AGENT_SPECS), {AgentRole.DM, AgentRole.SUGGESTIONS})
        self.assertNotIn(
            "set_player_action_suggestions",
            AGENT_SPECS[AgentRole.DM].tool_names,
        )
        self.assertEqual(
            AGENT_SPECS[AgentRole.SUGGESTIONS].tool_names,
            ("set_player_action_suggestions",),
        )

    def test_dm_owns_every_phase_capability(self) -> None:
        dm_tools = set(AGENT_SPECS[AgentRole.DM].tool_names)
        for phase, phase_tools in PHASE_CAPABILITY_TOOL_NAMES.items():
            self.assertLessEqual(set(phase_tools), dm_tools, msg=phase)

    def test_runtime_agents_own_every_registered_backend_tool(self) -> None:
        schema_names = {str(schema.get("name") or "") for schema in LANGGRAPH_TOOL_SCHEMAS}
        owned_names = {name for spec in AGENT_SPECS.values() for name in spec.tool_names}
        self.assertEqual(schema_names, owned_names)


if __name__ == "__main__":
    unittest.main()
