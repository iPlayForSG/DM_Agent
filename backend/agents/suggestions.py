"""Post-commit Suggestion Agent with structured output and a registered UI tool."""

import json
from typing import Annotated, Any, Dict, List, TypedDict

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from models import ActionSuggestion, GameState

from .specs import AGENT_SPECS, AgentRole


class SuggestionState(TypedDict, total=False):
    game_state: Dict[str, Any]
    response: str
    user_input: str
    messages: Annotated[List[Any], add_messages]
    suggestions: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class SuggestionAgent:
    def __init__(self, runner: Any):
        self.runner = runner
        self.role = AgentRole.SUGGESTIONS
        self.spec = AGENT_SPECS[self.role]
        self.tool_names = frozenset(self.spec.tool_names)
        contract = runner.tool_registry.get("set_player_action_suggestions")
        if contract is None:
            raise KeyError("Suggestion Agent requires set_player_action_suggestions.")

        def set_suggestions(
            runtime: ToolRuntime[None, SuggestionState],
            **kwargs: Any,
        ) -> Command:
            graph_state = dict(runtime.state)
            game_state = GameState.model_validate(graph_state["game_state"])
            guardrail = self.runner.tool_registry.validate_call(
                state=game_state,
                tool_name="set_player_action_suggestions",
                args=dict(kwargs),
                allowed_tools=["set_player_action_suggestions"],
            )
            suggestions: List[ActionSuggestion] = []
            error = guardrail.error
            if guardrail.ok:
                suggestions = self.runner._valid_scene_action_suggestions(
                    guardrail.args.get("suggestions", []),
                    game_state,
                    {"user_input": graph_state.get("user_input", "")},
                    response=str(graph_state.get("response") or ""),
                )
                if len(suggestions) != 3:
                    error = "Suggestions were not grounded in the confirmed scene."
            payload = {
                "ok": len(suggestions) == 3,
                "suggestions": [item.model_dump(mode="json") for item in suggestions],
                "error": error,
            }
            metadata = {
                **dict(graph_state.get("metadata", {})),
                "agent_name": self.role.value,
                "tool_name": "set_player_action_suggestions",
                "tool_ok": payload["ok"],
            }
            return Command(
                update={
                    "suggestions": payload["suggestions"],
                    "metadata": metadata,
                    "messages": [
                        ToolMessage(
                            content=json.dumps(payload, ensure_ascii=False),
                            tool_call_id=runtime.tool_call_id or "suggestions-set",
                            name="set_player_action_suggestions",
                        )
                    ],
                }
            )

        self.tools = {
            "set_player_action_suggestions": StructuredTool.from_function(
                func=set_suggestions,
                name="set_player_action_suggestions",
                description=str(contract.schema.get("description") or "Set player action suggestions."),
                args_schema=dict(contract.schema.get("parameters") or {}),
            )
        }
        self.tool_node = ToolNode(
            list(self.tools.values()),
            name="suggestion_tools",
            handle_tool_errors=False,
        )
        self.graph = self._build_graph()

    def _generate(self, state: SuggestionState) -> SuggestionState:
        game_state = GameState.model_validate(state["game_state"])
        suggestions, metadata = self.runner._generate_action_suggestion_projection(
            game_state,
            {
                "game_state": state["game_state"],
                "user_input": state.get("user_input", ""),
                "turn_profile": "ui_projection",
                "active_agent": self.role.value,
                "allowed_tools": list(self.tool_names),
            },
            state.get("response", ""),
        )
        update: SuggestionState = {
            "metadata": {**metadata, "agent_name": self.role.value},
        }
        if suggestions:
            update["messages"] = [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "suggestions-set",
                            "name": "set_player_action_suggestions",
                            "args": {
                                "suggestions": [item.model_dump(mode="json") for item in suggestions]
                            },
                        }
                    ],
                )
            ]
        else:
            update["suggestions"] = []
        return update

    @staticmethod
    def _route_after_generate(state: SuggestionState) -> str:
        messages = list(state.get("messages", []))
        if messages and getattr(messages[-1], "tool_calls", None):
            return "tools"
        return "done"

    def _build_graph(self):
        builder = StateGraph(SuggestionState)
        builder.add_node("generate", self._generate)
        builder.add_node("tools", self.tool_node)
        builder.add_edge(START, "generate")
        builder.add_conditional_edges(
            "generate",
            self._route_after_generate,
            {"tools": "tools", "done": END},
        )
        builder.add_edge("tools", END)
        return builder.compile()

    def project(
        self,
        game_state: GameState,
        response: str,
        user_input: str = "",
    ) -> tuple[List[ActionSuggestion], Dict[str, Any]]:
        if not self.runner._action_suggestions_required(
            game_state,
            {"turn_profile": "ui_projection"},
        ):
            return [], {
                "agent_name": self.role.value,
                "skipped": True,
                "skipped_reason": "not_player_decision_point",
            }
        result = self.graph.invoke(
            {
                "game_state": game_state.model_dump(mode="json"),
                "response": response,
                "user_input": user_input,
            }
        )
        suggestions = [ActionSuggestion.model_validate(item) for item in result.get("suggestions", [])]
        return suggestions, dict(result.get("metadata", {}))
