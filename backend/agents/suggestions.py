"""Post-commit action suggestion agent."""

from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from models import ActionSuggestion, GameState

from .specs import AGENT_SPECS, AgentRole


class SuggestionState(TypedDict, total=False):
    game_state: Dict[str, Any]
    response: str
    user_input: str
    suggestions: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class SuggestionAgent:
    def __init__(self, runner: Any):
        self.runner = runner
        self.role = AgentRole.SUGGESTIONS
        self.spec = AGENT_SPECS[self.role]
        self.tool_names = frozenset(self.spec.tool_names)
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
        return {
            "suggestions": [item.model_dump(mode="json") for item in suggestions],
            "metadata": {**metadata, "agent_name": self.role.value},
        }

    def _build_graph(self):
        builder = StateGraph(SuggestionState)
        builder.add_node("generate", self._generate)
        builder.add_edge(START, "generate")
        builder.add_edge("generate", END)
        return builder.compile()

    def project(
        self,
        game_state: GameState,
        response: str,
        user_input: str = "",
    ) -> tuple[List[ActionSuggestion], Dict[str, Any]]:
        result = self.graph.invoke(
            {
                "game_state": game_state.model_dump(mode="json"),
                "response": response,
                "user_input": user_input,
            }
        )
        suggestions = [ActionSuggestion.model_validate(item) for item in result.get("suggestions", [])]
        return suggestions, dict(result.get("metadata", {}))
