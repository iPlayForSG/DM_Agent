"""Google ADK wrapper that lets the DM operate on local game state through tools."""

import copy
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from agent_tools import AgentToolExecution, AgentToolService
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import (
    Character,
    ChatMessage,
    GameState,
    SessionEvent,
    ToolResult,
    TurnResult,
)
from prompts import build_dm_instruction
from rag import RAGEngine
from rules_catalog import RuleCatalog
from storage import MonsterStorage

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)

try:
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import ToolContext
    from google.genai import types
except ImportError:
    LlmAgent = None
    LiteLlm = None
    Runner = None
    InMemorySessionService = None
    ToolContext = Any
    types = None


def merge_patch(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_patch(merged[key], value)
        else:
            merged[key] = value
    return merged


class DMAgent:
    """
    Dungeon Master agent powered by Google ADK.
    Runtime state still lives in local JSON; ADK handles model orchestration and tool calls.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL", "")
        self.model_name = os.getenv("LLM_MODEL", "gpt-5.1")
        self.chat_backend = os.getenv("CHAT_BACKEND", os.getenv("AGENT_BACKEND", "google-adk")).lower()
        self.app_name = os.getenv("ADK_APP_NAME", "dnd_dm_agent")
        self.user_id = os.getenv("ADK_USER_ID", "local_dm")
        self.monster_storage = MonsterStorage()
        self.rules_catalog = RuleCatalog()
        self.rag_engine = RAGEngine()
        self.tool_service = AgentToolService(
            rag_engine=self.rag_engine,
            monster_storage=self.monster_storage,
            rules_catalog=self.rules_catalog,
        )
        self.dm_graph_runner = DMGraphRunner(
            rag_engine=self.rag_engine,
            model_name=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            enable_model=True,
        )

        if self.api_key:
            os.environ.setdefault("OPENAI_API_KEY", self.api_key)
        if self.base_url:
            os.environ.setdefault("OPENAI_API_BASE", self.base_url)

    def _require_adk(self) -> None:
        if not all([LlmAgent, LiteLlm, Runner, InMemorySessionService, types]):
            raise RuntimeError(
                "Google ADK is not installed. Install backend requirements before starting the API server."
            )
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is missing.")

    @property
    def backend_name(self) -> str:
        if self.chat_backend in {"langgraph", "langchain", "graph"}:
            return "langgraph" if self.dm_graph_runner.is_available else "langgraph-unavailable"
        return "google-adk"

    def _resolve_model_name(self) -> str:
        if "/" in self.model_name:
            return self.model_name
        return f"openai/{self.model_name}"

    def _create_model(self):
        model_kwargs: Dict[str, Any] = {"model": self._resolve_model_name()}
        if self.api_key:
            model_kwargs["api_key"] = self.api_key
        if self.base_url:
            model_kwargs["api_base"] = self.base_url
        return LiteLlm(**model_kwargs)

    def create_new_game(
        self, characters: List[Character], game_id: str = "", title: str = ""
    ) -> GameState:
        state = GameState(game_id=game_id, title=title or game_id)

        if not characters:
            fallback = Character(name="Adventurer")
            state.characters[fallback.character_id] = fallback
            state.active_character_id = fallback.character_id
        else:
            for character in characters:
                state.characters[character.character_id] = character
            state.active_character_id = characters[0].character_id

        return state

    def _load_runtime_state(self, tool_context: ToolContext) -> GameState:
        # Tool handlers always work against the authoritative serialized game state in the ADK session.
        payload = copy.deepcopy(tool_context.state.get("game_state", {}))
        return GameState.model_validate(payload)

    def _build_event(
        self,
        event_type: str,
        summary: str,
        content: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> SessionEvent:
        return SessionEvent(type=event_type, summary=summary, content=content, payload=payload or {})

    def _store_runtime_state(
        self,
        tool_context: ToolContext,
        state: GameState,
        tool_result: Optional[ToolResult] = None,
        state_patch: Optional[Dict[str, Any]] = None,
        timeline_event: Optional[SessionEvent] = None,
    ) -> None:
        if timeline_event:
            state.timeline.append(timeline_event)
            timeline_append = list(tool_context.state.get("timeline_append", []))
            timeline_append.append(timeline_event.model_dump(mode="json"))
            tool_context.state["timeline_append"] = timeline_append

        # Persist the full post-tool state so the next tool call and the final turn result see the same truth.
        tool_context.state["game_state"] = state.model_dump(mode="json")

        if tool_result:
            results = list(tool_context.state.get("latest_tool_results", []))
            results.append(tool_result.model_dump(mode="json"))
            tool_context.state["latest_tool_results"] = results

        if state_patch:
            current_delta = dict(tool_context.state.get("state_delta", {}))
            tool_context.state["state_delta"] = merge_patch(current_delta, state_patch)

    def _store_tool_execution(
        self,
        tool_context: ToolContext,
        state: GameState,
        execution: AgentToolExecution,
    ) -> None:
        self._store_runtime_state(
            tool_context,
            state,
            tool_result=execution.tool_result,
            state_patch=execution.state_patch,
            timeline_event=execution.timeline_event,
        )

    def _run_agent_tool(
        self,
        tool_context: ToolContext,
        tool_call,
        *args,
        include_ok: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        state = self._load_runtime_state(tool_context)
        execution = tool_call(state, *args, **kwargs)
        if execution.ok:
            self._store_tool_execution(tool_context, state, execution)
        return execution.response(include_ok=include_ok)

    def _build_tools(self):
        # Phase 1 bridge: ADK still owns model orchestration, but tool behavior now lives in a runtime-neutral service.
        def lookup_rules(
            query: str,
            n_results: int = 3,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Search the local D&D rules knowledge base for relevant snippets and sources."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.lookup_rules,
                query=query,
                n_results=n_results,
            )

        def roll_dice(expression: str, reason: str = "", tool_context: ToolContext = None) -> Dict[str, Any]:
            """Roll dice locally. Use this for checks, saves, attacks, damage, healing, and random outcomes."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.roll_dice,
                expression=expression,
                reason=reason,
                include_ok=False,
            )

        def adjust_hp(
            target_ref: str,
            amount: int,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Adjust HP for a party character or encounter combatant. Positive heals, negative deals damage."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.adjust_hp,
                target_ref=target_ref,
                amount=amount,
                reason=reason,
            )

        def add_status(target_ref: str, status: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Add a condition or status effect to a tracked party character or encounter combatant."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.add_status,
                target_ref=target_ref,
                status=status,
            )

        def remove_status(target_ref: str, status: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Remove a condition or status effect from a tracked party character or encounter combatant."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.remove_status,
                target_ref=target_ref,
                status=status,
            )

        def append_adventure_log(entry: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Append an important story event to the adventure log."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.append_adventure_log,
                entry=entry,
            )

        def add_inventory_item(
            character_ref: str,
            item_name: str,
            quantity: int = 1,
            item_type: str = "misc",
            notes: str = "",
            source: str = "",
            tags: Optional[List[str]] = None,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Add a named item, clue, or piece of loot to a character inventory."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.add_inventory_item,
                character_ref=character_ref,
                item_name=item_name,
                quantity=quantity,
                item_type=item_type,
                notes=notes,
                source=source,
                tags=tags,
            )

        def record_evidence(
            title: str,
            summary: str,
            holder_ref: str = "",
            source_ref: str = "",
            location: str = "",
            tags: Optional[List[str]] = None,
            add_to_inventory: bool = True,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Persist a clue or document as structured evidence and optionally place it in inventory."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.record_evidence,
                title=title,
                summary=summary,
                holder_ref=holder_ref,
                source_ref=source_ref,
                location=location,
                tags=tags,
                add_to_inventory=add_to_inventory,
            )

        def record_search_outcome(
            searcher_ref: str,
            target_ref: str,
            summary: str,
            location: str = "",
            recovered_items: Optional[List[str]] = None,
            recovered_evidence_ids: Optional[List[str]] = None,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Record the structured result of searching a body, room, or suspect."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.record_search_outcome,
                searcher_ref=searcher_ref,
                target_ref=target_ref,
                summary=summary,
                location=location,
                recovered_items=recovered_items,
                recovered_evidence_ids=recovered_evidence_ids,
            )

        def record_major_experience(
            character_ref: str,
            entry: str,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Record a major experience or milestone on a character sheet."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.record_major_experience,
                character_ref=character_ref,
                entry=entry,
            )

        def record_chapter_progress(
            chapter_title: str,
            summary: str,
            chapter_number: int = 0,
            completed: bool = False,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Persist the current chapter title and summary, optionally marking it complete."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.record_chapter_progress,
                chapter_title=chapter_title,
                summary=summary,
                chapter_number=chapter_number,
                completed=completed,
            )

        def set_defeat_state(
            target_ref: str,
            defeat_state: str,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Set a tracked combatant or character defeat state such as active, unconscious, captured, or dead."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.set_defeat_state,
                target_ref=target_ref,
                defeat_state=defeat_state,
            )

        def set_scene(scene: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Set the current scene. Preferred values: setup, exploration, combat, downtime."""
            return self._run_agent_tool(tool_context, self.tool_service.set_scene, scene=scene)

        def set_active_character(character_ref: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Switch the active character to the specified party member."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.set_active_character,
                character_ref=character_ref,
            )

        def start_encounter(
            enemy_names: List[str],
            enemy_hp: int = 10,
            enemy_ac: int = 10,
            auto_roll_initiative: bool = True,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Start a combat encounter and add enemy combatants."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.start_encounter,
                enemy_names=enemy_names,
                enemy_hp=enemy_hp,
                enemy_ac=enemy_ac,
                auto_roll_initiative=auto_roll_initiative,
            )

        def add_enemy(
            name: str,
            hp_max: int = 10,
            ac: int = 10,
            initiative_bonus: int = 0,
            side: str = "enemy",
            auto_roll_initiative: bool = True,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Add a new enemy combatant to the current encounter."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.add_enemy,
                name=name,
                hp_max=hp_max,
                ac=ac,
                initiative_bonus=initiative_bonus,
                side=side,
                auto_roll_initiative=auto_roll_initiative,
            )

        def save_monster_template(
            name: str,
            creature_type: str = "Beast",
            challenge_rating: str = "1",
            hp_max: int = 10,
            ac: int = 10,
            initiative_bonus: int = 0,
            size: str = "Medium",
            alignment: str = "Unaligned",
            speed: int = 30,
            notes: str = "",
            traits: Optional[List[str]] = None,
            actions: Optional[List[str]] = None,
            reactions: Optional[List[str]] = None,
            bonus_actions: Optional[List[str]] = None,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Persist a reusable monster template designed during play."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.save_monster_template,
                name=name,
                creature_type=creature_type,
                challenge_rating=challenge_rating,
                hp_max=hp_max,
                ac=ac,
                initiative_bonus=initiative_bonus,
                size=size,
                alignment=alignment,
                speed=speed,
                notes=notes,
                traits=traits,
                actions=actions,
                reactions=reactions,
                bonus_actions=bonus_actions,
            )

        def spawn_monster_from_template(
            monster_ref: str,
            quantity: int = 1,
            custom_name: str = "",
            hp_override: int = 0,
            side: str = "enemy",
            auto_roll_initiative: bool = True,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Spawn one or more combatants from a saved monster template."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.spawn_monster_from_template,
                monster_ref=monster_ref,
                quantity=quantity,
                custom_name=custom_name,
                hp_override=hp_override,
                side=side,
                auto_roll_initiative=auto_roll_initiative,
            )

        def attack_target(
            attacker_ref: str,
            target_ref: str,
            attack_bonus: int,
            damage_expression: str,
            damage_type: str = "",
            resolution_mode: str = "normal",
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Resolve an attack roll against target AC and apply damage on hit."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.attack_target,
                attacker_ref=attacker_ref,
                target_ref=target_ref,
                attack_bonus=attack_bonus,
                damage_expression=damage_expression,
                damage_type=damage_type,
                resolution_mode=resolution_mode,
                reason=reason,
            )

        def roll_skill_check(
            actor_ref: str,
            skill_name: str,
            modifier: Optional[int] = None,
            dc: int = 0,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Roll a skill check against an optional DC."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.roll_skill_check,
                actor_ref=actor_ref,
                skill_name=skill_name,
                modifier=modifier,
                dc=dc,
                reason=reason,
            )

        def roll_saving_throw(
            target_ref: str,
            save_name: str,
            dc: int,
            modifier: Optional[int] = None,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Roll a saving throw against a DC."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.roll_saving_throw,
                target_ref=target_ref,
                save_name=save_name,
                dc=dc,
                modifier=modifier,
                reason=reason,
            )

        def cast_spell(
            caster_ref: str,
            spell_name: str,
            slot_level: int = 0,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Validate prepared/known spell access and spend a spell slot if required."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.cast_spell,
                caster_ref=caster_ref,
                spell_name=spell_name,
                slot_level=slot_level,
                reason=reason,
            )

        def set_initiative(combatant_ref: str, initiative: int, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Set a combatant initiative score directly."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.set_initiative,
                combatant_ref=combatant_ref,
                initiative=initiative,
            )

        def roll_initiative(combatant_ref: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Roll initiative for a combatant using 1d20 plus initiative bonus."""
            return self._run_agent_tool(
                tool_context,
                self.tool_service.roll_initiative,
                combatant_ref=combatant_ref,
            )

        def advance_turn(tool_context: ToolContext = None) -> Dict[str, Any]:
            """Advance the encounter to the next combatant."""
            return self._run_agent_tool(tool_context, self.tool_service.advance_turn)

        def end_encounter(tool_context: ToolContext = None) -> Dict[str, Any]:
            """End the current encounter and leave combat scene."""
            return self._run_agent_tool(tool_context, self.tool_service.end_encounter)

        return [
            lookup_rules,
            roll_dice,
            adjust_hp,
            add_status,
            remove_status,
            append_adventure_log,
            add_inventory_item,
            record_evidence,
            record_search_outcome,
            record_major_experience,
            record_chapter_progress,
            set_defeat_state,
            set_scene,
            set_active_character,
            start_encounter,
            add_enemy,
            save_monster_template,
            spawn_monster_from_template,
            attack_target,
            roll_skill_check,
            roll_saving_throw,
            cast_spell,
            set_initiative,
            roll_initiative,
            advance_turn,
            end_encounter,
        ]

    def _extract_text(self, event: Any) -> str:
        content = getattr(event, "content", None)
        if not content:
            return ""

        parts = getattr(content, "parts", None) or []
        texts: List[str] = []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)
        return "\n".join(texts).strip()

    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        if self.chat_backend in {"langgraph", "langchain", "graph"}:
            return self.dm_graph_runner.run_turn(state, user_input)

        self._require_adk()

        # Copy the persisted state before the turn so tool execution can mutate it freely without side effects.
        working_state = GameState.model_validate(state.model_dump(mode="json"))
        player_event = self._build_event(
            event_type="player_action",
            summary="Player action",
            content=user_input,
            payload={"message": user_input},
        )
        working_state.timeline.append(player_event)

        logic = GameLogic(working_state)
        instruction = build_dm_instruction(
            state_summary=logic.get_state_summary(),
            recent_history=logic.get_recent_history(),
            rag_enabled=self.rag_engine.is_ready(),
        )

        session_service = InMemorySessionService()
        session_id = working_state.game_id or "local-session"
        initial_state = {
            "game_state": working_state.model_dump(mode="json"),
            "latest_tool_results": [],
            "state_delta": {},
            "timeline_append": [player_event.model_dump(mode="json")],
        }
        await session_service.create_session(
            app_name=self.app_name,
            user_id=self.user_id,
            session_id=session_id,
            state=initial_state,
        )

        agent = LlmAgent(
            name="dnd_dm_agent",
            model=self._create_model(),
            instruction=instruction,
            tools=self._build_tools(),
        )
        runner = Runner(agent=agent, app_name=self.app_name, session_service=session_service)

        prompt = types.Content(role="user", parts=[types.Part(text=user_input)])
        final_response = ""

        async for event in runner.run_async(
            user_id=self.user_id,
            session_id=session_id,
            new_message=prompt,
        ):
            if getattr(event, "is_final_response", None) and event.is_final_response():
                text = self._extract_text(event)
                if text:
                    final_response = text

        session = await session_service.get_session(
            app_name=self.app_name,
            user_id=self.user_id,
            session_id=session_id,
        )

        updated_state = working_state
        tool_results: List[ToolResult] = []
        state_delta: Dict[str, Any] = {}
        timeline_append: List[SessionEvent] = [player_event]

        if session:
            updated_state = GameState.model_validate(session.state.get("game_state", working_state.model_dump(mode="json")))
            tool_results = [
                ToolResult.model_validate(item) for item in session.state.get("latest_tool_results", [])
            ]
            state_delta = dict(session.state.get("state_delta", {}))
            timeline_append = [
                SessionEvent.model_validate(item) for item in session.state.get("timeline_append", [])
            ]

        if not final_response:
            final_response = "我暂时没能完成这一轮裁定，请稍后再试。"

        updated_state.turn_number += 1
        updated_state.latest_tool_results = tool_results

        assistant_event = self._build_event(
            event_type="assistant_response",
            summary="DM response",
            content=final_response,
            payload={"message": final_response},
        )
        updated_state.timeline.append(assistant_event)
        timeline_append.append(assistant_event)

        history_append: List[ChatMessage] = [ChatMessage(role="user", content=user_input)]
        history_append.extend(
            ChatMessage(role="system", content=result.summary, kind="tool_result") for result in tool_results
        )
        history_append.append(ChatMessage(role="assistant", content=final_response))
        updated_state.chat_history.extend(history_append)

        return TurnResult(
            response=final_response,
            history=updated_state.chat_history,
            history_append=history_append,
            timeline=updated_state.timeline,
            timeline_append=timeline_append,
            tool_results=tool_results,
            state_delta=state_delta,
            game_state=updated_state,
        )
