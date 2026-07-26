"""Compiled Specialist agents with private state and real ToolNode tools."""

from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .specs import AGENT_SPECS, AgentRole
from .state import SPECIALIST_PARENT_FIELDS, SpecialistState
from .tool_adapters import SpecialistToolFactory


class SpecialistAgent:
    """Own one isolated model/ToolNode/audit loop and immutable tool roster."""

    def __init__(self, role: AgentRole, runner: Any):
        self.role = role
        self.runner = runner
        self.spec = AGENT_SPECS[role]
        self.tool_names = frozenset(self.spec.tool_names)
        self.tools = SpecialistToolFactory(role, runner).create_all()
        self.tool_node = ToolNode(
            list(self.tools.values()),
            name=f"{role.value}_tools",
            handle_tool_errors=False,
        )
        self.graph = self._build_graph()

    def _scope(self, state: SpecialistState) -> SpecialistState:
        scoped = [
            name
            for name in state.get("allowed_tools", [])
            if name in self.tool_names
        ]
        return {
            "allowed_tools": scoped,
            "active_agent": self.role.value,
            "agent_role": self.role.value,
            "node_traces": self.runner._append_node_trace(
                state,
                f"agent.{self.role.value}.entered",
                f"{self.role.value} Specialist accepted the delegated turn.",
                {"registered_tools": sorted(self.tool_names), "available_tools": scoped},
            ),
        }

    def _model(self, state: SpecialistState) -> SpecialistState:
        if not self.runner.enable_model:
            return self.runner._draft_response_placeholder(state)

        available_names = [
            name
            for name in state.get("allowed_tools", [])
            if name in self.tools
        ]
        model = self.runner._create_model()
        if available_names:
            model = model.bind_tools([self.tools[name] for name in available_names])
        result = self.runner._call_model(state, model=model)
        return self._serialize_tool_batch(result)

    def _serialize_tool_batch(self, result: Dict[str, Any]) -> SpecialistState:
        """Allow one state-writing call per model step so ToolNode never races GameState."""

        messages = list(result.get("messages", []))
        if not messages:
            return result
        last_message = messages[-1]
        tool_calls = self.runner._last_message_tool_calls([last_message])
        if len(tool_calls) <= 1:
            return result

        first_call = tool_calls[0]
        if isinstance(last_message, AIMessage):
            additional_kwargs = dict(last_message.additional_kwargs or {})
            additional_kwargs.pop("tool_calls", None)
            serialized_message = last_message.model_copy(
                update={
                    "tool_calls": [first_call],
                    "invalid_tool_calls": [],
                    "additional_kwargs": additional_kwargs,
                }
            )
        else:
            serialized_message = AIMessage(
                content=self.runner._extract_message_content(last_message),
                tool_calls=[first_call],
            )
        return {
            **result,
            "messages": [*messages[:-1], serialized_message],
            "node_traces": self.runner._append_node_trace(
                {**result, "node_traces": result.get("node_traces", [])},
                f"agent.{self.role.value}.tool_batch_serialized",
                "Multiple requested tools were serialized to preserve atomic state writes.",
                {
                    "accepted_tool": str(first_call.get("name") or ""),
                    "deferred_tools": [str(item.get("name") or "") for item in tool_calls[1:]],
                },
            ),
        }

    def _audit(self, state: SpecialistState) -> SpecialistState:
        return self.runner._validate_state(state)

    def _route_after_model(self, state: SpecialistState) -> str:
        route = self.runner._should_continue_after_model(state)
        if route != "finalize_turn":
            return route
        if self.runner.enable_model and self.runner._dm_controlled_turn_pending(state):
            return "audit_state"
        return "finalize_turn"

    def _build_graph(self):
        builder = StateGraph(SpecialistState)
        builder.add_node("scope", self._scope)
        builder.add_node("model", self._model)
        builder.add_node("tools", self.tool_node)
        builder.add_node("audit", self._audit)
        builder.add_edge(START, "scope")
        builder.add_edge("scope", "model")
        builder.add_conditional_edges(
            "model",
            self._route_after_model,
            {"execute_tools": "tools", "audit_state": "audit", "finalize_turn": END},
        )
        builder.add_edge("tools", "audit")
        builder.add_conditional_edges(
            "audit",
            self.runner._should_continue_after_validation,
            {"draft_response": "model", "finalize_turn": END},
        )
        return builder.compile()

    def as_parent_node(
        self,
        parent_state: Dict[str, Any],
        config: Optional[RunnableConfig] = None,
    ) -> Dict[str, Any]:
        """Map parent state into private state and return only parent-owned channels."""

        specialist_input: SpecialistState = {
            key: value
            for key, value in parent_state.items()
            if key in SPECIALIST_PARENT_FIELDS
        }
        specialist_input["agent_role"] = self.role.value
        specialist_input["instruction"] = (
            f"Specialist role contract:\n{self.spec.system_prompt}\n\n"
            + str(parent_state.get("instruction") or "")
        ).strip()
        result = self.graph.invoke(specialist_input, config=config)
        return {
            key: value
            for key, value in result.items()
            if key in SPECIALIST_PARENT_FIELDS
        }


def specialist_role_for_phase(phase: str) -> AgentRole:
    return {
        "party_creation": AgentRole.SETUP,
        "character_creation": AgentRole.SETUP,
        "adventure_selection": AgentRole.SETUP,
        "combat": AgentRole.COMBAT,
        "downtime": AgentRole.DOWNTIME,
        "level_up": AgentRole.LEVEL_UP,
    }.get(str(phase or "").strip().lower(), AgentRole.EXPLORATION)
