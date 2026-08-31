"""Persistent DM Brain with a private model/tool/validation loop."""

from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from models import GameState

from .specs import AGENT_SPECS, AgentRole
from .state import DM_BRAIN_PARENT_FIELDS, DMBrainState
from .tool_adapters import AgentToolFactory


class GameMasterAgent:
    """One DM identity backed by phase-scoped deterministic tools."""

    def __init__(self, runner: Any):
        self.role = AgentRole.DM
        self.runner = runner
        self.spec = AGENT_SPECS[self.role]
        self.tool_names = frozenset(self.spec.tool_names)
        self.tools = AgentToolFactory(self.role, runner).create_all()
        self.tool_node = ToolNode(
            list(self.tools.values()),
            name="dm_tools",
            handle_tool_errors=False,
        )
        self.graph = self._build_graph()

    def _scope(self, state: DMBrainState) -> DMBrainState:
        game_state = GameState.model_validate(state["game_state"])
        phase_tools = set(
            self.runner._allowed_tool_names(game_state, phase=str(state.get("phase") or ""))
        )
        # 父图负责给出任务子集，这里再次与权威阶段能力取交集，避免调用方扩大权限。
        scoped = [
            name
            for name in state.get("allowed_tools", [])
            if name in self.tool_names and name in phase_tools
        ]
        return {
            "allowed_tools": scoped,
            "active_agent": self.role.value,
            "agent_role": self.role.value,
            "node_traces": self.runner._append_node_trace(
                state,
                "agent.dm.entered",
                "The persistent DM Brain accepted the turn.",
                {
                    "phase": str(state.get("phase") or ""),
                    "registered_tools": sorted(self.tool_names),
                    "available_tools": scoped,
                },
            ),
        }

    def _model(self, state: DMBrainState) -> DMBrainState:
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
        result = self.runner._run_dm_model_step(state, model=model)
        return self._serialize_tool_batch(result)

    def _serialize_tool_batch(self, result: Dict[str, Any]) -> DMBrainState:
        """Allow one state-writing call per step so tools never race GameState."""

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
                "agent.dm.tool_batch_serialized",
                "Multiple requested tools were serialized to preserve atomic state writes.",
                {
                    "accepted_tool": str(first_call.get("name") or ""),
                    "deferred_tools": [str(item.get("name") or "") for item in tool_calls[1:]],
                },
            ),
        }

    def _validate(self, state: DMBrainState) -> DMBrainState:
        return self.runner._validate_state(state)

    def _route_after_model(self, state: DMBrainState) -> str:
        route = self.runner._should_continue_after_model(state)
        if route != "finalize_turn":
            return route
        if self.runner.enable_model and self.runner._authoritative_resolution_pending(state):
            return "validate_state"
        if self.runner.enable_model and self.runner._dm_controlled_turn_pending(state):
            return "validate_state"
        return "finalize_turn"

    def _build_graph(self):
        builder = StateGraph(DMBrainState)
        builder.add_node("scope", self._scope)
        builder.add_node("model", self._model)
        builder.add_node("tools", self.tool_node)
        builder.add_node("validate", self._validate)
        builder.add_edge(START, "scope")
        builder.add_edge("scope", "model")
        builder.add_conditional_edges(
            "model",
            self._route_after_model,
            {"execute_tools": "tools", "validate_state": "validate", "finalize_turn": END},
        )
        builder.add_edge("tools", "validate")
        builder.add_conditional_edges(
            "validate",
            self.runner._should_continue_after_validation,
            {"draft_response": "model", "finalize_turn": END},
        )
        return builder.compile()

    def as_parent_node(
        self,
        parent_state: Dict[str, Any],
        config: Optional[RunnableConfig] = None,
    ) -> Dict[str, Any]:
        dm_input: DMBrainState = {
            key: value
            for key, value in parent_state.items()
            if key in DM_BRAIN_PARENT_FIELDS
        }
        dm_input["agent_role"] = self.role.value
        dm_input["instruction"] = (
            f"Persistent DM contract:\n{self.spec.system_prompt}\n\n"
            + str(parent_state.get("instruction") or "")
        ).strip()
        result = self.graph.invoke(dm_input, config=config)
        return {
            key: value
            for key, value in result.items()
            if key in DM_BRAIN_PARENT_FIELDS
        }
