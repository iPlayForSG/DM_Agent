"""Rules research agent subgraph."""

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from .specs import AGENT_SPECS, AgentRole


class RulesResearchAgent:
    """Owns rules retrieval and exposes only the lookup_rules capability."""

    def __init__(self, runner: Any):
        self.runner = runner
        self.role = AgentRole.RULES
        self.spec = AGENT_SPECS[self.role]
        self.tool_names = frozenset(self.spec.tool_names)
        self.graph = self._build_graph()

    def _enter(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "active_agent": self.role.value,
            "node_traces": self.runner._append_node_trace(
                state,
                "agent.rules.entered",
                "Rules agent accepted the research task.",
                {"tools": sorted(self.tool_names)},
            ),
        }

    def _lookup_rules(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.runner._retrieve_rules(state)

    def _build_graph(self):
        builder = StateGraph(self.runner.graph_state_type)
        builder.add_node("enter", self._enter)
        builder.add_node("lookup_rules", self._lookup_rules)
        builder.add_edge(START, "enter")
        builder.add_edge("enter", "lookup_rules")
        builder.add_edge("lookup_rules", END)
        return builder.compile()
