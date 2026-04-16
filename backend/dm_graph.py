"""LangGraph workflow for deterministic DM turn orchestration."""

import json
from typing import Any, Dict, List, Optional, TypedDict

from agent_tools import AgentToolExecution, AgentToolService, merge_patch
from game_logic import GameLogic
from models import ChatMessage, GameState, SessionEvent, ToolResult, TurnResult
from prompts import build_dm_instruction

try:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph
except ImportError:
    ChatOpenAI = None
    END = None
    HumanMessage = None
    START = None
    StateGraph = None
    SystemMessage = None
    ToolMessage = None


LANGGRAPH_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "lookup_rules",
        "description": "Search the local D&D rules knowledge base for relevant snippets and sources.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n_results": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "roll_dice",
        "description": "Roll dice locally for checks, attacks, damage, healing, or random outcomes.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "adjust_hp",
        "description": "Adjust HP for a party character or encounter combatant. Positive heals, negative deals damage.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_ref": {"type": "string"},
                "amount": {"type": "integer"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["target_ref", "amount"],
        },
    },
    {
        "name": "add_status",
        "description": "Add a condition or status effect to a character or combatant.",
        "parameters": {
            "type": "object",
            "properties": {"target_ref": {"type": "string"}, "status": {"type": "string"}},
            "required": ["target_ref", "status"],
        },
    },
    {
        "name": "remove_status",
        "description": "Remove a condition or status effect from a character or combatant.",
        "parameters": {
            "type": "object",
            "properties": {"target_ref": {"type": "string"}, "status": {"type": "string"}},
            "required": ["target_ref", "status"],
        },
    },
    {
        "name": "append_adventure_log",
        "description": "Append an important story event to the adventure log.",
        "parameters": {
            "type": "object",
            "properties": {"entry": {"type": "string"}},
            "required": ["entry"],
        },
    },
    {
        "name": "add_inventory_item",
        "description": "Add a named item, clue, or loot entry to a character inventory.",
        "parameters": {
            "type": "object",
            "properties": {
                "character_ref": {"type": "string"},
                "item_name": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
                "item_type": {"type": "string", "default": "misc"},
                "notes": {"type": "string", "default": ""},
                "source": {"type": "string", "default": ""},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["character_ref", "item_name"],
        },
    },
    {
        "name": "record_evidence",
        "description": "Persist a clue or document as structured evidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "holder_ref": {"type": "string", "default": ""},
                "source_ref": {"type": "string", "default": ""},
                "location": {"type": "string", "default": ""},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                "add_to_inventory": {"type": "boolean", "default": True},
            },
            "required": ["title", "summary"],
        },
    },
    {
        "name": "record_search_outcome",
        "description": "Record the structured result of searching a body, room, or suspect.",
        "parameters": {
            "type": "object",
            "properties": {
                "searcher_ref": {"type": "string"},
                "target_ref": {"type": "string"},
                "summary": {"type": "string"},
                "location": {"type": "string", "default": ""},
                "recovered_items": {"type": "array", "items": {"type": "string"}, "default": []},
                "recovered_evidence_ids": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["searcher_ref", "target_ref", "summary"],
        },
    },
    {
        "name": "record_major_experience",
        "description": "Record a major experience or milestone on a character sheet.",
        "parameters": {
            "type": "object",
            "properties": {"character_ref": {"type": "string"}, "entry": {"type": "string"}},
            "required": ["character_ref", "entry"],
        },
    },
    {
        "name": "record_chapter_progress",
        "description": "Persist the current chapter title and summary, optionally marking it complete.",
        "parameters": {
            "type": "object",
            "properties": {
                "chapter_title": {"type": "string"},
                "summary": {"type": "string"},
                "chapter_number": {"type": "integer", "default": 0},
                "completed": {"type": "boolean", "default": False},
            },
            "required": ["chapter_title", "summary"],
        },
    },
    {
        "name": "set_defeat_state",
        "description": "Set a tracked combatant or character defeat state.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_ref": {"type": "string"},
                "defeat_state": {"type": "string", "enum": ["active", "unconscious", "captured", "dead"]},
            },
            "required": ["target_ref", "defeat_state"],
        },
    },
    {
        "name": "set_scene",
        "description": "Set the current scene.",
        "parameters": {
            "type": "object",
            "properties": {"scene": {"type": "string"}},
            "required": ["scene"],
        },
    },
    {
        "name": "set_active_character",
        "description": "Switch the active character to a party member.",
        "parameters": {
            "type": "object",
            "properties": {"character_ref": {"type": "string"}},
            "required": ["character_ref"],
        },
    },
    {
        "name": "start_encounter",
        "description": "Start a combat encounter and add enemy combatants.",
        "parameters": {
            "type": "object",
            "properties": {
                "enemy_names": {"type": "array", "items": {"type": "string"}},
                "enemy_hp": {"type": "integer", "default": 10},
                "enemy_ac": {"type": "integer", "default": 10},
                "auto_roll_initiative": {"type": "boolean", "default": True},
            },
            "required": ["enemy_names"],
        },
    },
    {
        "name": "add_enemy",
        "description": "Add a new combatant to the current encounter.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "hp_max": {"type": "integer", "default": 10},
                "ac": {"type": "integer", "default": 10},
                "initiative_bonus": {"type": "integer", "default": 0},
                "side": {"type": "string", "default": "enemy"},
                "auto_roll_initiative": {"type": "boolean", "default": True},
            },
            "required": ["name"],
        },
    },
    {
        "name": "save_monster_template",
        "description": "Persist a reusable monster template designed during play.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "creature_type": {"type": "string", "default": "Beast"},
                "challenge_rating": {"type": "string", "default": "1"},
                "hp_max": {"type": "integer", "default": 10},
                "ac": {"type": "integer", "default": 10},
                "initiative_bonus": {"type": "integer", "default": 0},
                "size": {"type": "string", "default": "Medium"},
                "alignment": {"type": "string", "default": "Unaligned"},
                "speed": {"type": "integer", "default": 30},
                "notes": {"type": "string", "default": ""},
                "traits": {"type": "array", "items": {"type": "string"}, "default": []},
                "actions": {"type": "array", "items": {"type": "string"}, "default": []},
                "reactions": {"type": "array", "items": {"type": "string"}, "default": []},
                "bonus_actions": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["name"],
        },
    },
    {
        "name": "spawn_monster_from_template",
        "description": "Spawn one or more combatants from a saved monster template.",
        "parameters": {
            "type": "object",
            "properties": {
                "monster_ref": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
                "custom_name": {"type": "string", "default": ""},
                "hp_override": {"type": "integer", "default": 0},
                "side": {"type": "string", "default": "enemy"},
                "auto_roll_initiative": {"type": "boolean", "default": True},
            },
            "required": ["monster_ref"],
        },
    },
    {
        "name": "attack_target",
        "description": "Resolve an attack roll against target AC and apply damage on hit.",
        "parameters": {
            "type": "object",
            "properties": {
                "attacker_ref": {"type": "string"},
                "target_ref": {"type": "string"},
                "attack_bonus": {"type": "integer"},
                "damage_expression": {"type": "string"},
                "damage_type": {"type": "string", "default": ""},
                "resolution_mode": {"type": "string", "default": "normal"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["attacker_ref", "target_ref", "attack_bonus", "damage_expression"],
        },
    },
    {
        "name": "roll_skill_check",
        "description": "Roll a skill check against an optional DC.",
        "parameters": {
            "type": "object",
            "properties": {
                "actor_ref": {"type": "string"},
                "skill_name": {"type": "string"},
                "modifier": {"type": "integer"},
                "dc": {"type": "integer", "default": 0},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["actor_ref", "skill_name"],
        },
    },
    {
        "name": "roll_saving_throw",
        "description": "Roll a saving throw against a DC.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_ref": {"type": "string"},
                "save_name": {"type": "string"},
                "dc": {"type": "integer"},
                "modifier": {"type": "integer"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["target_ref", "save_name", "dc"],
        },
    },
    {
        "name": "cast_spell",
        "description": "Validate spell access and spend a spell slot if required.",
        "parameters": {
            "type": "object",
            "properties": {
                "caster_ref": {"type": "string"},
                "spell_name": {"type": "string"},
                "slot_level": {"type": "integer", "default": 0},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["caster_ref", "spell_name"],
        },
    },
    {
        "name": "set_initiative",
        "description": "Set a combatant initiative score directly.",
        "parameters": {
            "type": "object",
            "properties": {"combatant_ref": {"type": "string"}, "initiative": {"type": "integer"}},
            "required": ["combatant_ref", "initiative"],
        },
    },
    {
        "name": "roll_initiative",
        "description": "Roll initiative for a combatant.",
        "parameters": {
            "type": "object",
            "properties": {"combatant_ref": {"type": "string"}},
            "required": ["combatant_ref"],
        },
    },
    {
        "name": "advance_turn",
        "description": "Advance the encounter to the next combatant.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "end_encounter",
        "description": "End the current encounter and leave combat scene.",
        "parameters": {"type": "object", "properties": {}},
    },
]


class LangGraphUnavailableError(RuntimeError):
    pass


class DMGraphState(TypedDict, total=False):
    game_state: Dict[str, Any]
    user_input: str
    phase: str
    scene: str
    messages: List[Any]
    state_summary: str
    recent_history: str
    instruction: str
    allowed_tools: List[str]
    tool_call_rounds: int
    final_response: str
    tool_results: List[Dict[str, Any]]
    state_delta: Dict[str, Any]
    timeline_append: List[Dict[str, Any]]
    history_append: List[Dict[str, Any]]


class DMGraphRunner:
    """
    LangGraph DM runner with model/tool execution over the local authoritative GameState.
    """

    def __init__(
        self,
        rag_engine,
        tool_service: Optional[AgentToolService] = None,
        model_name: str = "",
        api_key: str = "",
        base_url: str = "",
        enable_model: bool = False,
        max_tool_rounds: int = 6,
    ):
        self.rag_engine = rag_engine
        self.tool_service = tool_service
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.enable_model = enable_model
        self.max_tool_rounds = max_tool_rounds
        self._graph = None
        self._model = None

    @property
    def is_available(self) -> bool:
        return StateGraph is not None

    def _require_langgraph(self) -> None:
        if not self.is_available:
            raise LangGraphUnavailableError(
                "LangGraph is not installed. Install backend requirements before enabling the LangGraph runner."
            )

    def _create_model(self):
        if self._model is not None:
            return self._model
        if ChatOpenAI is None:
            raise LangGraphUnavailableError("langchain-openai is not installed.")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is missing.")

        model_kwargs: Dict[str, Any] = {
            "model": self.model_name or "gpt-5.1",
            "api_key": self.api_key,
        }
        if self.base_url:
            model_kwargs["base_url"] = self.base_url
        self._model = ChatOpenAI(**model_kwargs)
        return self._model

    def _create_tool_bound_model(self, allowed_tools: List[str]):
        model = self._create_model()
        if not allowed_tools:
            return model
        tool_schemas = [tool for tool in LANGGRAPH_TOOL_SCHEMAS if tool["name"] in set(allowed_tools)]
        if not tool_schemas:
            return model
        return model.bind_tools(tool_schemas)

    @staticmethod
    def _allowed_tool_names(state: GameState) -> List[str]:
        always = [
            "lookup_rules",
            "roll_dice",
            "adjust_hp",
            "add_status",
            "remove_status",
            "append_adventure_log",
            "add_inventory_item",
            "record_evidence",
            "record_search_outcome",
            "record_major_experience",
            "record_chapter_progress",
            "set_scene",
            "set_active_character",
            "roll_skill_check",
            "roll_saving_throw",
            "cast_spell",
            "save_monster_template",
        ]
        encounter_tools = [
            "set_defeat_state",
            "start_encounter",
            "add_enemy",
            "spawn_monster_from_template",
            "attack_target",
            "set_initiative",
            "roll_initiative",
            "advance_turn",
            "end_encounter",
        ]
        if state.scene == "combat" or (state.encounter and state.encounter.active):
            return [*always, *encounter_tools]
        return [*always, "start_encounter"]

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
            "tool_call_rounds": 0,
            "tool_results": [],
            "state_delta": {},
            "timeline_append": [player_event.model_dump(mode="json")],
        }

    def _route_phase(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        return {
            "phase": state.campaign.phase,
            "scene": state.scene,
            "allowed_tools": self._allowed_tool_names(state),
        }

    def _prepare_context(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        logic = GameLogic(state)
        state_summary = logic.get_state_summary()
        recent_history = logic.get_recent_history()
        instruction = build_dm_instruction(
            state_summary=state_summary,
            recent_history=recent_history,
            rag_enabled=self.rag_engine.is_ready(),
        )
        return {
            "state_summary": state_summary,
            "recent_history": recent_history,
            "instruction": instruction,
            "messages": [
                SystemMessage(content=instruction),
                HumanMessage(content=graph_state.get("user_input", "")),
            ],
        }

    def _draft_response_placeholder(self, graph_state: DMGraphState) -> DMGraphState:
        return {
            "final_response": (
                "LangGraph turn workflow is prepared, but the model/tool execution node is not enabled yet."
            )
        }

    @staticmethod
    def _extract_message_content(message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
                elif item:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content).strip() if content else ""

    def _call_model(self, graph_state: DMGraphState) -> DMGraphState:
        messages = list(graph_state.get("messages", []))
        if not messages:
            messages = [
                SystemMessage(content=graph_state.get("instruction", "")),
                HumanMessage(content=graph_state.get("user_input", "")),
            ]
        model = self._create_tool_bound_model(graph_state.get("allowed_tools", []))
        try:
            response = model.invoke(messages)
        except Exception as exc:
            return {
                "messages": messages,
                "final_response": (
                    "The model provider rejected this turn before completion "
                    f"({exc.__class__.__name__}). Check provider quota and API settings."
                ),
            }
        final_response = self._extract_message_content(response)
        result: DMGraphState = {"messages": [*messages, response]}
        if final_response:
            result["final_response"] = final_response
        return result

    @staticmethod
    def _last_message_tool_calls(messages: List[Any]) -> List[Dict[str, Any]]:
        if not messages:
            return []
        return list(getattr(messages[-1], "tool_calls", []) or [])

    def _should_continue_after_model(self, graph_state: DMGraphState) -> str:
        tool_calls = self._last_message_tool_calls(list(graph_state.get("messages", [])))
        if tool_calls and graph_state.get("tool_call_rounds", 0) < self.max_tool_rounds:
            return "execute_tools"
        return "finalize_turn"

    def _tool_error_execution(self, tool_name: str, message: str) -> AgentToolExecution:
        return AgentToolExecution(
            ok=False,
            error=message,
            error_response={"ok": False, "tool_name": tool_name, "error": message},
        )

    def _execute_single_tool(
        self,
        state: GameState,
        tool_name: str,
        args: Dict[str, Any],
        allowed_tools: List[str],
    ) -> AgentToolExecution:
        if not self.tool_service:
            return self._tool_error_execution(tool_name, "Agent tool service is not configured.")
        if tool_name not in allowed_tools:
            return self._tool_error_execution(tool_name, f"Tool is not allowed in the current phase: {tool_name}")
        tool = getattr(self.tool_service, tool_name, None)
        if not tool:
            return self._tool_error_execution(tool_name, f"Unknown tool: {tool_name}")
        try:
            return tool(state, **(args or {}))
        except TypeError as exc:
            return self._tool_error_execution(tool_name, f"Invalid tool arguments for {tool_name}: {exc}")
        except Exception as exc:
            return self._tool_error_execution(tool_name, f"Tool failed: {exc}")

    @staticmethod
    def _tool_message_content(execution: AgentToolExecution) -> str:
        return json.dumps(execution.response(), ensure_ascii=False, default=str)

    def _execute_tools(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        messages = list(graph_state.get("messages", []))
        allowed_tools = list(graph_state.get("allowed_tools", []))
        tool_results = list(graph_state.get("tool_results", []))
        timeline_append = list(graph_state.get("timeline_append", []))
        state_delta = dict(graph_state.get("state_delta", {}))

        for tool_call in self._last_message_tool_calls(messages):
            tool_name = tool_call.get("name", "")
            args = dict(tool_call.get("args") or {})
            execution = self._execute_single_tool(state, tool_name, args, allowed_tools)

            if execution.ok:
                if execution.timeline_event:
                    state.timeline.append(execution.timeline_event)
                    timeline_append.append(execution.timeline_event.model_dump(mode="json"))
                if execution.tool_result:
                    tool_results.append(execution.tool_result.model_dump(mode="json"))
                if execution.state_patch:
                    state_delta = merge_patch(state_delta, execution.state_patch)

            messages.append(
                ToolMessage(
                    content=self._tool_message_content(execution),
                    tool_call_id=tool_call.get("id", tool_name or "tool_call"),
                )
            )

        return {
            "game_state": state.model_dump(mode="json"),
            "messages": messages,
            "tool_results": tool_results,
            "timeline_append": timeline_append,
            "state_delta": state_delta,
            "tool_call_rounds": graph_state.get("tool_call_rounds", 0) + 1,
            "allowed_tools": self._allowed_tool_names(state),
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
        builder.add_node("route_phase", self._route_phase)
        builder.add_node("prepare_context", self._prepare_context)
        model_node = self._call_model if self.enable_model else self._draft_response_placeholder
        builder.add_node("draft_response", model_node)
        builder.add_node("execute_tools", self._execute_tools)
        builder.add_node("finalize_turn", self._finalize_turn)
        builder.add_edge(START, "prepare_turn")
        builder.add_edge("prepare_turn", "route_phase")
        builder.add_edge("route_phase", "prepare_context")
        builder.add_edge("prepare_context", "draft_response")
        builder.add_conditional_edges(
            "draft_response",
            self._should_continue_after_model,
            {
                "execute_tools": "execute_tools",
                "finalize_turn": "finalize_turn",
            },
        )
        builder.add_edge("execute_tools", "draft_response")
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
