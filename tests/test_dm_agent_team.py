import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from dm_graph import DMGraphRunner


class DMAgentTeamTests(unittest.TestCase):
    def test_graph_registers_supervisor_and_specialist_agents(self) -> None:
        runner = DMGraphRunner(rag_engine=None, checkpoint_mode="memory")
        try:
            runner._graph = runner._build_graph()
            roster = runner.specialist_agents
        finally:
            runner.close()

        self.assertEqual(
            {role.value for role in roster},
            {
                "setup",
                "exploration",
                "combat",
                "downtime",
                "level_up",
            },
        )

        combat = next(agent for role, agent in roster.items() if role.value == "combat")
        exploration = next(agent for role, agent in roster.items() if role.value == "exploration")
        self.assertIn("attack_target", combat.tool_names)
        self.assertNotIn("attack_target", exploration.tool_names)
        self.assertEqual(runner.rules_agent.tool_names, frozenset({"lookup_rules"}))


if __name__ == "__main__":
    unittest.main()
