"""Compiled specialist subgraphs with strict per-agent tool ownership."""

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from .specs import AGENT_SPECS, AgentRole


class SpecialistAgent:
    """Owns one model/tool/audit loop and its immutable tool whitelist."""

    def __init__(self, role: AgentRole, runner: Any):
        self.role = role
        self.runner = runner
        self.spec = AGENT_SPECS[role]
        self.tool_names = frozenset(self.spec.tool_names)
        self.graph = self._build_graph()

    def _scope(self, state: Dict[str, Any]) -> Dict[str, Any]:
        phase_tools = list(state.get("allowed_tools", []))
        scoped = [name for name in phase_tools if name in self.tool_names]
        return {
            "allowed_tools": scoped,
            "active_agent": self.role.value,
            "node_traces": self.runner._append_node_trace(
                state,
                f"agent.{self.role.value}.entered",
                f"{self.role.value} specialist accepted the delegated turn.",
                {"tools": scoped},
            ),
        }

    def _model(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.runner._call_model(state) if self.runner.enable_model else self.runner._draft_response_placeholder(state)

    def _tools(self, state: Dict[str, Any]) -> Dict[str, Any]:
        unauthorized = [name for name in state.get("allowed_tools", []) if name not in self.tool_names]
        if unauthorized:
            raise RuntimeError(f"{self.role.value} agent received unauthorized tools: {unauthorized}")
        return self.runner._execute_tools(state)

    def _audit(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.runner._validate_state(state)

    def _build_graph(self):
        builder = StateGraph(self.runner.graph_state_type)
        builder.add_node("scope", self._scope)
        builder.add_node("model", self._model)
        builder.add_node("tools", self._tools)
        builder.add_node("audit", self._audit)
        builder.add_edge(START, "scope")
        builder.add_edge("scope", "model")
        builder.add_conditional_edges(
            "model",
            self.runner._should_continue_after_model,
            {"execute_tools": "tools", "finalize_turn": END},
        )
        builder.add_edge("tools", "audit")
        builder.add_conditional_edges(
            "audit",
            self.runner._should_continue_after_validation,
            {"draft_response": "model", "finalize_turn": END},
        )
        return builder.compile()


def specialist_role_for_phase(phase: str) -> AgentRole:
    return {
        "party_creation": AgentRole.SETUP,
        "character_creation": AgentRole.SETUP,
        "adventure_selection": AgentRole.SETUP,
        "combat": AgentRole.COMBAT,
        "downtime": AgentRole.DOWNTIME,
        "level_up": AgentRole.LEVEL_UP,
    }.get(str(phase or "").strip().lower(), AgentRole.EXPLORATION)
