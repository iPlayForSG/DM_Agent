"""LangGraph workflow skeleton for deterministic DM turn orchestration."""

from typing import Any, Dict, List, Optional, TypedDict

from game_logic import GameLogic
from models import ChatMessage, GameState, SessionEvent, ToolResult, TurnResult
from prompts import build_dm_instruction

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END = None
    START = None
    StateGraph = None


class LangGraphUnavailableError(RuntimeError):
    pass


class DMGraphState(TypedDict, total=False):
    game_state: Dict[str, Any]
    user_input: str
    phase: str
    scene: str
    state_summary: str
    recent_history: str
    instruction: str
    final_response: str
    tool_results: List[Dict[str, Any]]
    state_delta: Dict[str, Any]
    timeline_append: List[Dict[str, Any]]
    history_append: List[Dict[str, Any]]


class DMGraphRunner:
    """
    First LangGraph slice.
    It models turn preparation/context/finalization now; model and tool nodes are added in the next phase.
    """

    def __init__(self, rag_engine):
        self.rag_engine = rag_engine
        self._graph = None

    @property
    def is_available(self) -> bool:
        return StateGraph is not None

    def _require_langgraph(self) -> None:
        if not self.is_available:
            raise LangGraphUnavailableError(
                "LangGraph is not installed. Install backend requirements before enabling the LangGraph runner."
            )

    @staticmethod
    def _build_event(
        event_type: str,
        summary: str,
        content: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> SessionEvent:
        return SessionEvent(type=event_type, summary=summary, content=content, payload=payload or {})

    def _prepare_turn(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = graph_state.get("user_input", "")
        player_event = self._build_event(
            event_type="player_action",
            summary="Player action",
            content=user_input,
            payload={"message": user_input},
        )
        state.timeline.append(player_event)
        return {
            "game_state": state.model_dump(mode="json"),
            "phase": state.campaign.phase,
            "scene": state.scene,
            "tool_results": [],
            "state_delta": {},
            "timeline_append": [player_event.model_dump(mode="json")],
        }

    def _prepare_context(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        logic = GameLogic(state)
        state_summary = logic.get_state_summary()
        recent_history = logic.get_recent_history()
        return {
            "state_summary": state_summary,
            "recent_history": recent_history,
            "instruction": build_dm_instruction(
                state_summary=state_summary,
                recent_history=recent_history,
                rag_enabled=self.rag_engine.is_ready(),
            ),
        }

    def _draft_response_placeholder(self, graph_state: DMGraphState) -> DMGraphState:
        return {
            "final_response": (
                "LangGraph turn workflow is prepared, but the model/tool execution node is not enabled yet."
            )
        }

    def _finalize_turn(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = graph_state.get("user_input", "")
        final_response = graph_state.get("final_response") or "I could not complete this turn."
        tool_results = [
            item if isinstance(item, ToolResult) else ToolResult.model_validate(item)
            for item in graph_state.get("tool_results", [])
        ]

        state.turn_number += 1
        state.latest_tool_results = tool_results

        assistant_event = self._build_event(
            event_type="assistant_response",
            summary="DM response",
            content=final_response,
            payload={"message": final_response},
        )
        state.timeline.append(assistant_event)

        history_append: List[ChatMessage] = [ChatMessage(role="user", content=user_input)]
        history_append.extend(
            ChatMessage(role="system", content=result.summary, kind="tool_result") for result in tool_results
        )
        history_append.append(ChatMessage(role="assistant", content=final_response))
        state.chat_history.extend(history_append)

        timeline_append = list(graph_state.get("timeline_append", []))
        timeline_append.append(assistant_event.model_dump(mode="json"))
        return {
            "game_state": state.model_dump(mode="json"),
            "history_append": [item.model_dump(mode="json") for item in history_append],
            "timeline_append": timeline_append,
            "final_response": final_response,
        }

    def _build_graph(self):
        self._require_langgraph()
        builder = StateGraph(DMGraphState)
        builder.add_node("prepare_turn", self._prepare_turn)
        builder.add_node("prepare_context", self._prepare_context)
        builder.add_node("draft_response", self._draft_response_placeholder)
        builder.add_node("finalize_turn", self._finalize_turn)
        builder.add_edge(START, "prepare_turn")
        builder.add_edge("prepare_turn", "prepare_context")
        builder.add_edge("prepare_context", "draft_response")
        builder.add_edge("draft_response", "finalize_turn")
        builder.add_edge("finalize_turn", END)
        return builder.compile()

    def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        if self._graph is None:
            self._graph = self._build_graph()

        result = self._graph.invoke(
            {
                "game_state": state.model_dump(mode="json"),
                "user_input": user_input,
            }
        )
        updated_state = GameState.model_validate(result["game_state"])
        history_append = [
            item if isinstance(item, ChatMessage) else ChatMessage.model_validate(item)
            for item in result.get("history_append", [])
        ]
        timeline_append = [
            item if isinstance(item, SessionEvent) else SessionEvent.model_validate(item)
            for item in result.get("timeline_append", [])
        ]
        tool_results = [
            item if isinstance(item, ToolResult) else ToolResult.model_validate(item)
            for item in result.get("tool_results", [])
        ]
        return TurnResult(
            response=result.get("final_response", ""),
            history=updated_state.chat_history,
            history_append=history_append,
            timeline=updated_state.timeline,
            timeline_append=timeline_append,
            tool_results=tool_results,
            state_delta=dict(result.get("state_delta", {})),
            game_state=updated_state,
        )
