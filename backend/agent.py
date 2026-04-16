"""Google ADK wrapper that lets the DM operate on local game state through tools."""

import copy
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from agent_tools import AgentToolExecution, AgentToolService
from dm_graph import DMGraphRunner
from game_logic import DiceRoller, GameLogic
from models import (
    Character,
    ChatMessage,
    GameState,
    MonsterTemplate,
    MonsterTextEntry,
    SessionEvent,
    ToolResult,
    TurnResult,
)
from prompts import build_dm_instruction
from rag import RAGEngine
from rules_catalog import ABILITY_ALIAS, SKILL_TO_ABILITY, RuleCatalog
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

        # Tool closures are defined here so each turn gets a fresh view of runtime state.
        def _combatant_ability_modifier(combatant, ability_name: str) -> int:
            attr = ABILITY_ALIAS.get(ability_name, ability_name).lower()
            return (getattr(combatant.stats, attr, 10) - 10) // 2

        def _normalize_text_entries(entries: Optional[List[str]]) -> List[MonsterTextEntry]:
            normalized: List[MonsterTextEntry] = []
            for index, item in enumerate(entries or [], start=1):
                text = str(item).strip()
                if not text:
                    continue
                normalized.append(MonsterTextEntry(name=f"Entry {index}", description=text))
            return normalized

        def lookup_rules(
            query: str,
            n_results: int = 3,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Search the local D&D rules knowledge base for relevant snippets and sources."""
            state = self._load_runtime_state(tool_context)
            normalized_query = (query or "").strip()
            if not normalized_query:
                return {"ok": False, "error": "query is required"}
            if not self.rag_engine.is_ready():
                return {
                    "ok": False,
                    "error": self.rag_engine.last_error or "RAG is not available",
                    "rag_status": self.rag_engine.status_payload(),
                }

            snippets = self.rag_engine.search(normalized_query, n_results=n_results)
            payload = {
                "query": normalized_query,
                "result_count": len(snippets),
                "snippets": snippets,
            }
            tool_result = ToolResult(
                tool_name="knowledge.lookup_rules",
                summary=f"Rule lookup for '{normalized_query}' returned {len(snippets)} snippet(s)",
                payload=payload,
                status="success" if snippets else "empty",
            )
            event = self._build_event(
                event_type="rules_retrieved",
                summary=tool_result.summary,
                content=normalized_query,
                payload=payload,
            )
            self._store_runtime_state(tool_context, state, tool_result=tool_result, timeline_event=event)
            return {"ok": True, **payload}

        # Generic dice and state-mutation tools come first so the DM can build richer turns from them.
        def roll_dice(expression: str, reason: str = "", tool_context: ToolContext = None) -> Dict[str, Any]:
            """Roll dice locally. Use this for checks, saves, attacks, damage, healing, and random outcomes."""
            state = self._load_runtime_state(tool_context)
            total, detail = DiceRoller.roll(expression)
            payload = {
                "expression": expression,
                "reason": reason,
                "total": total,
                "detail": detail,
            }
            tool_result = ToolResult(
                tool_name="dice.roll",
                summary=f"Roll {expression}: {detail} = {total}" + (f" | {reason}" if reason else ""),
                payload=payload,
            )
            event = self._build_event(
                event_type="dice_result",
                summary=tool_result.summary,
                content=reason,
                payload=payload,
            )
            self._store_runtime_state(tool_context, state, tool_result=tool_result, timeline_event=event)
            return payload

        def adjust_hp(
            target_ref: str,
            amount: int,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Adjust HP for a party character or encounter combatant. Positive heals, negative deals damage."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.update_target_hp(target_ref, amount)

            if not result:
                return {"ok": False, "error": f"Target not found: {target_ref}"}

            target = result["target"]
            payload = {
                "target_type": result["target_type"],
                "target_id": getattr(target, "character_id", getattr(target, "combatant_id", "")),
                "target_name": target.name,
                "amount": amount,
                "reason": reason,
                "hp_current": target.hp_current,
                "hp_max": target.hp_max,
            }
            tool_result = ToolResult(
                tool_name="target.adjust_hp",
                summary=(
                    f"{target.name} HP {amount:+d} -> {target.hp_current}/{target.hp_max}"
                    + (f" | {reason}" if reason else "")
                ),
                payload=payload,
            )
            event = self._build_event(
                event_type="hp_changed",
                summary=tool_result.summary,
                content=reason,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def add_status(target_ref: str, status: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Add a condition or status effect to a tracked party character or encounter combatant."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.add_status(target_ref, status)

            if not result:
                return {"ok": False, "error": f"Target not found: {target_ref}"}

            target = result["target"]
            payload = {
                "target_type": result["target_type"],
                "target_name": target.name,
                "status": status,
                "status_effects": list(target.status_effects),
            }
            tool_result = ToolResult(
                tool_name="target.add_status",
                summary=f"{target.name} gains status: {status}",
                payload=payload,
            )
            event = self._build_event(
                event_type="status_added",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def remove_status(target_ref: str, status: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Remove a condition or status effect from a tracked party character or encounter combatant."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.remove_status(target_ref, status)

            if not result:
                return {"ok": False, "error": f"Target not found: {target_ref}"}

            target = result["target"]
            payload = {
                "target_type": result["target_type"],
                "target_name": target.name,
                "status": status,
                "status_effects": list(target.status_effects),
            }
            tool_result = ToolResult(
                tool_name="target.remove_status",
                summary=f"{target.name} loses status: {status}",
                payload=payload,
            )
            event = self._build_event(
                event_type="status_removed",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def append_adventure_log(entry: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Append an important story event to the adventure log."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            logic.append_adventure_log(entry)

            payload = {"entry": entry, "log_size": len(state.adventure_log)}
            tool_result = ToolResult(
                tool_name="log.append",
                summary=f"Adventure log appended: {entry}",
                payload=payload,
            )
            event = self._build_event(
                event_type="log_entry",
                summary=tool_result.summary,
                content=entry,
                payload=payload,
            )
            self._store_runtime_state(tool_context, state, tool_result=tool_result, timeline_event=event)
            return {"ok": True, **payload}

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
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.add_inventory_item(
                character_ref=character_ref,
                item_name=item_name,
                quantity=quantity,
                item_type=item_type,
                notes=notes,
                source=source,
                tags=tags,
            )
            if not result:
                return {"ok": False, "error": f"Character not found: {character_ref}"}

            payload = {
                "character_id": result["character"].character_id,
                "character_name": result["character"].name,
                "item_name": result["item"].name,
                "quantity": quantity,
                "item_type": result["item"].type,
                "notes": result["item"].notes,
                "source": result["item"].source,
                "tags": list(result["item"].tags),
            }
            tool_result = ToolResult(
                tool_name="character.add_inventory_item",
                summary=f"{result['character'].name} gains {quantity} x {result['item'].name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="inventory_item_added",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

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
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            try:
                result = logic.record_evidence(
                    title=title,
                    summary=summary,
                    holder_ref=holder_ref,
                    source_ref=source_ref,
                    location=location,
                    tags=tags,
                    add_to_inventory=add_to_inventory,
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            evidence = result["evidence"]
            holder = result.get("character")
            payload = {
                "evidence_id": evidence.evidence_id,
                "title": evidence.title,
                "summary": evidence.summary,
                "holder_character_id": evidence.holder_character_id,
                "holder_character_name": holder.name if holder else "",
                "source_ref": evidence.source_ref,
                "location": evidence.location,
                "tags": list(evidence.tags),
            }
            tool_result = ToolResult(
                tool_name="story.record_evidence",
                summary=f"Evidence recorded: {evidence.title}",
                payload=payload,
            )
            event = self._build_event(
                event_type="evidence_recorded",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

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
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            try:
                result = logic.record_search_outcome(
                    searcher_ref=searcher_ref,
                    target_ref=target_ref,
                    summary=summary,
                    location=location,
                    recovered_items=recovered_items,
                    recovered_evidence_ids=recovered_evidence_ids,
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            record = result["search_record"]
            payload = record.model_dump(mode="json")
            tool_result = ToolResult(
                tool_name="story.record_search_outcome",
                summary=f"Search recorded: {result['character'].name} searched {record.target_ref or 'target'}",
                payload=payload,
            )
            event = self._build_event(
                event_type="search_recorded",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def record_major_experience(
            character_ref: str,
            entry: str,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Record a major experience or milestone on a character sheet."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.add_major_experience(character_ref, entry)
            if not result:
                return {"ok": False, "error": f"Character not found: {character_ref}"}

            payload = {
                "character_id": result["character"].character_id,
                "character_name": result["character"].name,
                "entry": result["entry"],
            }
            tool_result = ToolResult(
                tool_name="character.record_major_experience",
                summary=f"Major experience recorded for {result['character'].name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="major_experience_recorded",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def record_chapter_progress(
            chapter_title: str,
            summary: str,
            chapter_number: int = 0,
            completed: bool = False,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Persist the current chapter title and summary, optionally marking it complete."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.record_chapter_progress(
                title=chapter_title,
                summary=summary,
                chapter_number=chapter_number,
                completed=completed,
            )
            chapter = result["chapter"]
            payload = chapter.model_dump(mode="json")
            tool_result = ToolResult(
                tool_name="campaign.record_chapter_progress",
                summary=f"Chapter recorded: {chapter.chapter_number} - {chapter.title}",
                payload=payload,
            )
            event = self._build_event(
                event_type="chapter_recorded",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def set_defeat_state(
            target_ref: str,
            defeat_state: str,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Set a tracked combatant or character defeat state such as active, unconscious, captured, or dead."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.set_defeat_state(target_ref, defeat_state)
            if not result:
                return {"ok": False, "error": f"Target not found: {target_ref}"}

            target = result["target"]
            payload = {
                "target_name": target.name,
                "target_ref": target_ref,
                "defeat_state": target.defeat_state,
                "status_effects": list(target.status_effects),
            }
            tool_result = ToolResult(
                tool_name="combat.set_defeat_state",
                summary=f"{target.name} marked as {target.defeat_state}",
                payload=payload,
            )
            event = self._build_event(
                event_type="defeat_state_set",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def set_scene(scene: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Set the current scene. Preferred values: setup, exploration, combat, downtime."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            normalized = logic.set_scene(scene)

            payload = {"scene": normalized}
            tool_result = ToolResult(
                tool_name="scene.set",
                summary=f"Scene changed to: {normalized}",
                payload=payload,
            )
            event = self._build_event(
                event_type="scene_changed",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"scene": normalized},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def set_active_character(character_ref: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Switch the active character to the specified party member."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            character = logic.set_active_character(character_ref)

            if not character:
                return {"ok": False, "error": f"Character not found: {character_ref}"}

            payload = {
                "active_character_id": character.character_id,
                "active_character_name": character.name,
            }
            tool_result = ToolResult(
                tool_name="character.set_active",
                summary=f"Active character: {character.name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="active_character_changed",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"active_character_id": character.character_id},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        # Encounter tools are responsible for keeping combat state authoritative.
        def start_encounter(
            enemy_names: List[str],
            enemy_hp: int = 10,
            enemy_ac: int = 10,
            auto_roll_initiative: bool = True,
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Start a combat encounter and add enemy combatants."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            encounter = logic.start_encounter(enemy_names, enemy_hp=enemy_hp, enemy_ac=enemy_ac)
            if auto_roll_initiative:
                for combatant_id in encounter.initiative_order:
                    combatant = encounter.combatants.get(combatant_id)
                    if combatant and combatant.initiative is None:
                        logic.roll_initiative(combatant.combatant_id)

            payload = {
                "encounter_id": encounter.encounter_id,
                "enemy_names": enemy_names,
                "combatant_count": len(encounter.combatants),
                "round_number": encounter.round_number,
                "current_combatant_id": state.encounter.current_combatant_id if state.encounter else None,
            }
            tool_result = ToolResult(
                tool_name="encounter.start",
                summary=f"Encounter started with {len(enemy_names)} enemy group(s)",
                payload=payload,
            )
            event = self._build_event(
                event_type="encounter_started",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"scene": "combat", "encounter": encounter.model_dump(mode="json")},
                timeline_event=event,
            )
            return {"ok": True, **payload}

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
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            combatant = logic.add_enemy(
                name=name,
                hp_max=hp_max,
                ac=ac,
                initiative_bonus=initiative_bonus,
                side=side,
            )
            if auto_roll_initiative and combatant.initiative is None:
                logic.roll_initiative(combatant.combatant_id)

            payload = {
                "combatant_id": combatant.combatant_id,
                "name": combatant.name,
                "hp_current": combatant.hp_current,
                "hp_max": combatant.hp_max,
                "ac": combatant.ac,
                "initiative_bonus": combatant.initiative_bonus,
                "side": combatant.side,
            }
            tool_result = ToolResult(
                tool_name="encounter.add_enemy",
                summary=f"Enemy added: {combatant.name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="combatant_added",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"scene": "combat", "encounter": state.encounter.model_dump(mode="json")},
                timeline_event=event,
            )
            return {"ok": True, **payload}

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
            state = self._load_runtime_state(tool_context)
            monster = MonsterTemplate(
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
                traits=_normalize_text_entries(traits),
                actions=_normalize_text_entries(actions),
                reactions=_normalize_text_entries(reactions),
                bonus_actions=_normalize_text_entries(bonus_actions),
            )
            self.monster_storage.save_monster(monster)

            payload = {
                "monster_id": monster.monster_id,
                "name": monster.name,
                "creature_type": monster.creature_type,
                "challenge_rating": monster.challenge_rating,
            }
            tool_result = ToolResult(
                tool_name="monster.save_template",
                summary=f"Monster template saved: {monster.name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="monster_template_saved",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(tool_context, state, tool_result=tool_result, timeline_event=event)
            return {"ok": True, **payload}

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
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            monster = self.monster_storage.load_monster(monster_ref)
            if not monster:
                return {"ok": False, "error": f"Monster template not found: {monster_ref}"}

            spawned = logic.add_monster_from_template(
                monster=monster,
                quantity=quantity,
                custom_name=custom_name,
                hp_override=hp_override or None,
                side=side,
            )
            if auto_roll_initiative:
                for combatant in spawned:
                    if combatant.initiative is None:
                        logic.roll_initiative(combatant.combatant_id)
            payload = {
                "monster_id": monster.monster_id,
                "monster_name": monster.name,
                "quantity": len(spawned),
                "combatant_ids": [combatant.combatant_id for combatant in spawned],
            }
            tool_result = ToolResult(
                tool_name="monster.spawn_from_template",
                summary=f"Spawned {len(spawned)} combatant(s) from template {monster.name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="monster_spawned",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"scene": "combat", "encounter": state.encounter.model_dump(mode="json")},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        # Action tools are the rules-safe path for checks, attacks, saves, and spell slot use.
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
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            try:
                logic.require_current_actor(attacker_ref)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            result = logic.resolve_attack(
                attacker_ref=attacker_ref,
                target_ref=target_ref,
                attack_bonus=attack_bonus,
                damage_expression=damage_expression,
                damage_type=damage_type,
                resolution_mode=resolution_mode,
            )
            if not result:
                return {"ok": False, "error": f"Attack target not found: {target_ref}"}

            payload = {
                "attacker_name": result["attacker_name"],
                "target_name": result["target_name"],
                "target_ac": result["target_ac"],
                "attack_total": result["attack_total"],
                "attack_detail": result["attack_detail"],
                "hit": result["hit"],
                "critical": result["critical"],
                "damage_total": result["damage_total"],
                "damage_detail": result["damage_detail"],
                "damage_expression": result["damage_expression"],
                "damage_roll": result["damage_roll"],
                "damage_type": result["damage_type"],
                "resolution_mode": result["resolution_mode"],
                "target_hp_current": result["target_hp_current"],
                "target_defeat_state": result["target_defeat_state"],
                "reason": reason,
            }
            summary = (
                f"{result['attacker_name']} attacks {result['target_name']}: "
                f"{result['attack_total']} vs AC {result['target_ac']} -> "
                f"{'hit' if result['hit'] else 'miss'}"
            )
            if result["hit"]:
                summary += f", damage {result['damage_total']}"
                if damage_type:
                    summary += f" {damage_type}"
                if result["target_defeat_state"] != "active":
                    summary += f" | target {result['target_defeat_state']}"
            if reason:
                summary += f" | {reason}"
            tool_result = ToolResult(
                tool_name="combat.attack_target",
                summary=summary,
                payload=payload,
            )
            event = self._build_event(
                event_type="attack_resolved",
                summary=summary,
                content=reason,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch=result["patch"],
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def roll_skill_check(
            actor_ref: str,
            skill_name: str,
            modifier: Optional[int] = None,
            dc: int = 0,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Roll a skill check against an optional DC."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            try:
                logic.require_current_actor(actor_ref)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            resolved_modifier = modifier
            actor = logic.get_character(actor_ref)
            if actor and resolved_modifier is None:
                resolved_modifier = self.rules_catalog.get_skill_modifier(actor, skill_name)
            elif resolved_modifier is None:
                combatant = logic.get_combatant(actor_ref)
                if combatant:
                    resolved_modifier = int(combatant.skills.get(skill_name, _combatant_ability_modifier(combatant, SKILL_TO_ABILITY.get(skill_name, "wisdom"))))
            result = logic.roll_skill_check(
                actor_ref=actor_ref,
                skill_name=skill_name,
                modifier=int(resolved_modifier or 0),
                dc=dc,
            )
            payload = {**result, "reason": reason}
            summary = f"{result['actor_name']} {skill_name} check {result['total']}"
            if dc > 0:
                summary += f" vs DC {dc} -> {'success' if result['success'] else 'fail'}"
            if reason:
                summary += f" | {reason}"
            tool_result = ToolResult(
                tool_name="check.skill",
                summary=summary,
                payload=payload,
            )
            event = self._build_event(
                event_type="skill_check",
                summary=summary,
                content=reason,
                payload=payload,
            )
            self._store_runtime_state(tool_context, state, tool_result=tool_result, timeline_event=event)
            return {"ok": True, **payload}

        def roll_saving_throw(
            target_ref: str,
            save_name: str,
            dc: int,
            modifier: Optional[int] = None,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Roll a saving throw against a DC."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            resolved_modifier = modifier
            target = logic.get_character(target_ref)
            if target and resolved_modifier is None:
                resolved_modifier = self.rules_catalog.get_save_modifier(target, save_name)
            elif resolved_modifier is None:
                combatant = logic.get_combatant(target_ref)
                if combatant:
                    resolved_modifier = int(combatant.saving_throws.get(save_name, _combatant_ability_modifier(combatant, save_name)))
            result = logic.roll_saving_throw(
                target_ref=target_ref,
                save_name=save_name,
                modifier=int(resolved_modifier or 0),
                dc=dc,
            )
            payload = {**result, "reason": reason}
            summary = f"{result['target_name']} {save_name} save {result['total']} vs DC {dc} -> {'success' if result['success'] else 'fail'}"
            if reason:
                summary += f" | {reason}"
            tool_result = ToolResult(
                tool_name="check.saving_throw",
                summary=summary,
                payload=payload,
            )
            event = self._build_event(
                event_type="saving_throw",
                summary=summary,
                content=reason,
                payload=payload,
            )
            self._store_runtime_state(tool_context, state, tool_result=tool_result, timeline_event=event)
            return {"ok": True, **payload}

        def cast_spell(
            caster_ref: str,
            spell_name: str,
            slot_level: int = 0,
            reason: str = "",
            tool_context: ToolContext = None,
        ) -> Dict[str, Any]:
            """Validate prepared/known spell access and spend a spell slot if required."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            try:
                logic.require_current_actor(caster_ref)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            caster = logic.get_character(caster_ref)
            if not caster:
                return {"ok": False, "error": f"Spell caster not found: {caster_ref}"}

            validation = self.rules_catalog.can_cast_spell(
                character=caster,
                spell_name=spell_name,
                slot_level=slot_level or None,
            )
            if not validation["ok"]:
                return validation

            resolved_slot = int(validation["resolved_slot_level"])
            self.rules_catalog.consume_spell_slot(caster, resolved_slot)
            payload = {
                "caster_id": caster.character_id,
                "caster_name": caster.name,
                "spell_name": spell_name,
                "spell_level": int(validation["spell"].get("level", 0)),
                "resolved_slot_level": resolved_slot,
                "reason": reason,
                "remaining_slots": {
                    level: {
                        "total": slot.total,
                        "used": slot.used,
                    }
                    for level, slot in caster.spells.slots.items()
                },
            }
            summary = f"{caster.name} casts {spell_name}"
            if resolved_slot > 0:
                summary += f" using a level {resolved_slot} slot"
            if reason:
                summary += f" | {reason}"
            tool_result = ToolResult(
                tool_name="magic.cast_spell",
                summary=summary,
                payload=payload,
            )
            event = self._build_event(
                event_type="spell_cast",
                summary=summary,
                content=reason,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"characters": {caster.character_id: {"spells": caster.spells.model_dump(mode="json")}}},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def set_initiative(combatant_ref: str, initiative: int, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Set a combatant initiative score directly."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            combatant = logic.set_initiative(combatant_ref, initiative)

            if not combatant:
                return {"ok": False, "error": f"Combatant not found: {combatant_ref}"}

            payload = {
                "combatant_id": combatant.combatant_id,
                "name": combatant.name,
                "initiative": combatant.initiative,
            }
            tool_result = ToolResult(
                tool_name="encounter.set_initiative",
                summary=f"{combatant.name} initiative set to {combatant.initiative}",
                payload=payload,
            )
            event = self._build_event(
                event_type="initiative_set",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def roll_initiative(combatant_ref: str, tool_context: ToolContext = None) -> Dict[str, Any]:
            """Roll initiative for a combatant using 1d20 plus initiative bonus."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            result = logic.roll_initiative(combatant_ref)

            if not result:
                return {"ok": False, "error": f"Combatant not found: {combatant_ref}"}

            combatant = result["combatant"]
            payload = {
                "combatant_id": combatant.combatant_id,
                "name": combatant.name,
                "initiative": combatant.initiative,
                "expression": result["expression"],
                "detail": result["detail"],
            }
            tool_result = ToolResult(
                tool_name="encounter.roll_initiative",
                summary=f"{combatant.name} initiative {combatant.initiative} via {result['expression']}",
                payload=payload,
            )
            event = self._build_event(
                event_type="initiative_rolled",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def advance_turn(tool_context: ToolContext = None) -> Dict[str, Any]:
            """Advance the encounter to the next combatant."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            combatant = logic.advance_turn()

            if not combatant:
                return {"ok": False, "error": "No active encounter or initiative order"}

            payload = {
                "current_combatant_id": combatant.combatant_id,
                "current_combatant_name": combatant.name,
                "round_number": state.encounter.round_number if state.encounter else 0,
            }
            tool_result = ToolResult(
                tool_name="encounter.advance_turn",
                summary=f"Turn advanced to {combatant.name}",
                payload=payload,
            )
            event = self._build_event(
                event_type="turn_advanced",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
                timeline_event=event,
            )
            return {"ok": True, **payload}

        def end_encounter(tool_context: ToolContext = None) -> Dict[str, Any]:
            """End the current encounter and leave combat scene."""
            state = self._load_runtime_state(tool_context)
            logic = GameLogic(state)
            outcome = logic.finalize_encounter()

            if not outcome:
                return {"ok": False, "error": "No encounter to end"}

            encounter = outcome["encounter"]
            payload = {
                **outcome["summary_payload"],
                "adventure_log_entry": outcome["adventure_log_entry"],
            }
            tool_result = ToolResult(
                tool_name="encounter.end",
                summary=outcome["summary"],
                payload=payload,
            )
            event = self._build_event(
                event_type="encounter_ended",
                summary=tool_result.summary,
                payload=payload,
            )
            self._store_runtime_state(
                tool_context,
                state,
                tool_result=tool_result,
                state_patch={
                    "scene": state.scene,
                    "campaign": {"phase": state.campaign.phase},
                    "encounter": encounter.model_dump(mode="json"),
                    "adventure_log": state.adventure_log,
                },
                timeline_event=event,
            )
            return {"ok": True, **payload}

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
