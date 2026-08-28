"""LangChain tool adapters backed by the authoritative AgentToolService."""

from typing import Any, Dict

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import Command

from agent_tools import merge_patch
from models import GameState

from .specs import AGENT_SPECS, AgentRole
from .state import DMBrainState


class AgentToolFactory:
    """Create real tools for a runtime actor while preserving local guardrails."""

    def __init__(self, role: AgentRole, runner: Any):
        self.role = role
        self.runner = runner
        self.tool_names = frozenset(AGENT_SPECS[role].tool_names)

    def create_all(self) -> Dict[str, BaseTool]:
        return {name: self.create(name) for name in sorted(self.tool_names)}

    def create(self, tool_name: str) -> BaseTool:
        if tool_name not in self.tool_names:
            raise KeyError(f"{self.role.value} does not own tool: {tool_name}")
        contract = self.runner.tool_registry.get(tool_name)
        if contract is None:
            raise KeyError(f"Unknown registered tool: {tool_name}")

        def execute(runtime: ToolRuntime[None, DMBrainState], **kwargs: Any) -> Command:
            return self._execute(tool_name, runtime, dict(kwargs))

        return StructuredTool.from_function(
            func=execute,
            name=tool_name,
            description=str(contract.schema.get("description") or f"Execute {tool_name}."),
            args_schema=dict(contract.schema.get("parameters") or {"type": "object", "properties": {}}),
        )

    def _execute(
        self,
        tool_name: str,
        runtime: ToolRuntime[None, DMBrainState],
        args: Dict[str, Any],
    ) -> Command:
        graph_state = dict(runtime.state)
        state = GameState.model_validate(graph_state["game_state"])
        allowed_tools = [
            name
            for name in graph_state.get("allowed_tools", [])
            if name in self.tool_names
        ]
        guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name=tool_name,
            args=args,
            allowed_tools=allowed_tools,
        )
        confirmation_status = ""

        if not guardrail.ok:
            execution = self.runner._tool_error_execution(
                tool_name,
                guardrail.error,
                guardrail.metadata,
            )
        else:
            repair_error = self.runner._repair_tool_call_error(
                graph_state,
                tool_name,
                guardrail.args,
            )
            if repair_error:
                execution = self.runner._tool_error_execution(
                    tool_name,
                    repair_error,
                    guardrail.metadata,
                )
            elif guardrail.metadata.get("requires_confirmation"):
                confirmed, confirmation_error = self.runner._confirm_tool_execution(
                    graph_state,
                    tool_name,
                    guardrail.args,
                    guardrail,
                )
                confirmation_status = "confirmed" if confirmed else "cancelled"
                execution = (
                    self.runner._execute_single_tool(state, tool_name, guardrail.args, allowed_tools)
                    if confirmed
                    else self.runner._tool_error_execution(
                        tool_name,
                        confirmation_error,
                        guardrail.metadata,
                    )
                )
            else:
                execution = self.runner._execute_single_tool(
                    state,
                    tool_name,
                    guardrail.args,
                    allowed_tools,
                )

        tool_results = list(graph_state.get("tool_results", []))
        timeline_append = list(graph_state.get("timeline_append", []))
        state_delta = dict(graph_state.get("state_delta", {}))
        if execution.ok:
            if execution.timeline_event:
                state.timeline.append(execution.timeline_event)
                timeline_append.append(execution.timeline_event.model_dump(mode="json"))
            if execution.tool_result:
                tool_results.append(execution.tool_result.model_dump(mode="json"))
            if execution.state_patch:
                state_delta = merge_patch(state_delta, execution.state_patch)

        tool_round = int(graph_state.get("tool_call_rounds", 0) or 0) + 1
        trace_metadata = {
            "agent_name": self.role.value,
            "tool_call_count": 1,
            "tool_result_count": len(tool_results),
            "tool_round": tool_round,
            "tools": [
                {
                    "tool_name": tool_name,
                    "ok": execution.ok,
                    "error": execution.error,
                    "guardrail": dict(guardrail.metadata),
                    "confirmation_status": confirmation_status,
                }
            ],
        }
        tool_message = ToolMessage(
            content=self.runner._tool_message_content(execution, confirmation_status),
            tool_call_id=runtime.tool_call_id or tool_name,
            name=tool_name,
        )
        return Command(
            update={
                "game_state": state.model_dump(mode="json"),
                "messages": [tool_message],
                "tool_results": tool_results,
                "timeline_append": timeline_append,
                "state_delta": state_delta,
                "tool_call_rounds": tool_round,
                "allowed_tools": allowed_tools,
                "active_agent": self.role.value,
                "node_traces": self.runner._append_node_trace(
                    graph_state,
                    "execute_tools",
                    f"{self.role.value} ToolNode executed one registered tool.",
                    trace_metadata,
                    status="completed" if execution.ok else "failed",
                ),
            }
        )
