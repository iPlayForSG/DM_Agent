"""FastAPI entrypoint exposing builder, campaign, encounter, and local action routes."""

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent import DMAgent
from action_service import GameActionService
from ability_scores import AbilityScoreService
from adventure_service import (
    ensure_ai_generated_adventure_option,
    generate_initial_adventures,
    is_ai_generated_adventure_id,
    is_model_generated_adventure_id,
    opening_action_suggestions,
)
from game_logic import GameLogic
from library import Library
from model_backends import DEFAULT_MODEL_PROVIDER
from models import ActionSuggestion, Character, ChatMessage, GameState, MonsterTemplate, SessionEvent, TurnResult
from rules_catalog import RuleCatalog, proficiency_bonus_for_level
from starter_shop import get_shop_item_by_name
from storage import CharacterStorage, GameStorage, MonsterStorage, StateConflictError, PENDING_TURN_ACTION_MESSAGE
from turn_stream import turn_stream_context, turn_time_budget, remaining_turn_seconds
from player_projection import PlayerJSONResponse, player_payload
from roll_capture import capture_rolls, settle_rolls

app = FastAPI(title="D&D 2024 DM Agent", default_response_class=PlayerJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

library = Library()
game_storage = GameStorage()
char_storage = CharacterStorage()
monster_storage = MonsterStorage()
agent = DMAgent()
_action_suggestion_locks: Dict[str, asyncio.Lock] = {}
rule_catalog = RuleCatalog()
action_service = GameActionService()
ability_score_service = AbilityScoreService(rule_catalog)


@app.exception_handler(StateConflictError)
async def state_conflict_handler(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.on_event("shutdown")
def shutdown_event():
    agent.close()


# Request payloads stay intentionally thin and map 1:1 to frontend form state.
class ChatRequest(BaseModel):
    message: str


class RewriteMessageRequest(BaseModel):
    message: str


class CreateGameRequest(BaseModel):
    game_id: str
    title: str = ""
    character_ids: List[str] = Field(default_factory=list)
    character_names: List[str] = Field(default_factory=list)


class BatchDeleteRequest(BaseModel):
    ids: List[str] = Field(default_factory=list)


class SelectAdventureRequest(BaseModel):
    adventure_id: str


class AttackActionRequest(BaseModel):
    attacker_ref: str
    target_ref: str
    attack_bonus: int | None = None
    damage_expression: str = ""
    attack_name: str = ""
    cast_id: str = ""
    damage_type: str = ""
    resolution_mode: str = "normal"


class SkillCheckActionRequest(BaseModel):
    actor_ref: str
    skill_name: str
    dc: int = 0
    modifier: int | None = None


class SavingThrowActionRequest(BaseModel):
    target_ref: str
    save_name: str
    dc: int = 0
    modifier: int | None = None
    source_ref: str = ""
    spell_name: str = ""


class CastSpellActionRequest(BaseModel):
    caster_ref: str
    spell_name: str
    slot_level: int = 0
    target_ref: str = ""
    damage_type: str = ""


class UseItemActionRequest(BaseModel):
    user_ref: str
    item_name: str
    quantity: int = 1


class UseFeatureActionRequest(BaseModel):
    actor_ref: str
    feature_name: str
    action_cost: str = "action"
    resource_name: str = ""
    resource_cost: int = 0
    reason: str = ""


class StartEncounterRequest(BaseModel):
    enemy_names: List[str] = Field(default_factory=list)
    enemy_hp: int = 10
    enemy_ac: int = 10
    auto_roll_initiative: bool = True


class AddEnemyEncounterRequest(BaseModel):
    name: str
    hp_max: int = 10
    ac: int = 10
    initiative_bonus: int = 0
    side: str = "enemy"
    auto_roll_initiative: bool = True


class SpawnMonsterEncounterRequest(BaseModel):
    monster_id: str
    quantity: int = 1
    custom_name: str = ""
    hp_override: int | None = None
    side: str = "enemy"
    auto_roll_initiative: bool = True


class RemoveCombatantRequest(BaseModel):
    combatant_ref: str


class SetInitiativeRequest(BaseModel):
    combatant_ref: str
    initiative: int


class RollInitiativeRequest(BaseModel):
    combatant_ref: str


class RuleLookupRequest(BaseModel):
    query: str
    n_results: int = 3


class AbilityScoreRequest(BaseModel):
    method: str
    scores: Dict[str, int] = Field(default_factory=dict)


class LLMConfigUpdateRequest(BaseModel):
    profile_id: str = ""
    profile_label: str = ""
    provider: str = DEFAULT_MODEL_PROVIDER
    model_name: str = ""
    reasoning_effort: str = ""
    base_url: str = ""
    api_key: Optional[str] = None
    cli_command: str = ""
    cli_timeout_s: int = 300
    activate: bool = True


class LLMProfileSelectRequest(BaseModel):
    profile_id: str


class ReplyLengthSettingsRequest(BaseModel):
    min_chars: int = 0
    max_chars: int = 0


# Small payload builders keep the route handlers mostly orchestration-only.
def health_payload():
    return {
        "status": "ok",
        "rag_enabled": agent.rag_engine.is_ready(),
        "rag_status": agent.rag_engine.status_payload(),
        "chat_backend": agent.backend_name,
        "checkpoint_backend": agent.checkpoint_backend,
        "checkpoint_db_path": agent.checkpoint_db_path,
        "checkpoint_warning": agent.checkpoint_warning,
        "agent_topology": agent.agent_topology,
        "llm": agent.llm_runtime_payload(),
        "api_features": {
            "delete_games": True,
            "delete_characters": True,
            "batch_delete": True,
            "ai_generated_adventures": True,
            "llm_profiles": True,
            "action_suggestions": True,
            "action_suggestion_tool": True,
            "reply_length_settings": True,
            "ability_score_generation": True,
        },
    }


def _turn_result_payload(result: TurnResult) -> Dict[str, Any]:
    return player_payload(result.model_dump(mode="json"))


def _sse_event(event: str, data: Dict[str, Any]) -> str:
    payload = json.dumps(player_payload(data), ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _turn_node_event_payloads(result: TurnResult, game_id: str, mode: str) -> List[Dict[str, Any]]:
    trace = result.turn_trace
    if not trace or not trace.node_traces:
        return []
    payloads: List[Dict[str, Any]] = []
    for index, node_trace in enumerate(trace.node_traces):
        payloads.append(
            {
                "game_id": game_id,
                "mode": mode,
                "trace_id": trace.trace_id,
                "turn_number": trace.turn_number,
                "index": index,
                **node_trace.model_dump(mode="json"),
            }
        )
    return payloads


def _turn_detail_event_payloads(result: TurnResult, game_id: str, mode: str) -> List[tuple[str, Dict[str, Any]]]:
    trace = result.turn_trace
    if not trace:
        return []

    base_payload = {
        "game_id": game_id,
        "mode": mode,
        "trace_id": trace.trace_id,
        "turn_number": trace.turn_number,
    }
    events: List[tuple[str, Dict[str, Any]]] = []

    if trace.rag_metadata:
        metadata = dict(trace.rag_metadata or {})
        queries = metadata.get("queries") if isinstance(metadata.get("queries"), list) else []
        sources = metadata.get("sources") if isinstance(metadata.get("sources"), list) else []
        try:
            snippet_count = int(metadata.get("snippet_count") or 0)
        except (TypeError, ValueError):
            snippet_count = 0
        events.append(
            (
                "rag.completed",
                {
                    **base_payload,
                    "status": "completed",
                    "intent": metadata.get("intent", "none"),
                    "reason": metadata.get("reason", ""),
                    "query_count": len(queries),
                    "snippet_count": snippet_count,
                    "source_count": len(sources),
                    "queries": queries,
                    "sources": sources,
                    "metadata": metadata,
                },
            )
        )

    for index, tool_result in enumerate(trace.tool_results or []):
        if hasattr(tool_result, "model_dump"):
            payload = tool_result.model_dump(mode="json")
        else:
            payload = dict(tool_result or {})
        result_payload = payload.get("payload", {})
        # 暗骰可以留在 DM 的权威 trace 中供后续裁定，但绝不能进入玩家可见的 SSE 思考面板。
        if str(result_payload.get("visibility") or "public").strip().casefold() == "hidden":
            continue
        events.append(
            (
                "tool.completed",
                {
                    **base_payload,
                    "index": index,
                    "tool_name": payload.get("tool_name", ""),
                    "status": payload.get("status", "success"),
                    "summary": payload.get("summary", ""),
                    "payload": result_payload,
                },
            )
        )

    issues = list(trace.validation_issues or [])
    for index, note in enumerate(trace.validation_notes or []):
        issue_payload: Dict[str, Any] = {}
        if index < len(issues):
            issue = issues[index]
            issue_payload = issue.model_dump(mode="json") if hasattr(issue, "model_dump") else dict(issue or {})
        events.append(
            (
                "validation.note",
                {
                    **base_payload,
                    "index": index,
                    "status": "noted",
                    "note": str(note),
                    "validator": issue_payload.get("validator", ""),
                    "severity": issue_payload.get("severity", "info"),
                    "action": issue_payload.get("action", "noted"),
                    "metadata": issue_payload.get("metadata", {}),
                },
            )
        )

    return events


async def _execute_turn_request(
    state: GameState,
    message: str,
    stream_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> tuple[TurnResult, str]:
    mode = "resume" if state.pending_turn else "start"
    turn_method = agent.resume_turn if state.pending_turn else agent.run_turn
    initial_rolls = state.pending_turn.roll_records if state.pending_turn else []
    base_history_length = len(state.chat_history)

    def execute_in_worker() -> TurnResult:
        with turn_stream_context(stream_event), turn_time_budget(getattr(agent, "cli_timeout_s", 300)), capture_rolls(initial_rolls) as capture:
            result = asyncio.run(turn_method(state, message))
            if result.turn_status != "failed":
                remaining_turn_seconds()
            records = settle_rolls(capture.records, result.turn_status)
            result.roll_records = records
            if result.game_state.pending_turn:
                result.game_state.pending_turn.roll_records = records
                result.pending_input["roll_records"] = [record.model_dump(mode="json") for record in records]
            else:
                # 绑定新增的主持回复，不能把新回合的骰点挂到内容相同的旧回复上。
                for messages in (result.game_state.chat_history[base_history_length:], result.history[base_history_length:], result.history_append):
                    for reply in reversed(messages):
                        if reply.role == "assistant":
                            reply.roll_records = records
                            reply.roll_records_recorded = True
                            break
            return result

    result = await asyncio.to_thread(execute_in_worker)
    return result, mode


def _visible_chat_messages(state: GameState) -> List[ChatMessage]:
    return [message for message in state.chat_history if message.kind != "tool_result"]


def _visible_message_count(state: GameState) -> int:
    return len(_visible_chat_messages(state))


def _rewind_safe_state(state: GameState) -> GameState:
    snapshot = state.model_copy(deep=True)
    # LangGraph interrupt 是一次性执行位置，不是可恢复的剧情分支。rewind 只能回到已提交状态，
    # 否则已消费的 thread_id 会重新显示选择卡，却无法再次恢复同一个暂停回合。
    snapshot.pending_turn = None
    return snapshot


def _state_before_last_assistant_message(state: GameState) -> GameState:
    snapshot = state.model_copy(deep=True)
    for index in range(len(snapshot.chat_history) - 1, -1, -1):
        message = snapshot.chat_history[index]
        if message.kind != "tool_result" and message.role == "assistant":
            del snapshot.chat_history[index]
            break

    for index in range(len(snapshot.timeline) - 1, -1, -1):
        if snapshot.timeline[index].type == "assistant_response":
            del snapshot.timeline[index]
            break
    return snapshot


def _action_suggestions_for_state(state: GameState) -> List[Dict[str, Any]]:
    for message in reversed(_visible_chat_messages(state)):
        if message.role == "assistant":
            return [item.model_dump(mode="json") for item in message.action_suggestions]
    return []


def _latest_assistant_suggestion_status(state: GameState) -> tuple[List[Dict[str, Any]], bool]:
    for message in reversed(_visible_chat_messages(state)):
        if message.role == "assistant":
            return (
                [item.model_dump(mode="json") for item in message.action_suggestions],
                bool(message.action_suggestions_generated),
            )
    return [], False


def _bind_action_suggestions_to_reply(
    state: GameState,
    message_index: int,
    response: str,
    suggestions: List[ActionSuggestion],
) -> bool:
    if message_index < 0 or message_index >= len(state.chat_history):
        return False
    message = state.chat_history[message_index]
    if message.kind == "tool_result" or message.role != "assistant" or message.content != response:
        return False
    message.action_suggestions = list(suggestions)
    message.action_suggestions_generated = True
    return True


def _merge_persisted_action_suggestions(target: GameState, persisted: GameState) -> None:
    # 主回合和提交后投影可以交叠；合并已经落盘的消息投影，避免较早加载的回合快照把缓存覆盖掉。
    for index, source in enumerate(persisted.chat_history):
        if index >= len(target.chat_history) or not source.action_suggestions_generated:
            continue
        destination = target.chat_history[index]
        if destination.role != source.role or destination.kind != source.kind or destination.content != source.content:
            continue
        if not destination.action_suggestions_generated:
            destination.action_suggestions = list(source.action_suggestions)
            destination.action_suggestions_generated = True


def _action_suggestion_lock(game_id: str) -> asyncio.Lock:
    lock = _action_suggestion_locks.get(game_id)
    if lock is None:
        lock = asyncio.Lock()
        _action_suggestion_locks[game_id] = lock
    return lock


async def _execute_turn_and_save(
    game_id: str,
    state: GameState,
    message: str,
    stream_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    expected_version: Optional[str] = None,
    preserve_on_failure: bool = False,
) -> tuple[TurnResult, str]:
    base_message_index = _visible_message_count(state)
    expected_version = state.state_version if expected_version is None else expected_version
    base_snapshot = _rewind_safe_state(state)

    result, mode = await _execute_turn_request(state, message, stream_event=stream_event)
    if preserve_on_failure and result.turn_status == "failed":
        # 重写/重试尚未产生有效新分支时，前端恢复旧消息，存储也必须保留同一旧分支。
        raise RuntimeError(result.response or "回合失败，原剧情分支未改变。")

    persisted_state = game_storage.load_game(game_id)
    if persisted_state:
        _merge_persisted_action_suggestions(result.game_state, persisted_state)

    assistant_message_index = base_message_index + 1
    game_storage.save_turn(
        game_id, result.game_state,
        expected_version=expected_version,
        snapshots={
            base_message_index: base_snapshot,
            assistant_message_index: _state_before_last_assistant_message(result.game_state),
        },
        prune_from=base_message_index,
    )
    return result, mode


def classes_payload():
    return {"classes": library.get_all_classes()}


def spells_payload(class_name: str):
    return _add_display_fields(
        {"spells": library.get_spells_by_class(rule_catalog.resolve_spell_library_key(class_name))}
    )


def builder_payload():
    return _add_display_fields(rule_catalog.get_builder_catalog())


def characters_payload():
    summaries = [summary.model_dump(mode="json") for summary in char_storage.list_character_summaries()]
    summaries = [_add_display_fields(summary) for summary in summaries]
    return {
        "characters": summaries,
        "names": [summary["name"] for summary in summaries],
    }


def monsters_payload():
    summaries = [summary.model_dump(mode="json") for summary in monster_storage.list_monster_summaries()]
    summaries = [_add_display_fields(summary) for summary in summaries]
    return {
        "monsters": summaries,
        "names": [summary["name"] for summary in summaries],
    }


def _load_monster_template_for_state(state: GameState, identifier: str) -> Optional[MonsterTemplate]:
    monster = state.monster_templates.get(identifier)
    if monster:
        return monster
    for template in state.monster_templates.values():
        if template.name == identifier:
            return template
    return monster_storage.load_monster(identifier)


def game_monsters_payload(state: GameState):
    standard = [summary.model_dump(mode="json") for summary in monster_storage.list_monster_summaries()]
    game_specific = [monster.to_summary().model_dump(mode="json") for monster in state.monster_templates.values()]
    for summary in standard:
        summary["scope"] = "standard"
    for summary in game_specific:
        summary["scope"] = "game"
    combined = [_add_display_fields(summary) for summary in [*standard, *game_specific]]
    combined.sort(key=lambda item: (item.get("scope") != "standard", item["name"]))
    return {
        "monsters": combined,
        "standard_count": len(standard),
        "game_count": len(game_specific),
        "names": [summary["name"] for summary in combined],
    }


def games_payload():
    summaries = [summary.model_dump(mode="json") for summary in game_storage.list_game_summaries()]
    return {
        "games": summaries,
        "ids": [summary["game_id"] for summary in summaries],
    }


def delete_characters_payload(identifiers: List[str]) -> Dict[str, Any]:
    deleted: List[str] = []
    missing: List[str] = []
    for identifier in dict.fromkeys(item for item in identifiers if item):
        char = char_storage.load_character(identifier)
        if not char:
            missing.append(identifier)
            continue
        if char_storage.delete_character(char.character_id):
            deleted.append(char.character_id)
        else:
            missing.append(identifier)
    return {"status": "deleted", "deleted": deleted, "missing": missing}


def delete_games_payload(game_ids: List[str]) -> Dict[str, Any]:
    deleted: List[str] = []
    missing: List[str] = []
    for game_id in dict.fromkeys(item for item in game_ids if item):
        state = game_storage.load_game(game_id)
        if not state:
            missing.append(game_id)
            continue
        game_storage.delete_game(game_id)
        deleted.append(state.game_id or game_id)
    return {"status": "deleted", "deleted": deleted, "missing": missing}


def _derive_character_attack_options(character: Character):
    attacks = []
    str_mod = rule_catalog.get_ability_modifier(character, "strength")
    dex_mod = rule_catalog.get_ability_modifier(character, "dexterity")

    for item in character.inventory:
        if item.type != "weapon":
            continue

        properties = set(item.properties or [])
        if "Ranged" in properties or "Thrown" in properties or "Finesse" in properties:
            ability_mod = max(str_mod, dex_mod)
        else:
            ability_mod = str_mod

        attack_bonus = item.attack_bonus if item.attack_bonus is not None else ability_mod + proficiency_bonus_for_level(character.level)
        attacks.append(
            {
                "name": item.name,
                "name_display": library.localize_game_terms(item.name),
                "attack_bonus": attack_bonus,
                "damage_expression": item.damage_expression,
                "damage_type": item.damage_type,
                "damage_type_display": library.localize_game_terms(item.damage_type),
                "source": "inventory",
            }
        )
    return attacks


def _derive_monster_attack_options(monster):
    attacks = []
    for action in monster.actions:
        parsed = _parse_monster_action(action.description)
        if parsed:
            attacks.append(
                {
                    "name": action.name,
                    "name_display": library.localize_game_terms(action.name),
                    **parsed,
                    "damage_type_display": library.localize_game_terms(parsed.get("damage_type", "")),
                }
            )
    return attacks


def _monster_feature_name(entry):
    name = str(entry.name or "").strip()
    if name and not re.fullmatch(r"Entry\s+\d+", name, re.IGNORECASE):
        return name
    description = str(entry.description or "").strip()
    if not description:
        return name or "Feature"
    return description.split(".", 1)[0].strip()[:80] or name or "Feature"


def _action_cost_display(action_cost: str) -> str:
    if action_cost == "bonus_action":
        return library.localize_game_terms("Bonus Action")
    if action_cost == "reaction":
        return library.localize_game_terms("Reaction")
    if action_cost == "free":
        return "自由动作"
    return library.localize_game_terms("Action")


def _derive_character_feature_options(character: Character):
    features = []
    for resource_name, pool in character.resources.items():
        definition = GameLogic.feature_definition_for(resource_name)
        action_cost = definition.get("action_cost", "action")
        resource_cost = int(definition.get("resource_cost") or 0)
        features.append(
            {
                "name": str(definition.get("name") or resource_name),
                "name_display": library.localize_game_terms(str(definition.get("name") or resource_name)),
                "action_cost": action_cost,
                "action_cost_display": _action_cost_display(action_cost),
                "resource_name": resource_name,
                "resource_cost": resource_cost,
                "resource_current": pool.current_value,
                "resource_max": pool.max_value,
                "resource_recovery": pool.recovery,
                "source": "character_resource",
            }
        )
    return sorted(features, key=lambda item: (item["action_cost"], item["name"]))


def _derive_monster_feature_options(monster: MonsterTemplate):
    features = []
    groups = [
        ("traits", "free"),
        ("actions", "action"),
        ("bonus_actions", "bonus_action"),
        ("reactions", "reaction"),
    ]
    for source, action_cost in groups:
        for entry in getattr(monster, source, []) or []:
            name = _monster_feature_name(entry)
            features.append(
                {
                    "name": name,
                    "name_display": library.localize_game_terms(name),
                    "action_cost": action_cost,
                    "action_cost_display": _action_cost_display(action_cost),
                    "resource_name": "",
                    "resource_cost": 0,
                    "source": f"monster_{source}",
                }
            )
    return features


def _add_display_fields(value):
    if isinstance(value, list):
        return [_add_display_fields(item) for item in value]
    if not isinstance(value, dict):
        return value

    localized = {key: _add_display_fields(item) for key, item in value.items()}
    display_keys = {
        "name",
        "label",
        "description",
        "notes",
        "title",
        "summary",
        "tone",
        "difficulty",
        "opening_scene",
        "type",
        "damage_type",
        "creature_type",
        "alignment",
        "source",
        "recovery",
        "origin_feat",
        "class_name",
        "background_name",
        "species",
        "school",
    }
    for key in display_keys:
        raw = value.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        display = library.localize_game_terms(raw)
        if display != raw:
            localized[f"{key}_display"] = display
    for key in ("properties", "tags", "traits", "status_effects", "cantrips", "prepared"):
        raw_values = value.get(key)
        if not isinstance(raw_values, list):
            continue
        display_values = [library.localize_game_terms(str(item)) for item in raw_values]
        if display_values != raw_values:
            localized[f"{key}_display"] = display_values
    return localized


def _build_spell_options(character: Character):
    options = []

    for spell_name in character.spells.cantrips:
        details = library.get_spell_details(spell_name) or {}
        display_name = details.get("name") or spell_name
        options.append(
            {
                "name": display_name,
                "nameEN": details.get("nameEN", ""),
                "level": int(details.get("level", 0)),
                "school": details.get("school", ""),
                "requires_slot": False,
                "available": True,
                "available_slot_levels": [],
            }
        )

    for spell_name in character.spells.prepared:
        details = library.get_spell_details(spell_name) or {}
        display_name = details.get("name") or spell_name
        spell_level = int(details.get("level", 0))
        available_slot_levels = [
            int(level)
            for level, slot in character.spells.slots.items()
            if int(level) >= spell_level and slot.total - slot.used > 0
        ]
        options.append(
            {
                "name": display_name,
                "nameEN": details.get("nameEN", ""),
                "level": spell_level,
                "school": details.get("school", ""),
                "requires_slot": spell_level > 0,
                "available": spell_level == 0 or bool(available_slot_levels),
                "available_slot_levels": available_slot_levels,
            }
        )

    for option in options:
        details = library.get_spell_details(option["name"]) or {}
        # 说明属于只读展示投影，复用同一法术目录；不把描述写进角色的权威法术列表。
        option.update({
            "description": details.get("desc") or details.get("description") or "",
            "higher_levels": details.get("higherLevels") or details.get("higher_levels") or "",
            "casting_time": details.get("castingTime") or details.get("casting_time") or "",
            "range": details.get("range") or "",
            "duration": details.get("duration") or "",
            "components": details.get("components") or "",
            "concentration": bool(details.get("concentration")),
            "ritual": bool(details.get("ritual")),
        })
        option["action_cost"] = rule_catalog.spell_action_cost(details)
        try:
            profile = rule_catalog.get_spell_attack_profile(character, option["name"], option["level"])
            option["requires_attack_target"] = bool(profile)
            option["damage_types"] = profile["damage_types"] if profile else []
            option["damage_type_labels"] = {kind: library.localize_game_terms(kind) for kind in option["damage_types"]}
        except ValueError as exc:
            option["available"] = False
            option["resolution_error"] = str(exc)
    return _add_display_fields(sorted(options, key=lambda item: (item["level"], item["name"])))


def _build_item_options(character: Character):
    options = []
    for item in character.inventory:
        catalog_item = get_shop_item_by_name(item.name) or {}
        description = str(catalog_item.get("description") or catalog_item.get("desc") or "").strip()
        notes = str(item.notes or catalog_item.get("notes") or "").strip()
        # 自定义备注优先保留，目录说明仅补充阅读；缺少说明时不推测物品效果。
        options.append({
            **item.model_dump(mode="json"),
            "description": "\n\n".join(dict.fromkeys(text for text in (description, notes) if text)),
        })
    return _add_display_fields(options)


_CHINESE_DAMAGE_TYPES = {
    "钝击": "bludgeoning",
    "穿刺": "piercing",
    "挥砍": "slashing",
    "火焰": "fire",
    "寒冷": "cold",
    "闪电": "lightning",
    "雷鸣": "thunder",
    "强酸": "acid",
    "酸": "acid",
    "毒素": "poison",
    "毒性": "poison",
    "黯蚀": "necrotic",
    "坏死": "necrotic",
    "光耀": "radiant",
    "力场": "force",
    "心灵": "psychic",
    "精神": "psychic",
}


def _parse_monster_action(text: str):
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return None

    attack_bonus = None
    damage_expression = ""
    damage_type = ""

    match_bonus = re.search(r"([+-]\d+)\s*to hit", normalized, re.IGNORECASE)
    if not match_bonus:
        match_bonus = re.search(
            r"(?:攻击检定|武器攻击|法术攻击|近战或远程攻击|近战攻击|远程攻击)[^。；;]*?([+-]\d+)",
            normalized,
        )
    if not match_bonus:
        match_bonus = re.search(r"命中\s*([+-]\d+)", normalized)
    if match_bonus:
        attack_bonus = int(match_bonus.group(1))

    match_damage = re.search(r"(\d+d\d+(?:[+-]\d+)?)", normalized, re.IGNORECASE)
    if match_damage:
        damage_expression = match_damage.group(1)

    match_type = re.search(r"(slashing|piercing|bludgeoning|fire|cold|lightning|thunder|acid|poison|necrotic|radiant|force|psychic)", normalized, re.IGNORECASE)
    if match_type:
        damage_type = match_type.group(1).lower()
    else:
        chinese_types = "|".join(re.escape(item) for item in sorted(_CHINESE_DAMAGE_TYPES, key=len, reverse=True))
        match_chinese_type = re.search(rf"({chinese_types})\s*伤害", normalized)
        if match_chinese_type:
            damage_type = _CHINESE_DAMAGE_TYPES[match_chinese_type.group(1)]

    if attack_bonus is None or not damage_expression:
        return None

    return {
        "attack_bonus": attack_bonus,
        "damage_expression": damage_expression,
        "damage_type": damage_type,
        "source": "monster_action",
    }


def action_options_payload(state: GameState):
    # The frontend consumes a normalized action menu instead of raw character JSON.
    actors = []
    current_combatant = state.encounter.get_current_combatant() if state.encounter and state.encounter.active else None
    current_actor_ref = (
        current_combatant.linked_character_id
        if current_combatant and current_combatant.linked_character_id
        else current_combatant.combatant_id
        if current_combatant
        else None
    )
    for character in state.characters.values():
        is_current_actor = bool(current_combatant and current_combatant.linked_character_id == character.character_id)
        linked_combatant = GameLogic(state).get_combatant(character.character_id)
        reaction_used = bool(state.encounter and linked_combatant and state.encounter.reactions_used.get(linked_combatant.combatant_id))
        actors.append(
            {
                "ref": character.character_id,
                "name": character.name,
                "type": "character",
                "side": "party",
                "is_current_actor": is_current_actor,
                "can_act": character.hp_current > 0 and character.defeat_state == "active" and not GameLogic.is_incapacitated(character),
                "reaction_available": not reaction_used,
                "defeat_state": character.defeat_state,
                "defeat_state_display": library.localize_game_terms(character.defeat_state.title()),
                "gold_gp": character.gold_gp,
                "starter_option_id": character.starter_option_id,
                "spells": {
                    "cantrips": library.normalize_spell_names(character.spells.cantrips),
                    "prepared": library.normalize_spell_names(character.spells.prepared),
                    "options": _build_spell_options(character),
                    "slots": {
                        level: {"total": slot.total, "used": slot.used}
                        for level, slot in character.spells.slots.items()
                    },
                },
                "items": _build_item_options(character),
                "skills": sorted(character.skill_proficiencies.keys()),
                "saves": sorted(character.save_proficiencies.keys()),
                "resources": {
                    name: {
                        "current_value": pool.current_value,
                        "max_value": pool.max_value,
                        "recovery": pool.recovery,
                        "description": pool.description,
                    }
                    for name, pool in character.resources.items()
                },
                "attacks": _derive_character_attack_options(character),
                "features": _derive_character_feature_options(character),
            }
        )

    if state.encounter:
        for combatant_id in state.encounter.initiative_order:
            combatant = state.encounter.combatants.get(combatant_id)
            if not combatant:
                continue
            if combatant.linked_character_id:
                continue
            actors.append(
                {
                    "ref": combatant.combatant_id,
                    "name": combatant.name,
                    "type": "combatant",
                    "side": combatant.side,
                    "is_current_actor": bool(current_combatant and current_combatant.combatant_id == combatant.combatant_id),
                    "defeat_state": combatant.defeat_state,
                    "defeat_state_display": library.localize_game_terms(combatant.defeat_state.title()),
                    "initiative": combatant.initiative,
                    "monster_template_id": combatant.monster_template_id,
                    "skills": sorted(combatant.skills.keys()),
                    "saves": sorted(combatant.saving_throws.keys()),
                    "attacks": [],
                    "features": [],
                }
            )

            if combatant.monster_template_id:
                monster = _load_monster_template_for_state(state, combatant.monster_template_id)
                if monster:
                    actors[-1]["attacks"] = _derive_monster_attack_options(monster)
                    actors[-1]["features"] = _derive_monster_feature_options(monster)

    return {
        "phase": state.campaign.phase,
        "state_version": state.state_version,
        "local_actions_allowed": state.pending_turn is None,
        "local_actions_block_reason": PENDING_TURN_ACTION_MESSAGE if state.pending_turn else "",
        "encounter": {
            "active": bool(state.encounter and state.encounter.active),
            "round_number": state.encounter.round_number if state.encounter else 0,
            "current_combatant_id": current_combatant.combatant_id if current_combatant else None,
            "current_actor_ref": current_actor_ref,
            "current_actor_name": current_combatant.name if current_combatant else "",
            "current_actor_side": current_combatant.side if current_combatant else "",
        },
        "actors": actors,
    }


def ensure_adventure_generation_option(state: GameState) -> bool:
    if state.campaign.phase != "adventure_selection" or state.campaign.selected_adventure_id:
        return False

    current_ids = [hook.adventure_id for hook in state.campaign.available_adventures]
    state.campaign.available_adventures = ensure_ai_generated_adventure_option(
        state.campaign.available_adventures
    )
    next_ids = [hook.adventure_id for hook in state.campaign.available_adventures]
    return next_ids != current_ids


def _roll_missing_initiative(logic, encounter):
    for combatant_id in encounter.initiative_order:
        combatant = encounter.combatants.get(combatant_id)
        if combatant and combatant.initiative is None:
            logic.roll_initiative(combatant.combatant_id)


def _normalize_reply_length_settings(min_chars: int = 0, max_chars: int = 0) -> tuple[int, int]:
    min_value = max(0, min(int(min_chars or 0), 3000))
    max_value = max(0, min(int(max_chars or 0), 4000))
    if min_value and max_value and min_value > max_value:
        raise ValueError("最小字数不能大于最大字数")
    return min_value, max_value


@app.get("/api/v1/health")
async def health_check():
    return health_payload()


@app.get("/api/v1/health/llm")
async def llm_health_check():
    return agent.probe_llm()


@app.get("/api/v1/llm/config")
async def get_llm_config():
    return agent.llm_runtime_payload()


@app.post("/api/v1/llm/config")
async def update_llm_config(req: LLMConfigUpdateRequest):
    try:
        payload = agent.upsert_llm_profile(
            profile_id=req.profile_id,
            profile_label=req.profile_label,
            provider=req.provider,
            model_name=req.model_name,
            reasoning_effort=req.reasoning_effort,
            base_url=req.base_url,
            api_key=req.api_key,
            cli_command=req.cli_command,
            cli_timeout_s=req.cli_timeout_s,
            activate=req.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新模型配置失败：{exc}") from exc
    return {"status": "updated", "llm": payload}


@app.post("/api/v1/llm/config/select")
async def select_llm_config(req: LLMProfileSelectRequest):
    try:
        payload = agent.select_llm_profile(req.profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"切换模型配置失败：{exc}") from exc
    return {"status": "selected", "llm": payload}


@app.get("/api/v1/config")
async def get_config():
    return {
        "rag_enabled": agent.rag_engine.is_ready(),
        "rag_status": agent.rag_engine.status_payload(),
        "chat_backend": agent.backend_name,
        "checkpoint_backend": agent.checkpoint_backend,
        "checkpoint_db_path": agent.checkpoint_db_path,
        "checkpoint_warning": agent.checkpoint_warning,
        "model_provider": agent.model_provider,
        "llm": agent.llm_runtime_payload(),
    }


@app.get("/api/v1/library/classes")
async def get_classes():
    return classes_payload()


@app.get("/api/v1/library/spells/{class_name}")
async def get_spells(class_name: str):
    return spells_payload(class_name)


@app.get("/api/v1/rules/character-builder")
async def get_character_builder_rules():
    return builder_payload()


@app.post("/api/v1/rules/ability-scores")
async def generate_ability_scores(req: AbilityScoreRequest):
    try:
        return ability_score_service.generate(req.method, req.scores or None)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/rag/search")
async def search_rules(req: RuleLookupRequest):
    snippets = library.localize_rag_snippets(agent.rag_engine.search(req.query, n_results=req.n_results))
    return {
        "query": req.query,
        "rag_enabled": agent.rag_engine.is_ready(),
        "rag_status": agent.rag_engine.status_payload(),
        "result_count": len(snippets),
        "snippets": snippets,
    }


@app.get("/api/v1/rag/status")
async def get_rag_status():
    agent.rag_engine.refresh()
    return agent.rag_engine.status_payload()


@app.get("/api/v1/characters")
async def list_characters():
    return characters_payload()


@app.post("/api/v1/characters")
async def create_character(char: Character):
    char = rule_catalog.apply_builder_defaults(char)
    errors = rule_catalog.validate_character(char)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "Character validation failed", "errors": errors})
    char_storage.save_character(char)
    return {"status": "saved", "character": char.to_summary().model_dump(mode="json")}


@app.post("/api/v1/characters/batch-delete")
async def batch_delete_characters(req: BatchDeleteRequest):
    return delete_characters_payload(req.ids)


@app.get("/api/v1/characters/{identifier}")
async def get_character(identifier: str):
    char = char_storage.load_character(identifier)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    return _add_display_fields(char.model_dump(mode="json"))


@app.post("/api/v1/characters/{identifier}/delete")
async def post_delete_character(identifier: str):
    payload = delete_characters_payload([identifier])
    if not payload["deleted"]:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"status": "deleted", "character_id": payload["deleted"][0]}


@app.delete("/api/v1/characters/{identifier}")
async def delete_character(identifier: str):
    payload = delete_characters_payload([identifier])
    if not payload["deleted"]:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"status": "deleted", "character_id": payload["deleted"][0]}


@app.get("/api/v1/monsters")
async def list_monsters():
    return monsters_payload()


@app.post("/api/v1/monsters")
async def create_monster(monster: MonsterTemplate):
    raise HTTPException(
        status_code=405,
        detail="Standard monster templates are read-only. Save game-specific monsters in the game state.",
    )


@app.get("/api/v1/monsters/{identifier}")
async def get_monster(identifier: str):
    monster = monster_storage.load_monster(identifier)
    if not monster:
        raise HTTPException(status_code=404, detail="Monster not found")
    return monster


@app.get("/api/v1/games")
async def list_games():
    return games_payload()


@app.post("/api/v1/games")
async def create_game(req: CreateGameRequest):
    if game_storage.load_game(req.game_id):
        raise HTTPException(status_code=400, detail="Game ID already exists")

    requested_refs = list(dict.fromkeys(req.character_ids + req.character_names))
    characters = []
    missing = []

    for ref in requested_refs:
        character = char_storage.load_character(ref)
        if character:
            characters.append(character)
        else:
            missing.append(ref)

    if missing:
        raise HTTPException(
            status_code=404,
            detail={"message": "Some characters were not found", "missing": missing},
        )

    new_state = agent.create_new_game(characters, game_id=req.game_id, title=req.title or req.game_id)
    new_state.campaign.available_adventures = generate_initial_adventures(characters)
    new_state.campaign.phase = "adventure_selection" if characters else "party_creation"
    game_storage.save_game(req.game_id, new_state)
    return {
        "status": "created",
        "game": new_state.to_summary().model_dump(mode="json"),
        "game_state": new_state,
        "action_options": action_options_payload(new_state),
    }


@app.post("/api/v1/games/batch-delete")
async def batch_delete_games(req: BatchDeleteRequest):
    return delete_games_payload(req.ids)


@app.get("/api/v1/games/{game_id}")
async def get_game_state(game_id: str) -> GameState:
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    if not state.pending_turn and ensure_adventure_generation_option(state):
        game_storage.save_game(game_id, state)
    return state


@app.post("/api/v1/games/{game_id}/delete")
async def post_delete_game(game_id: str):
    payload = delete_games_payload([game_id])
    if not payload["deleted"]:
        raise HTTPException(status_code=404, detail="Game not found")
    return {"status": "deleted", "game_id": payload["deleted"][0]}


@app.delete("/api/v1/games/{game_id}")
async def delete_game(game_id: str):
    payload = delete_games_payload([game_id])
    if not payload["deleted"]:
        raise HTTPException(status_code=404, detail="Game not found")
    return {"status": "deleted", "game_id": payload["deleted"][0]}


@app.get("/api/v1/games/{game_id}/monsters")
async def list_game_monsters(game_id: str):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return game_monsters_payload(state)


@app.get("/api/v1/games/{game_id}/monsters/{identifier}")
async def get_game_monster(game_id: str, identifier: str):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    monster = _load_monster_template_for_state(state, identifier)
    if not monster:
        raise HTTPException(status_code=404, detail="Monster not found")
    return monster


@app.get("/api/v1/games/{game_id}/action-options")
async def get_game_action_options(game_id: str):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return action_options_payload(state)


@app.post("/api/v1/games/{game_id}/reply-length")
async def update_game_reply_length(game_id: str, req: ReplyLengthSettingsRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        min_chars, max_chars = _normalize_reply_length_settings(req.min_chars, req.max_chars)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state.campaign.reply_min_chars = min_chars
    state.campaign.reply_max_chars = max_chars
    game_storage.save_game(game_id, state)
    return {
        "status": "updated",
        "reply_length": {
            "min_chars": min_chars,
            "max_chars": max_chars,
        },
        "game_state": state,
    }


@app.post("/api/v1/games/{game_id}/select-adventure")
async def select_adventure(game_id: str, req: SelectAdventureRequest):
    state = _load_mutable_game_or_404(game_id)
    base_snapshot = _rewind_safe_state(state)
    base_message_index = _visible_message_count(state)

    selected = None
    if is_ai_generated_adventure_id(req.adventure_id):
        try:
            selected = await asyncio.to_thread(agent.generate_adventure_hook, state)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=f"AI 冒险生成失败：{exc}") from exc

        state.campaign.available_adventures = [
            hook
            for hook in state.campaign.available_adventures
            if not is_ai_generated_adventure_id(hook.adventure_id)
            and hook.adventure_id != selected.adventure_id
        ]
        state.campaign.available_adventures.append(selected)
    else:
        for hook in state.campaign.available_adventures:
            if hook.adventure_id == req.adventure_id:
                selected = hook
                break

    if not selected:
        raise HTTPException(status_code=404, detail="Adventure option not found")

    state.campaign.selected_adventure_id = selected.adventure_id
    state.campaign.phase = "exploration"
    state.campaign.setup_complete = True
    state.campaign.current_chapter_number = 1
    state.campaign.current_chapter_title = f"第一章：{selected.title}"
    state.campaign.current_chapter_summary = selected.summary
    state.scene = "exploration"
    opening_scene = selected.opening_scene or selected.summary
    if is_model_generated_adventure_id(selected.adventure_id):
        opening_message = f"你们选择了《{selected.title}》。\n\n{opening_scene}"
    else:
        opening_message = (
            f"你们选择了《{selected.title}》。\n\n"
            f"{opening_scene}\n\n"
            "潮湿的空气贴着斗篷边缘，远处的路标在风里轻轻晃动。现在，轮到你决定第一步。"
        )
    opening_message = agent.clean_player_response(opening_message)
    action_suggestions = opening_action_suggestions(selected)
    state.adventure_log.append(f"选择冒险：{selected.title}")
    state.chat_history.append(
        ChatMessage(
            role="assistant",
            content=opening_message,
            action_suggestions=action_suggestions,
            action_suggestions_generated=True,
        )
    )
    state.timeline.append(
        SessionEvent(
            type="assistant_response",
            summary="DM response",
            content=opening_message,
            payload={"message": opening_message, "adventure_id": selected.adventure_id},
        )
    )
    game_storage.save_turn(game_id, state, expected_version=base_snapshot.state_version,
                           snapshots={base_message_index: base_snapshot}, prune_from=base_message_index)
    return {
        "status": "selected",
        "adventure": selected.model_dump(mode="json"),
        "action_suggestions": [item.model_dump(mode="json") for item in action_suggestions],
        "game_state": state,
    }


@app.post("/api/v1/games/{game_id}/encounters/start")
async def start_encounter(game_id: str, req: StartEncounterRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        logic = GameLogic(state)
        encounter = logic.start_encounter(req.enemy_names, enemy_hp=req.enemy_hp, enemy_ac=req.enemy_ac)
        if req.auto_roll_initiative:
            _roll_missing_initiative(logic, encounter)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, state)
    return {"status": "started", "encounter": encounter.model_dump(mode="json"), "game_state": state}


@app.post("/api/v1/games/{game_id}/encounters/add-enemy")
async def add_enemy_to_encounter(game_id: str, req: AddEnemyEncounterRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        logic = GameLogic(state)
        combatant = logic.add_enemy(
            name=req.name,
            hp_max=req.hp_max,
            ac=req.ac,
            initiative_bonus=req.initiative_bonus,
            side=req.side,
        )
        if req.auto_roll_initiative:
            logic.roll_initiative(combatant.combatant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, state)
    return {"status": "added", "combatant": combatant.model_dump(mode="json"), "game_state": state}


@app.post("/api/v1/games/{game_id}/encounters/spawn-template")
async def spawn_template_into_encounter(game_id: str, req: SpawnMonsterEncounterRequest):
    state = _load_mutable_game_or_404(game_id)
    monster = _load_monster_template_for_state(state, req.monster_id)
    if not monster:
        raise HTTPException(status_code=404, detail="Monster template not found")

    try:
        logic = GameLogic(state)
        spawned = logic.add_monster_from_template(
            monster=monster,
            quantity=req.quantity,
            custom_name=req.custom_name,
            hp_override=req.hp_override,
            side=req.side,
        )
        if req.auto_roll_initiative:
            for combatant in spawned:
                logic.roll_initiative(combatant.combatant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, state)
    return {
        "status": "spawned",
        "combatants": [combatant.model_dump(mode="json") for combatant in spawned],
        "game_state": state,
    }


@app.post("/api/v1/games/{game_id}/encounters/end")
async def end_encounter(game_id: str):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.end_encounter(state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return {
        "status": "ended",
        "summary": result["summary"],
        "encounter_summary": result["event"].payload,
        "encounter": result["game_state"].encounter.model_dump(mode="json") if result["game_state"].encounter else None,
        "event": result["event"],
        "tool_result": result["tool_result"],
        "state_delta": result["state_delta"],
        "game_state": result["game_state"],
    }


@app.post("/api/v1/games/{game_id}/encounters/remove-combatant")
async def remove_encounter_combatant(game_id: str, req: RemoveCombatantRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        logic = GameLogic(state)
        combatant = logic.remove_combatant(req.combatant_ref)
        if not combatant:
            raise ValueError("Combatant not found in the active encounter")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, state)
    return {"status": "removed", "combatant": combatant.model_dump(mode="json"), "game_state": state}


@app.post("/api/v1/games/{game_id}/encounters/set-initiative")
async def set_encounter_initiative(game_id: str, req: SetInitiativeRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        logic = GameLogic(state)
        combatant = logic.set_initiative(req.combatant_ref, req.initiative)
        if not combatant:
            raise ValueError("Combatant not found in the active encounter")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, state)
    return {"status": "set", "combatant": combatant.model_dump(mode="json"), "game_state": state}


@app.post("/api/v1/games/{game_id}/encounters/roll-initiative")
async def roll_encounter_initiative(game_id: str, req: RollInitiativeRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        logic = GameLogic(state)
        result = logic.roll_initiative(req.combatant_ref)
        if not result:
            raise ValueError("Combatant not found in the active encounter")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, state)
    return {
        "status": "rolled",
        "combatant": result["combatant"].model_dump(mode="json"),
        "expression": result["expression"],
        "detail": result["detail"],
        "game_state": state,
    }


@app.post("/api/v1/games/{game_id}/messages/{message_index}/delete")
async def delete_game_message(game_id: str, message_index: int):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    visible_messages = _visible_chat_messages(state)
    if message_index < 0 or message_index >= len(visible_messages):
        raise HTTPException(status_code=404, detail="Message not found")

    snapshot = game_storage.load_rewind_snapshot(game_id, message_index)
    if not snapshot:
        raise HTTPException(
            status_code=409,
            detail="This message does not have a rewind snapshot. Continue playing once, then new messages can be rewound.",
        )

    # 兼容修复前已经落盘、仍携带一次性 pending_turn 的 rewind snapshot。
    snapshot = _rewind_safe_state(snapshot)
    game_storage.save_turn(game_id, snapshot, expected_version=state.state_version,
                           snapshots={}, prune_from=message_index)
    return {
        "status": "rewound",
        "message_index": message_index,
        "game_state": snapshot,
        "action_suggestions": _action_suggestions_for_state(snapshot),
    }


@app.post("/api/v1/games/{game_id}/messages/{message_index}/rewrite")
async def rewrite_game_message(game_id: str, message_index: int, req: RewriteMessageRequest, stream: bool = False):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    visible_messages = _visible_chat_messages(state)
    if message_index < 0 or message_index >= len(visible_messages):
        raise HTTPException(status_code=404, detail="Message not found")
    if visible_messages[message_index].role != "user":
        raise HTTPException(status_code=400, detail="Only player messages can be rewritten")

    snapshot = game_storage.load_rewind_snapshot(game_id, message_index)
    if not snapshot:
        raise HTTPException(
            status_code=409,
            detail="This message does not have a rewind snapshot. Continue playing once, then new player messages can be rewritten.",
        )

    snapshot = _rewind_safe_state(snapshot)
    if stream:
        return _stream_turn_response(game_id, snapshot, message, expected_version=state.state_version, preserve_on_failure=True)
    try:
        result, _ = await _execute_turn_and_save(game_id, snapshot, message, expected_version=state.state_version, preserve_on_failure=True)
    except StateConflictError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DM agent request failed: {exc}") from exc
    return result


@app.post("/api/v1/games/{game_id}/messages/{message_index}/retry")
async def retry_game_message(game_id: str, message_index: int, stream: bool = False):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")

    visible_messages = _visible_chat_messages(state)
    if message_index < 0 or message_index >= len(visible_messages):
        raise HTTPException(status_code=404, detail="Message not found")
    if visible_messages[message_index].role != "assistant":
        raise HTTPException(status_code=400, detail="Only DM messages can be retried")

    player_message_index = message_index - 1
    if player_message_index < 0 or visible_messages[player_message_index].role != "user":
        raise HTTPException(status_code=409, detail="This DM message is not linked to a retryable player action")

    snapshot = game_storage.load_rewind_snapshot(game_id, player_message_index)
    if not snapshot:
        raise HTTPException(
            status_code=409,
            detail="This DM message does not have a rewind snapshot. Continue playing once, then new replies can be retried.",
        )

    # retry 是 rewrite 的无编辑快捷入口；服务端解析上一条玩家消息，避免浏览器猜测回滚索引。
    snapshot = _rewind_safe_state(snapshot)
    if stream:
        return _stream_turn_response(game_id, snapshot, visible_messages[player_message_index].content,
                                     expected_version=state.state_version, preserve_on_failure=True)
    try:
        result, _ = await _execute_turn_and_save(
            game_id,
            snapshot,
            visible_messages[player_message_index].content,
            expected_version=state.state_version,
            preserve_on_failure=True,
        )
    except StateConflictError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DM agent request failed: {exc}") from exc
    return result


@app.post("/api/v1/games/{game_id}/turns")
async def run_turn(game_id: str, req: ChatRequest):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")

    try:
        result, _ = await _execute_turn_and_save(game_id, state, req.message)
    except StateConflictError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DM agent request failed: {exc}") from exc

    return result


@app.post("/api/v1/games/{game_id}/turns/stream")
async def run_turn_stream(game_id: str, req: ChatRequest):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")

    return _stream_turn_response(game_id, state, req.message)


def _stream_turn_response(game_id: str, state: GameState, message: str, *, expected_version=None, preserve_on_failure=False):
    async def event_stream():
        initial_mode = "resume" if state.pending_turn else "start"
        yield _sse_event(
            "turn.started",
            {
                "game_id": game_id,
                "mode": initial_mode,
                "checkpoint_backend": agent.checkpoint_backend,
                "checkpoint_db_path": agent.checkpoint_db_path,
                "has_pending_turn": bool(state.pending_turn),
                "roll_records": [record.model_dump(mode="json") for record in (state.pending_turn.roll_records if state.pending_turn else [])],
            },
        )
        event_queue: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue()
        event_loop = asyncio.get_running_loop()

        def publish_live_event(event: str, data: Dict[str, Any]) -> None:
            event_loop.call_soon_threadsafe(event_queue.put_nowait, (event, data))

        turn_task = asyncio.create_task(
            _execute_turn_and_save(
                game_id,
                state,
                message,
                stream_event=publish_live_event,
                expected_version=expected_version, preserve_on_failure=preserve_on_failure,
            )
        )
        started_at = event_loop.time()
        last_activity = started_at
        emitted_node_count = 0
        while not turn_task.done() or not event_queue.empty():
            try:
                live_event, live_data = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if event_loop.time() - last_activity >= 10:
                    yield _sse_event("turn.heartbeat", {"elapsed_seconds": int(event_loop.time() - started_at)})
                    last_activity = event_loop.time()
                continue
            live_payload = {
                "game_id": game_id,
                "mode": initial_mode,
                **dict(live_data or {}),
            }
            if live_event == "turn.node":
                live_payload.setdefault("index", emitted_node_count)
                emitted_node_count += 1
            last_activity = event_loop.time()
            yield _sse_event(live_event, live_payload)

        try:
            result, mode = await turn_task
        except Exception as exc:
            yield _sse_event(
                "turn.error",
                {
                    "game_id": game_id,
                    "mode": initial_mode,
                    "detail": f"DM agent request failed: {exc}",
                },
            )
            yield _sse_event("turn.finished", {"status": "error", "game_id": game_id})
            return

        payload = _turn_result_payload(result)
        payload["game_id"] = game_id
        payload["mode"] = mode
        result_event = "turn.input_required" if result.turn_status == "input_required" else "turn.completed"
        if emitted_node_count == 0:
            for node_payload in _turn_node_event_payloads(result, game_id, mode):
                yield _sse_event("turn.node", node_payload)
        for detail_event, detail_payload in _turn_detail_event_payloads(result, game_id, mode):
            yield _sse_event(detail_event, detail_payload)
        yield _sse_event(result_event, payload)
        yield _sse_event(
            "turn.saved",
            {
                "game_id": game_id,
                "turn_status": result.turn_status,
                "updated_at": result.game_state.updated_at,
            },
        )
        yield _sse_event(
            "turn.finished",
            {
                "status": result.turn_status,
                "game_id": game_id,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _load_game_or_404(game_id: str) -> GameState:
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state


def _load_mutable_game_or_404(game_id: str) -> GameState:
    state = _load_game_or_404(game_id)
    if state.pending_turn:
        raise HTTPException(status_code=409, detail=PENDING_TURN_ACTION_MESSAGE)
    return state


@app.get("/api/v1/games/{game_id}/traces")
async def get_game_turn_traces(game_id: str, limit: int = 20):
    state = _load_game_or_404(game_id)
    normalized_limit = max(1, min(int(limit or 20), 100))
    traces = [trace.model_dump(mode="json") for trace in state.turn_traces[-normalized_limit:]]
    return {
        "game_id": game_id,
        "trace_count": len(state.turn_traces),
        "limit": normalized_limit,
        "traces": traces,
    }


@app.post("/api/v1/games/{game_id}/action-suggestions")
async def project_game_action_suggestions(game_id: str):
    async with _action_suggestion_lock(game_id):
        state = _load_game_or_404(game_id)
        stored_suggestions, generated = _latest_assistant_suggestion_status(state)
        if generated:
            return {
                "game_id": game_id,
                "turn_number": state.turn_number,
                "action_suggestions": stored_suggestions,
                "generated": True,
                "metadata": {"status": "cached"},
            }

        visible_history = _visible_chat_messages(state)
        assistant_message_index = next(
            (
                index
                for index in range(len(state.chat_history) - 1, -1, -1)
                if state.chat_history[index].kind != "tool_result"
                and state.chat_history[index].role == "assistant"
            ),
            -1,
        )
        response = state.chat_history[assistant_message_index].content if assistant_message_index >= 0 else ""
        user_input = next(
            (message.content for message in reversed(visible_history) if message.role == "user"),
            "",
        )
        if not response:
            return {
                "game_id": game_id,
                "turn_number": state.turn_number,
                "action_suggestions": [],
                "generated": False,
            }

        projected_turn_number = state.turn_number
        suggestions, metadata = await asyncio.to_thread(
            agent.project_action_suggestions,
            state,
            response,
            user_input,
        )

        # 投影在主回合提交后运行；迟到结果只能写回原回复，不能用旧快照覆盖已经推进的新回合。
        latest_state = _load_game_or_404(game_id)
        if _bind_action_suggestions_to_reply(latest_state, assistant_message_index, response, suggestions):
            game_storage.save_game(game_id, latest_state, projection_only=True)
            if latest_state.turn_number != projected_turn_number:
                latest_suggestions, latest_generated = _latest_assistant_suggestion_status(latest_state)
                return {
                    "game_id": game_id,
                    "turn_number": latest_state.turn_number,
                    "action_suggestions": latest_suggestions,
                    "generated": latest_generated,
                    "metadata": {**metadata, "status": "stale"},
                }
            return {
                "game_id": game_id,
                "turn_number": latest_state.turn_number,
                "action_suggestions": [item.model_dump(mode="json") for item in suggestions],
                "generated": True,
                "metadata": metadata,
            }

        latest_suggestions, latest_generated = _latest_assistant_suggestion_status(latest_state)
        return {
            "game_id": game_id,
            "turn_number": latest_state.turn_number,
            "action_suggestions": latest_suggestions,
            "generated": latest_generated,
            "metadata": {**metadata, "status": "stale"},
        }


# Deterministic local action routes complement the freer LangGraph text turns.
@app.post("/api/v1/games/{game_id}/actions/advance-turn")
async def advance_turn_action(game_id: str):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.advance_turn(state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/attack")
async def attack_action(game_id: str, req: AttackActionRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.attack_target(
            state=state,
            attacker_ref=req.attacker_ref,
            target_ref=req.target_ref,
            attack_bonus=req.attack_bonus,
            damage_expression=req.damage_expression,
            damage_type=req.damage_type,
            resolution_mode=req.resolution_mode,
            attack_name=req.attack_name,
            cast_id=req.cast_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/skill-check")
async def skill_check_action(game_id: str, req: SkillCheckActionRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.skill_check(
            state=state,
            actor_ref=req.actor_ref,
            skill_name=req.skill_name,
            dc=req.dc,
            modifier=req.modifier,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/saving-throw")
async def saving_throw_action(game_id: str, req: SavingThrowActionRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.saving_throw(
            state=state,
            target_ref=req.target_ref,
            save_name=req.save_name,
            dc=req.dc,
            modifier=req.modifier,
            source_ref=req.source_ref,
            spell_name=req.spell_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/cast-spell")
async def cast_spell_action(game_id: str, req: CastSpellActionRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.cast_spell(
            state=state,
            caster_ref=req.caster_ref,
            spell_name=req.spell_name,
            slot_level=req.slot_level,
            target_ref=req.target_ref,
            damage_type=req.damage_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/use-item")
async def use_item_action(game_id: str, req: UseItemActionRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.use_item(
            state=state,
            user_ref=req.user_ref,
            item_name=req.item_name,
            quantity=req.quantity,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/use-feature")
async def use_feature_action(game_id: str, req: UseFeatureActionRequest):
    state = _load_mutable_game_or_404(game_id)
    try:
        result = action_service.use_feature(
            state=state,
            actor_ref=req.actor_ref,
            feature_name=req.feature_name,
            action_cost=req.action_cost,
            resource_name=req.resource_name,
            resource_cost=req.resource_cost,
            reason=req.reason,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=23333)
