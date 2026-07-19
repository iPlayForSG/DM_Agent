"""Rules research subgraph with a private state and registered lookup tool."""

import json
from typing import Any, Dict, Optional

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from .specs import AGENT_SPECS, AgentRole
from .state import RULES_PARENT_FIELDS, RulesState


class RulesResearchAgent:
    """Own automatic rules retrieval without exposing write capabilities."""

    def __init__(self, runner: Any):
        self.runner = runner
        self.role = AgentRole.RULES
        self.spec = AGENT_SPECS[self.role]
        self.tool_names = frozenset(self.spec.tool_names)
        contract = runner.tool_registry.get("lookup_rules")
        if contract is None:
            raise KeyError("Rules Agent requires the registered lookup_rules tool.")

        def lookup(runtime: ToolRuntime[None, RulesState], **_: Any) -> Command:
            result = self.runner._retrieve_rules(dict(runtime.state))
            metadata = dict(result.get("rag_metadata", {}))
            return Command(
                update={
                    **result,
                    "messages": [
                        ToolMessage(
                            content=json.dumps(metadata, ensure_ascii=False, default=str),
                            tool_call_id=runtime.tool_call_id or "rules-lookup",
                            name="lookup_rules",
                        )
                    ],
                }
            )

        self.tools = {
            "lookup_rules": StructuredTool.from_function(
                func=lookup,
                name="lookup_rules",
                description=str(contract.schema.get("description") or "Search local D&D rules."),
                args_schema=dict(contract.schema.get("parameters") or {}),
            )
        }
        self.tool_node = ToolNode(
            list(self.tools.values()),
            name="rules_tools",
            handle_tool_errors=False,
        )
        self.graph = self._build_graph()

    def _enter(self, state: RulesState) -> RulesState:
        return {
            "node_traces": self.runner._append_node_trace(
                state,
                "agent.rules.entered",
                "Rules Agent accepted the research task.",
                {"registered_tools": sorted(self.tool_names)},
            ),
        }

    def _request_lookup(self, state: RulesState) -> RulesState:
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "rules-lookup",
                            "name": "lookup_rules",
                            "args": {
                                "query": str(state.get("user_input") or "D&D 5e rules"),
                                "n_results": 3,
                            },
                        }
                    ],
                )
            ]
        }

    def _build_graph(self):
        builder = StateGraph(RulesState)
        builder.add_node("enter", self._enter)
        builder.add_node("request_lookup", self._request_lookup)
        builder.add_node("tools", self.tool_node)
        builder.add_edge(START, "enter")
        builder.add_edge("enter", "request_lookup")
        builder.add_edge("request_lookup", "tools")
        builder.add_edge("tools", END)
        return builder.compile()

    def as_parent_node(
        self,
        parent_state: Dict[str, Any],
        config: Optional[RunnableConfig] = None,
    ) -> Dict[str, Any]:
        rules_input: RulesState = {
            key: value
            for key, value in parent_state.items()
            if key in RULES_PARENT_FIELDS
        }
        result = self.graph.invoke(rules_input, config=config)
        return {
            key: value
            for key, value in result.items()
            if key in RULES_PARENT_FIELDS
        }
