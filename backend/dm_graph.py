"""LangGraph workflow for deterministic DM turn orchestration."""

import json
import os
import re
import sqlite3
from uuid import uuid4
from typing import Any, Dict, List, Optional, TypedDict

from agent_tools import AgentToolExecution, AgentToolService, merge_patch
from campaign_memory import compile_campaign_memory
from game_logic import GameLogic
from library import Library
from models import (
    ChatMessage,
    GameState,
    PendingTurnState,
    SessionEvent,
    ToolResult,
    TurnIntent,
    TurnResult,
    TurnTrace,
    ValidationIssue,
)
from prompts import build_dm_instruction
from tool_registry import ToolGuardrailResult, ToolRegistry

try:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt
except ImportError:
    ChatOpenAI = None
    Command = None
    END = None
    HumanMessage = None
    InMemorySaver = None
    SqliteSaver = None
    START = None
    StateGraph = None
    SystemMessage = None
    ToolMessage = None
    interrupt = None

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:
    SqliteSaver = None


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
        "name": "use_item",
        "description": "Use and consume an item from a character inventory, reducing quantity only when available.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_ref": {"type": "string"},
                "item_name": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["user_ref", "item_name"],
        },
    },
    {
        "name": "use_feature",
        "description": "Record a class feature, monster feature, trait, bonus action, or reaction use, consuming the chosen turn slot and optional character resource.",
        "parameters": {
            "type": "object",
            "properties": {
                "actor_ref": {"type": "string"},
                "feature_name": {"type": "string"},
                "action_cost": {
                    "type": "string",
                    "enum": ["action", "bonus_action", "reaction", "free"],
                    "default": "action",
                },
                "resource_name": {"type": "string", "default": ""},
                "resource_cost": {"type": "integer", "default": 0},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["actor_ref", "feature_name"],
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
        "description": "Persist a game-scoped monster template designed during play. Standard monster templates are read-only.",
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
        "description": "Spawn one or more combatants from a standard or game-scoped monster template.",
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


RULE_QUESTION_TERMS = [
    "?",
    "？",
    "如何",
    "怎么",
    "怎样",
    "是否",
    "能不能",
    "可以吗",
    "是什么",
    "什么意思",
    "规则",
    "解释",
    "说明",
    "rule",
    "rules",
]

RULE_TRIGGER_TERMS = [
    "优势",
    "劣势",
    "豁免",
    "检定",
    "技能",
    "攻击",
    "伤害",
    "命中",
    "先攻",
    "法术",
    "法术位",
    "戏法",
    "专注",
    "条件",
    "状态",
    "附赠动作",
    "反应",
    "动作",
    "移动",
    "借机攻击",
    "掩护",
    "长休",
    "短休",
    "死亡豁免",
    "隐匿",
    "潜行",
    "感知",
    "调查",
    "擒抱",
    "推撞",
    "倒地",
    "武器",
    "护甲",
    "熟练",
    "职业",
    "专长",
    "背景",
    "物种",
    "attack",
    "damage",
    "save",
    "check",
    "spell",
    "slot",
    "initiative",
    "condition",
    "concentration",
    "advantage",
    "disadvantage",
    "grapple",
    "shove",
    "reaction",
    "bonus action",
    "opportunity attack",
    "armor",
    "weapon",
    "proficiency",
]

COMBAT_RULE_TERMS = [
    "攻击",
    "伤害",
    "命中",
    "豁免",
    "法术",
    "法术位",
    "先攻",
    "回合",
    "附赠动作",
    "反应",
    "借机攻击",
    "擒抱",
    "推撞",
    "倒地",
    "优势",
    "劣势",
    "attack",
    "damage",
    "save",
    "spell",
    "initiative",
    "turn",
    "reaction",
    "bonus action",
    "opportunity",
    "grapple",
    "shove",
]

SCENE_LABELS = {
    "setup": "准备",
    "exploration": "探索",
    "combat": "战斗",
    "downtime": "休整",
    "adventure_selection": "冒险选择",
    "character_creation": "角色创建",
    "party_creation": "队伍创建",
    "level_up": "升级",
}

BASE_TOOL_NAMES = [
    "lookup_rules",
    "roll_dice",
    "adjust_hp",
    "add_status",
    "remove_status",
    "append_adventure_log",
    "add_inventory_item",
    "use_item",
    "use_feature",
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

COMBAT_TOOL_NAMES = [
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

PHASE_POLICIES: Dict[str, Dict[str, Any]] = {
    "party_creation": {
        "scene": "setup",
        "tools": ["lookup_rules"],
        "objective": "Help the player finish assembling the party before active play begins.",
        "constraints": [
            "Do not narrate live exploration or combat before at least one playable character exists.",
            "Keep the reply focused on missing party setup decisions.",
        ],
        "blockers": [
            "No party members are currently loaded into the game state.",
        ],
    },
    "character_creation": {
        "scene": "setup",
        "tools": ["lookup_rules"],
        "objective": "Help resolve remaining character build choices before starting the campaign.",
        "constraints": [
            "Do not start scenes, encounters, or chapter progression while build choices remain unresolved.",
            "Answer build questions with rules support instead of improvising sheet changes in prose.",
        ],
        "blockers": [
            "The active workflow is still in character setup.",
        ],
    },
    "adventure_selection": {
        "scene": "setup",
        "tools": ["lookup_rules", "append_adventure_log"],
        "objective": "Help the player compare the offered adventures and choose one hook.",
        "constraints": [
            "Do not begin active exploration or combat until an adventure hook is selected.",
            "Keep the turn centered on clarifying the available hooks, stakes, and tone.",
        ],
        "blockers": [
            "No selected adventure is locked in yet.",
        ],
    },
    "exploration": {
        "scene": "exploration",
        "tools": [*BASE_TOOL_NAMES, "start_encounter"],
        "objective": "Resolve exploration, conversation, investigation, travel, and scene transitions.",
        "constraints": [
            "If combat begins, call start_encounter before narrating initiative-based actions.",
            "Persist important discoveries, clues, and chapter progress with tools instead of leaving them only in prose.",
        ],
        "blockers": [],
    },
    "combat": {
        "scene": "combat",
        "tools": [*BASE_TOOL_NAMES, *COMBAT_TOOL_NAMES],
        "objective": "Resolve the current encounter one combatant turn at a time with authoritative tool calls.",
        "constraints": [
            "Only the current combatant may take an action until advance_turn changes the acting creature.",
            "Do not leave combat state through prose alone; use encounter tools to mutate it.",
        ],
        "blockers": [],
    },
    "downtime": {
        "scene": "downtime",
        "tools": [*BASE_TOOL_NAMES, "start_encounter"],
        "objective": "Handle recovery, shopping, planning, travel prep, and between-chapter scenes.",
        "constraints": [
            "Keep the pace lower-stakes unless the fiction explicitly escalates into a new encounter.",
            "Record durable rewards, milestones, and chapter updates with tools.",
        ],
        "blockers": [],
    },
    "level_up": {
        "scene": "level_up",
        "tools": [
            "lookup_rules",
            "append_adventure_log",
            "record_major_experience",
            "record_chapter_progress",
            "set_scene",
            "set_active_character",
        ],
        "objective": "Resolve level-up decisions and milestone bookkeeping before returning to play.",
        "constraints": [
            "Do not start encounters while the workflow is explicitly in level-up handling.",
            "Keep the turn focused on progression choices and persistent rewards.",
        ],
        "blockers": [],
    },
}

ACTION_RESOLUTION_TERMS = [
    "search",
    "investigate",
    "inspect",
    "check",
    "roll",
    "persuade",
    "deceive",
    "intimidate",
    "stealth",
    "perception",
    "insight",
    "heal",
    "drink",
    "cast",
    "attack",
    "rest",
    "\u68c0\u67e5",
    "\u8c03\u67e5",
    "\u89c2\u5bdf",
    "\u5bfb\u627e",
    "\u627e",
    "\u63a2\u67e5",
    "\u4fa6\u67e5",
    "\u67e5\u770b",
    "\u67e5\u9a8c",
    "\u8ffd\u8e2a",
    "\u8fa8\u8ba4",
    "\u4ea4\u6d89",
    "\u611f\u77e5",
    "\u6f5c\u884c",
    "\u8bf4\u670d",
    "\u6b3a\u7792",
    "\u5a01\u5413",
    "\u6d1e\u6089",
    "\u641c\u7d22",
    "\u7ffb\u627e",
    "\u6295\u9ab0",
    "\u68c0\u5b9a",
    "\u8c41\u514d",
    "\u65bd\u6cd5",
    "\u65bd\u653e",
    "\u91ca\u653e",
    "\u653b\u51fb",
    "\u4f7f\u7528",
    "\u559d",
    "\u4f11\u606f",
    "\u6cbb\u7597",
    "\u559d\u836f",
]

TOOL_RESULT_ALIASES: Dict[str, set[str]] = {
    "lookup_rules": {"lookup_rules", "knowledge.lookup_rules"},
    "roll_dice": {"roll_dice", "dice.roll"},
    "adjust_hp": {"adjust_hp", "target.adjust_hp"},
    "add_status": {"add_status", "target.add_status"},
    "remove_status": {"remove_status", "target.remove_status"},
    "append_adventure_log": {"append_adventure_log", "log.append"},
    "add_inventory_item": {"add_inventory_item", "character.add_inventory_item"},
    "use_item": {"use_item", "inventory.use_item"},
    "use_feature": {"use_feature", "feature.use"},
    "record_evidence": {"record_evidence", "story.record_evidence"},
    "record_search_outcome": {"record_search_outcome", "story.record_search_outcome"},
    "record_major_experience": {"record_major_experience", "character.record_major_experience"},
    "record_chapter_progress": {"record_chapter_progress", "campaign.record_chapter_progress"},
    "set_defeat_state": {"set_defeat_state", "combat.set_defeat_state"},
    "set_scene": {"set_scene", "scene.set"},
    "set_active_character": {"set_active_character", "character.set_active"},
    "start_encounter": {"start_encounter", "encounter.start"},
    "add_enemy": {"add_enemy", "encounter.add_enemy"},
    "save_monster_template": {"save_monster_template", "monster.save_template", "monster.save_game_template"},
    "spawn_monster_from_template": {"spawn_monster_from_template", "monster.spawn_from_template"},
    "attack_target": {"attack_target", "combat.attack_target"},
    "roll_skill_check": {"roll_skill_check", "check.skill"},
    "roll_saving_throw": {"roll_saving_throw", "check.saving_throw"},
    "cast_spell": {"cast_spell", "magic.cast_spell"},
    "set_initiative": {"set_initiative", "encounter.set_initiative"},
    "roll_initiative": {"roll_initiative", "encounter.roll_initiative"},
    "advance_turn": {"advance_turn", "encounter.advance_turn"},
    "end_encounter": {"end_encounter", "encounter.end"},
}


TURN_PROFILE_POLICIES: Dict[str, Dict[str, Any]] = {
    "setup_guidance": {
        "tool_round_limit": 1,
        "tool_subset": [],
        "guidance": "Keep the turn short and decision-oriented. Do not over-narrate; help the player finish setup cleanly.",
    },
    "conversation": {
        "tool_round_limit": 1,
        "tool_subset": [
            "lookup_rules",
            "append_adventure_log",
            "add_inventory_item",
            "record_evidence",
            "record_search_outcome",
            "record_chapter_progress",
            "set_scene",
            "set_active_character",
        ],
        "guidance": "Prefer a direct in-world reply. Only call tools if the player clearly creates a durable clue, loot, chapter update, or scene transition.",
    },
    "rules_reference": {
        "tool_round_limit": 1,
        "tool_subset": ["lookup_rules"],
        "guidance": "Answer the rules question clearly and avoid unrelated state mutations or extra tool chatter.",
    },
    "action_resolution": {
        "tool_round_limit": 2,
        "tool_subset": [],
        "guidance": "Resolve the attempted action with the minimum tool sequence needed for correctness, then narrate the outcome cleanly.",
    },
    "combat_resolution": {
        "tool_round_limit": 3,
        "tool_subset": [],
        "guidance": "Keep combat crisp. Resolve only the current acting creature's turn and avoid side detours or extra tool loops.",
    },
}


class DMGraphState(TypedDict, total=False):
    game_state: Dict[str, Any]
    initial_game_state: Dict[str, Any]
    user_input: str
    thread_id: str
    phase: str
    scene: str
    phase_objective: str
    phase_constraints: List[str]
    phase_blockers: List[str]
    messages: List[Any]
    state_summary: str
    recent_history: str
    campaign_memory: str
    instruction: str
    rag_snippets: List[Dict[str, Any]]
    rag_context: str
    rag_queries: List[str]
    rag_intent: str
    rag_reason: str
    rag_metadata: Dict[str, Any]
    input_warnings: List[str]
    turn_intent: Dict[str, Any]
    turn_profile: str
    turn_profile_reason: str
    turn_guidance: str
    turn_expectation: str
    suggested_tools: List[str]
    turn_checklist: List[str]
    allowed_tools: List[str]
    tool_round_limit: int
    tool_call_rounds: int
    turn_status: str
    pending_input: Dict[str, Any]
    final_response: str
    tool_results: List[Dict[str, Any]]
    state_delta: Dict[str, Any]
    timeline_append: List[Dict[str, Any]]
    history_append: List[Dict[str, Any]]
    validation_notes: List[str]
    validation_issues: List[Dict[str, Any]]
    node_traces: List[Dict[str, Any]]


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
        checkpoint_mode: str = "",
        checkpoint_db_path: str = "",
    ):
        self.rag_engine = rag_engine
        self.tool_service = tool_service
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.enable_model = enable_model
        self.max_tool_rounds = max_tool_rounds
        self.library = Library()
        self.tool_registry = ToolRegistry.from_schemas(LANGGRAPH_TOOL_SCHEMAS)
        self._graph = None
        self._model = None
        self._checkpoint_conn: Optional[sqlite3.Connection] = None
        self._checkpoint_mode = checkpoint_mode
        self._checkpoint_db_path_override = checkpoint_db_path
        self.checkpoint_backend = "none"
        self.checkpoint_db_path = ""
        self.checkpoint_warning = ""
        self._checkpointer = self._create_checkpointer()

    @property
    def is_available(self) -> bool:
        return StateGraph is not None

    def _require_langgraph(self) -> None:
        if not self.is_available:
            raise LangGraphUnavailableError(
                "LangGraph is not installed. Install backend requirements before enabling the LangGraph runner."
            )

    @staticmethod
    def _default_checkpoint_db_path() -> str:
        return os.path.join(os.path.dirname(__file__), "Game", "langgraph_checkpoints.sqlite")

    def _resolved_checkpoint_mode(self) -> str:
        mode = self._checkpoint_mode or os.getenv("LANGGRAPH_CHECKPOINT_MODE", "sqlite")
        normalized = str(mode or "").strip().lower()
        if normalized in {"", "default"}:
            return "sqlite"
        if normalized in {"off", "none", "disabled"}:
            return "none"
        if normalized in {"memory", "sqlite"}:
            return normalized
        return "sqlite"

    def _resolved_checkpoint_db_path(self) -> str:
        configured = self._checkpoint_db_path_override or os.getenv("LANGGRAPH_CHECKPOINT_DB_PATH", "")
        path = str(configured or "").strip()
        if not path:
            path = self._default_checkpoint_db_path()
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(__file__), path)
        return os.path.normpath(path)

    def _fallback_memory_checkpointer(self, warning: str = ""):
        self.checkpoint_warning = warning
        if InMemorySaver is None:
            self.checkpoint_backend = "none"
            return None
        self.checkpoint_backend = "memory"
        self.checkpoint_db_path = ""
        return InMemorySaver()

    def _create_checkpointer(self):
        mode = self._resolved_checkpoint_mode()
        if mode == "none":
            self.checkpoint_backend = "none"
            self.checkpoint_db_path = ""
            return None
        if mode == "memory":
            return self._fallback_memory_checkpointer()

        if SqliteSaver is None:
            return self._fallback_memory_checkpointer(
                "langgraph-checkpoint-sqlite is not installed; falling back to in-memory checkpoints."
            )

        db_path = self._resolved_checkpoint_db_path()
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            self._checkpoint_conn = sqlite3.connect(db_path, check_same_thread=False)
            saver = SqliteSaver(self._checkpoint_conn)
            saver.setup()
            self.checkpoint_backend = "sqlite"
            self.checkpoint_db_path = db_path
            self.checkpoint_warning = ""
            return saver
        except Exception as exc:
            if self._checkpoint_conn is not None:
                try:
                    self._checkpoint_conn.close()
                except Exception:
                    pass
                self._checkpoint_conn = None
            return self._fallback_memory_checkpointer(
                f"SQLite checkpointer initialization failed ({exc}); falling back to in-memory checkpoints."
            )

    def close(self) -> None:
        if self._checkpoint_conn is not None:
            try:
                self._checkpoint_conn.close()
            finally:
                self._checkpoint_conn = None

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
        tool_schemas = self.tool_registry.schemas_for(allowed_tools)
        if not tool_schemas:
            return model
        return model.bind_tools(tool_schemas)

    @staticmethod
    def _phase_policy(phase: str) -> Dict[str, Any]:
        normalized = str(phase or "").strip().lower()
        return dict(PHASE_POLICIES.get(normalized, PHASE_POLICIES["exploration"]))

    @classmethod
    def _derive_phase(cls, state: GameState) -> str:
        current_phase = str(state.campaign.phase or "").strip().lower()
        current_scene = str(state.scene or "").strip().lower()
        selected_adventure = state.campaign.selected_adventure()

        if state.encounter and state.encounter.active:
            return "combat"
        if not state.characters:
            return "party_creation"
        if current_phase == "character_creation":
            return "character_creation"
        if current_phase in {"level_up", "downtime"}:
            return current_phase
        if current_scene in {"level_up", "downtime"}:
            return current_scene
        if (
            not state.campaign.setup_complete
            or not state.campaign.selected_adventure_id
            or selected_adventure is None
        ):
            return "adventure_selection"
        return "exploration"

    @staticmethod
    def _expected_scene_for_phase(phase: str, fallback_scene: str) -> str:
        policy = PHASE_POLICIES.get(phase, {})
        expected = str(policy.get("scene") or "").strip().lower()
        return expected or str(fallback_scene or "setup").strip().lower() or "setup"

    @classmethod
    def _phase_blockers(cls, state: GameState, phase: str) -> List[str]:
        blockers = list(cls._phase_policy(phase).get("blockers", []))
        if phase == "adventure_selection" and not state.campaign.available_adventures:
            blockers.append("No adventure hooks are currently loaded.")
        if phase == "combat":
            encounter = state.encounter
            if not encounter or not encounter.active:
                blockers.append("No active encounter is available.")
            elif encounter.turn_order_started and not encounter.current_combatant_id:
                blockers.append("Initiative exists but there is no current combatant.")
            elif not encounter.turn_order_started:
                blockers.append("Initiative order is not fully ready yet.")
        return cls._unique_texts(blockers, limit=6)

    @classmethod
    def _normalize_phase_state(
        cls, state: GameState
    ) -> tuple[str, str, List[str], Dict[str, Any], Dict[str, Any]]:
        phase = cls._derive_phase(state)
        expected_scene = cls._expected_scene_for_phase(phase, state.scene)
        notes: List[str] = []
        patch: Dict[str, Any] = {}

        if state.campaign.phase != phase:
            state.campaign.phase = phase
            patch.setdefault("campaign", {})["phase"] = phase
            notes.append(f"Normalized campaign phase to {phase}.")
        if state.scene != expected_scene:
            state.scene = expected_scene
            patch["scene"] = expected_scene
            notes.append(f"Normalized scene to {expected_scene} for phase {phase}.")

        policy = cls._phase_policy(phase)
        return phase, expected_scene, notes, patch, policy

    @classmethod
    def _allowed_tool_names(cls, state: GameState, phase: str = "") -> List[str]:
        resolved_phase = str(phase or "").strip().lower() or cls._derive_phase(state)
        policy = cls._phase_policy(resolved_phase)
        return list(policy.get("tools", []))

    @staticmethod
    def _new_thread_id(state: GameState) -> str:
        game_id = state.game_id or "game"
        next_turn = int(state.turn_number or 0) + 1
        return f"{game_id}:turn:{next_turn}:{uuid4().hex}"

    @staticmethod
    def _graph_config(thread_id: str) -> Dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _is_generic_followup(text: str) -> bool:
        normalized = " ".join((text or "").split()).strip().lower()
        if not normalized:
            return True
        generic_inputs = {
            "continue",
            "go on",
            "next",
            "ok",
            "okay",
            "sure",
            "start",
            "begin",
            "do it",
            "continue on",
            "继续",
            "继续吧",
            "开始",
            "下一步",
            "下一个",
            "就这样",
            "那就这样",
            "好的",
            "好",
            "行",
            "嗯",
        }
        return normalized in generic_inputs

    @classmethod
    def _build_required_input_request(cls, state: GameState, user_input: str, phase: str) -> Optional[Dict[str, Any]]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return {
                "kind": "clarification",
                "phase": phase,
                "prompt": "请明确说明你希望 DM 现在处理什么，或直接描述角色动作。",
                "details": {"reason": "empty_input"},
            }

        if phase == "adventure_selection" and cls._is_generic_followup(normalized_input):
            options = [
                {"adventure_id": hook.adventure_id, "title": hook.title}
                for hook in (state.campaign.available_adventures or [])[:4]
            ]
            return {
                "kind": "choice",
                "phase": phase,
                "prompt": "请先明确选择本章要跑的冒险。你可以回复冒险标题，或直接说“选第 2 个”。",
                "details": {"reason": "adventure_choice_required", "options": options},
            }

        if phase == "combat" and cls._is_generic_followup(normalized_input):
            current = state.encounter.get_current_combatant() if state.encounter else None
            return {
                "kind": "clarification",
                "phase": phase,
                "prompt": "请明确说明这回合要执行的动作，例如攻击哪个目标、施放什么法术，或声明闪避/脱离/准备动作。",
                "details": {
                    "reason": "combat_action_required",
                    "current_combatant": current.name if current else "",
                },
            }

        return None

    @staticmethod
    def _coerce_resume_input(value: Any) -> str:
        if isinstance(value, dict):
            text = value.get("message") or value.get("input") or value.get("content")
            return str(text).strip() if text else ""
        return str(value or "").strip()

    @staticmethod
    def _turn_profile_policy(profile: str) -> Dict[str, Any]:
        normalized = str(profile or "").strip().lower()
        return dict(TURN_PROFILE_POLICIES.get(normalized, TURN_PROFILE_POLICIES["action_resolution"]))

    @classmethod
    def _profile_allowed_tools(cls, base_tools: List[str], turn_profile: str) -> List[str]:
        policy = cls._turn_profile_policy(turn_profile)
        subset = list(policy.get("tool_subset", []))
        if not subset:
            return list(base_tools)
        base_lookup = set(base_tools)
        return [tool_name for tool_name in subset if tool_name in base_lookup]

    @staticmethod
    def _prioritize_tools(allowed_tools: List[str], suggested_tools: List[str]) -> List[str]:
        if not suggested_tools:
            return list(allowed_tools)
        ordered: List[str] = []
        seen = set()
        for tool_name in [*suggested_tools, *allowed_tools]:
            if tool_name in seen or tool_name not in allowed_tools:
                continue
            seen.add(tool_name)
            ordered.append(tool_name)
        return ordered

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        normalized = " ".join((text or "").split()).strip()
        if not normalized:
            return False
        lowered = normalized.casefold()
        question_markers = [
            "?",
            "\uff1f",
            "how",
            "what",
            "when",
            "why",
            "can i",
            "can we",
            "do i",
            "do we",
            "does",
            "\u5982\u4f55",
            "\u600e\u4e48",
            "\u600e\u6837",
            "\u662f\u5426",
            "\u80fd\u4e0d\u80fd",
            "\u53ef\u4ee5\u5417",
            "\u4e3a\u4ec0\u4e48",
            "\u662f\u4ec0\u4e48",
        ]
        return any(marker in lowered for marker in question_markers)

    @classmethod
    def _action_terms_for_input(cls, user_input: str) -> List[str]:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return []
        return cls._unique_texts(
            [
                marker
                for marker in ACTION_RESOLUTION_TERMS
                if str(marker or "").strip() and str(marker).casefold() in lowered
            ],
            limit=6,
        )

    def _suggested_resolution_tools(self, state: GameState, user_input: str, phase: str) -> List[str]:
        normalized = " ".join((user_input or "").split()).strip()
        if not normalized:
            return []

        lowered = normalized.casefold()
        suggestions: List[str] = self._explicit_tool_names_in_input(normalized)
        matched_spells = self._matched_spell_names(state, normalized)

        if matched_spells or any(term in lowered for term in ["cast", "\u65bd\u6cd5", "\u6cd5\u672f"]):
            suggestions.append("cast_spell")
        if any(
            term in lowered
            for term in [
                "attack",
                "strike",
                "shoot",
                "\u653b\u51fb",
                "\u5c04\u51fb",
                "\u6325\u780d",
            ]
        ):
            suggestions.append("attack_target")
        if any(
            term in lowered
            for term in [
                "save",
                "saving throw",
                "\u8c41\u514d",
            ]
        ):
            suggestions.append("roll_saving_throw")
        if any(
            term in lowered
            for term in [
                "perception",
                "investigation",
                "stealth",
                "insight",
                "persuasion",
                "deception",
                "\u611f\u77e5",
                "\u8c03\u67e5",
                "\u6f5c\u884c",
                "\u6d1e\u6089",
                "\u8bf4\u670d",
                "\u6b3a\u7792",
                "\u68c0\u5b9a",
            ]
        ):
            suggestions.append("roll_skill_check")
        if any(
            term in lowered
            for term in [
                "use",
                "drink",
                "consume",
                "heal",
                "healing",
                "potion",
                "item",
                "\u4f7f\u7528",
                "\u6d88\u8017",
                "\u559d",
                "\u559d\u836f",
                "\u836f\u6c34",
                "\u7269\u54c1",
            ]
        ):
            suggestions.append("use_item")
        if any(
            term in lowered
            for term in [
                "feature",
                "ability",
                "trait",
                "class feature",
                "monster feature",
                "bonus action",
                "reaction",
                "second wind",
                "\u7279\u6027",
                "\u80fd\u529b",
                "\u804c\u4e1a\u7279\u6027",
                "\u602a\u7269\u7279\u6027",
                "\u9644\u8d60\u52a8\u4f5c",
                "\u9644\u52a0\u52a8\u4f5c",
                "\u53cd\u5e94",
                "\u52a8\u4f5c\u6fc0\u6d8c",
                "\u56de\u6c14",
            ]
        ):
            suggestions.append("use_feature")
        if any(
            term in lowered
            for term in [
                "heal",
                "healing",
                "damage",
                "hurt",
                "potion",
                "\u6cbb\u7597",
                "\u4f24\u5bb3",
                "\u559d\u836f",
                "\u836f\u6c34",
            ]
        ):
            suggestions.append("adjust_hp")
        if phase == "combat" and any(
            term in lowered
            for term in [
                "end turn",
                "next turn",
                "\u7ed3\u675f\u56de\u5408",
                "\u4e0b\u4e00\u56de\u5408",
                "\u8f6e\u5230",
            ]
        ):
            suggestions.append("advance_turn")
        if self._chapter_completion_requested(normalized) or any(
            term in lowered
            for term in [
                "record chapter",
                "chapter progress",
                "\u8bb0\u5f55\u7ae0\u8282",
                "\u7ae0\u8282\u8fdb\u5ea6",
                "\u7ae0\u8282\u5df2\u8bb0\u5f55",
            ]
        ):
            suggestions.append("record_chapter_progress")

        return self._unique_texts(suggestions, limit=4)

    @staticmethod
    def _explicit_tool_names_in_input(user_input: str) -> List[str]:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return []

        matches: List[str] = []
        for schema in LANGGRAPH_TOOL_SCHEMAS:
            tool_name = str(schema.get("name") or "").strip()
            if tool_name and tool_name.casefold() in lowered:
                matches.append(tool_name)
        return DMGraphRunner._unique_texts(matches, limit=6)

    @staticmethod
    def _intent_risk_level(phase: str, turn_type: str, suggested_tools: List[str]) -> str:
        high_risk_tools = {"end_encounter", "set_defeat_state", "record_chapter_progress"}
        medium_risk_tools = {
            "adjust_hp",
            "add_status",
            "remove_status",
            "add_inventory_item",
            "use_item",
            "record_evidence",
            "record_search_outcome",
            "record_major_experience",
            "start_encounter",
            "attack_target",
            "cast_spell",
            "roll_saving_throw",
        }
        tool_set = set(suggested_tools or [])
        if tool_set & high_risk_tools:
            return "high"
        if phase == "combat" or turn_type == "combat_resolution" or tool_set & medium_risk_tools:
            return "medium"
        return "low"

    def _plan_turn_intent(self, state: GameState, user_input: str, phase: str, scene: str = "") -> TurnIntent:
        normalized_input = " ".join((user_input or "").split()).strip()
        phase_name = str(phase or "").strip().lower() or self._derive_phase(state)
        scene_name = str(scene or state.scene or "").strip().lower()
        rule_intent = self._classify_rule_intent(state, normalized_input)
        action_terms = self._action_terms_for_input(normalized_input)
        question_shape = self._looks_like_question(normalized_input)

        if phase_name in {"party_creation", "character_creation", "adventure_selection", "level_up"}:
            turn_type = "setup_guidance"
            reason = f"phase {phase_name} is setup-heavy and benefits from short decision-oriented replies"
        elif not normalized_input and phase_name == "combat":
            turn_type = "combat_resolution"
            reason = "empty input during an active encounter should still preserve combat-focused tool access"
        elif not normalized_input:
            turn_type = "conversation"
            reason = "empty or whitespace-only player input"
        elif phase_name == "combat" and action_terms and not question_shape:
            turn_type = "combat_resolution"
            reason = "active encounter action should resolve directly instead of detouring into a rules-only turn"
        elif rule_intent.get("should_retrieve") and action_terms and not question_shape:
            turn_type = "action_resolution"
            reason = "the turn references rules-sensitive mechanics, but the player is attempting a concrete action"
        elif phase_name == "combat" and not rule_intent.get("should_retrieve"):
            turn_type = "combat_resolution"
            reason = "active encounter turn should stay focused on concrete combat resolution"
        elif rule_intent.get("should_retrieve"):
            turn_type = "rules_reference"
            reason = str(rule_intent.get("reason", "rules-sensitive question or resolution"))
        elif phase_name == "combat":
            turn_type = "combat_resolution"
            reason = "active encounter turn should stay focused on concrete combat resolution"
        elif action_terms:
            turn_type = "action_resolution"
            reason = "player attempted an action that likely needs adjudication or tracked consequences"
        elif question_shape:
            turn_type = "conversation"
            reason = "player asked an in-world or social question without obvious rules load"
        else:
            turn_type = "conversation"
            reason = "player input reads like low-friction narrative conversation"

        suggested_tools = self._suggested_resolution_tools(state, normalized_input, phase_name)
        if turn_type == "rules_reference":
            suggested_tools = ["lookup_rules"]
        suggested_tools = self._unique_texts(suggested_tools, limit=4)
        risk_level = self._intent_risk_level(phase_name, turn_type, suggested_tools)

        return TurnIntent(
            turn_type=turn_type,
            reason=reason,
            phase=phase_name,
            scene=scene_name,
            risk_level=risk_level,
            needs_rules=bool(rule_intent.get("should_retrieve")),
            rag_intent=str(rule_intent.get("intent") or "none"),
            rag_reason=str(rule_intent.get("reason") or ""),
            focus_terms=list(rule_intent.get("focus_terms", [])),
            action_terms=action_terms,
            matched_spells=list(rule_intent.get("matched_spells", [])),
            suggested_tools=suggested_tools,
            requires_confirmation=risk_level == "high",
        )

    def _build_turn_advice(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        turn_profile: str,
        allowed_tools: List[str],
        turn_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile_name = str(turn_profile or "").strip().lower()
        raw_suggested_tools = list(
            (turn_intent or {}).get("suggested_tools")
            or self._suggested_resolution_tools(state, user_input, phase)
        )
        suggested_tools = [
            tool_name
            for tool_name in raw_suggested_tools
            if tool_name in allowed_tools
        ]

        expectation = "Respond naturally and only escalate into tools when needed."
        checklist: List[str] = []
        if profile_name == "conversation":
            expectation = "Direct in-world reply first; skip tools unless something durable or stateful is actually created."
            checklist = [
                "Do not turn a simple social beat into a mechanical resolution unless the player clearly pushes for one.",
            ]
        elif profile_name == "rules_reference":
            expectation = "Answer the rules question in one pass, ideally with a single lookup if needed."
            checklist = [
                "Keep the answer scoped to the asked rule.",
                "Avoid unrelated state mutation tools.",
            ]
            suggested_tools = ["lookup_rules"] if "lookup_rules" in allowed_tools else []
        elif profile_name == "action_resolution":
            expectation = "Resolve the attempted action with the minimum necessary tool chain, then narrate once."
            checklist = [
                "Prefer one core resolution tool before considering persistence tools.",
                "Only persist evidence, loot, or chapter progress if the fiction actually establishes it.",
            ]
        elif profile_name == "combat_resolution":
            expectation = "Resolve one combat turn cleanly and avoid extra side actions or tool loops."
            checklist = [
                "Only resolve the current acting creature unless the turn is explicitly advanced.",
                "Advance the turn only after the acting creature has actually finished.",
            ]
        elif profile_name == "setup_guidance":
            expectation = "Keep the setup reply short and decision-oriented."
            checklist = [
                "Avoid dragging setup into freeform scene narration.",
            ]

        return {
            "turn_expectation": expectation,
            "suggested_tools": suggested_tools,
            "turn_checklist": checklist,
            "allowed_tools": self._prioritize_tools(allowed_tools, suggested_tools),
        }

    @staticmethod
    def _build_event(
        event_type: str,
        summary: str,
        content: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> SessionEvent:
        return SessionEvent(type=event_type, summary=summary, content=content, payload=payload or {})

    @staticmethod
    def _contains_any(text: str, terms: List[str]) -> bool:
        lowered = (text or "").casefold()
        return any(term.casefold() in lowered for term in terms if term)

    @staticmethod
    def _detect_input_warnings(text: str) -> List[str]:
        warnings: List[str] = []
        if not text:
            return warnings

        if "\ufffd" in text:
            warnings.append(
                "Input contains Unicode replacement characters; check client or shell text encoding."
            )

        # This catches the common Windows/stdin failure mode where CJK text arrives as question marks.
        question_count = text.count("?")
        if "???" in text or (question_count >= 6 and question_count / max(len(text), 1) > 0.2):
            warnings.append(
                "Input contains dense question-mark placeholders; non-ASCII text may have been corrupted before reaching the API."
            )

        return warnings

    @staticmethod
    def _unique_texts(values: List[str], limit: int = 4) -> List[str]:
        unique: List[str] = []
        seen = set()
        for raw in values:
            text = " ".join(str(raw or "").split()).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(text)
            if len(unique) >= limit:
                break
        return unique

    @staticmethod
    def _executed_tool_names(graph_state: DMGraphState) -> set[str]:
        names: set[str] = set()
        for item in graph_state.get("tool_results", []) or []:
            if isinstance(item, ToolResult):
                raw_name = item.tool_name
            elif isinstance(item, dict):
                raw_name = item.get("tool_name", "")
            else:
                raw_name = getattr(item, "tool_name", "")
            name = str(raw_name or "").strip()
            if name:
                names.add(name)
        return names

    @classmethod
    def _tool_result_present(cls, graph_state: DMGraphState, tool_name: str) -> bool:
        aliases = TOOL_RESULT_ALIASES.get(tool_name, {tool_name})
        return bool(cls._executed_tool_names(graph_state) & aliases)

    @classmethod
    def _tool_result_payloads(cls, graph_state: DMGraphState, tool_name: str) -> List[Dict[str, Any]]:
        aliases = TOOL_RESULT_ALIASES.get(tool_name, {tool_name})
        payloads: List[Dict[str, Any]] = []
        for item in graph_state.get("tool_results", []) or []:
            if isinstance(item, ToolResult):
                raw_name = item.tool_name
                raw_payload = item.payload
            elif isinstance(item, dict):
                raw_name = item.get("tool_name", "")
                raw_payload = item.get("payload", {})
            else:
                raw_name = getattr(item, "tool_name", "")
                raw_payload = getattr(item, "payload", {})
            if str(raw_name or "").strip() not in aliases:
                continue
            payloads.append(dict(raw_payload or {}))
        return payloads

    @staticmethod
    def _has_validation_issue(graph_state: DMGraphState, validator: str, action: str = "") -> bool:
        for item in graph_state.get("validation_issues", []) or []:
            if isinstance(item, ValidationIssue):
                issue_validator = item.validator
                issue_action = item.action
            elif isinstance(item, dict):
                issue_validator = str(item.get("validator", ""))
                issue_action = str(item.get("action", ""))
            else:
                issue_validator = str(getattr(item, "validator", ""))
                issue_action = str(getattr(item, "action", ""))
            if issue_validator != validator:
                continue
            if action and issue_action != action:
                continue
            return True
        return False

    def _repair_tool_call_error(
        self,
        graph_state: DMGraphState,
        tool_name: str,
        args: Dict[str, Any],
    ) -> str:
        if tool_name != "record_chapter_progress":
            return ""
        completed_arg = args.get("completed")
        completed_requested = self._chapter_completion_requested(graph_state.get("user_input", ""))
        repair_requires_completion = (
            str(graph_state.get("validation_status") or "") == "repair_required"
            and self._has_validation_issue(graph_state, "chapter_completion", "repair_required")
        )
        completed_is_true = completed_arg is True or str(completed_arg).strip().casefold() in {"true", "1", "yes"}
        if (completed_requested or repair_requires_completion) and not completed_is_true:
            return (
                "record_chapter_progress must include completed=true because the player asked to complete "
                "the chapter. The attempted call omitted that required argument."
            )
        return ""

    @staticmethod
    def _chapter_completion_requested(user_input: str) -> bool:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return False
        chapter_terms = ["chapter", "\u7ae0", "\u5927\u7ae0", "\u672c\u7ae0"]
        completion_terms = [
            "complete",
            "completed",
            "finish",
            "finished",
            "ending",
            "\u5b8c\u6210",
            "\u7ed3\u675f",
            "\u7ae0\u672b",
            "\u660e\u786e\u7ae0\u672b",
            "\u7ed3\u5c40",
            "\u6536\u675f",
        ]
        return any(term in lowered for term in chapter_terms) and any(
            term in lowered for term in completion_terms
        )

    @classmethod
    def _response_tool_requirements(cls, response_text: str, allowed_tools: List[str]) -> List[str]:
        lowered = " ".join((response_text or "").split()).strip().casefold()
        if not lowered:
            return []

        allowed = set(allowed_tools or [])
        requirements: List[str] = []

        def add(tool_name: str) -> None:
            if tool_name in allowed and tool_name not in requirements:
                requirements.append(tool_name)

        roll_markers = [
            "i roll",
            "rolling",
            "\u6211\u4e3a\u4f60",
            "\u8ba9\u6211",
            "\u4e3a\u4f60\u505a",
            "\u505a\u4e00\u6b21",
            "\u505a\u4e00\u7ec4",
            "\u8fdb\u884c\u4e00\u6b21",
            "\u8fdb\u884c\u4e00\u7ec4",
            "\u63b7\u9ab0",
            "\u6295\u9ab0",
        ]
        check_terms = [
            "check",
            "\u68c0\u5b9a",
            "\u5224\u5b9a",
            "\u63a2\u67e5",
            "\u611f\u77e5",
            "\u5bdf\u89c9",
            "\u8c03\u67e5",
        ]
        saving_terms = ["saving throw", "save", "\u8c41\u514d"]
        roll_result_pattern = re.compile(
            r"(?:check|save|\u68c0\u5b9a|\u5224\u5b9a|\u8c41\u514d)\s*(?:result|\u7ed3\u679c|[：:])?\s*\d+",
            re.IGNORECASE,
        )

        has_roll_marker = any(marker in lowered for marker in roll_markers)
        if roll_result_pattern.search(response_text or "") or (
            has_roll_marker and any(term in lowered for term in check_terms)
        ):
            add("roll_skill_check")
        if has_roll_marker and any(term in lowered for term in saving_terms):
            add("roll_saving_throw")

        attack_terms = ["attack", "hit", "miss", "damage", "\u653b\u51fb", "\u547d\u4e2d", "\u672a\u547d\u4e2d", "\u9020\u6210", "\u4f24\u5bb3"]
        if has_roll_marker and any(term in lowered for term in attack_terms):
            add("attack_target")

        if any(term in lowered for term in ["\u7ae0\u8282\u5df2\u8bb0\u5f55", "\u7ae0\u8282\u5b8c\u6210", "\u672c\u7ae0\u7ed3\u675f", "\u5c01\u7ae0", "chapter complete"]):
            add("record_chapter_progress")
        if any(term in lowered for term in ["\u6218\u6597\u7ed3\u675f", "\u906d\u9047\u7ed3\u675f", "encounter ends", "combat ends"]):
            add("end_encounter")

        return requirements

    @staticmethod
    def _contains_internal_tool_leak(response_text: str) -> bool:
        lowered = " ".join((response_text or "").split()).strip().casefold()
        if not lowered:
            return False
        leak_terms = [
            "record_chapter_progress",
            "completed=true",
            "validate_state",
            "tool call",
            "tool_call",
            "payload",
            "\u5de5\u5177\u8c03\u7528",
            "\u8c03\u7528\u5de5\u5177",
            "\u672a\u8c03\u7528\u5de5\u5177",
            "\u6ca1\u6709\u53d1\u8d77\u5de5\u5177",
            "\u72b6\u6001\u6821\u9a8c",
        ]
        return any(term in lowered for term in leak_terms)

    @staticmethod
    def _append_node_trace(
        graph_state: DMGraphState,
        node_name: str,
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "completed",
    ) -> List[Dict[str, Any]]:
        traces = list(graph_state.get("node_traces", []))
        traces.append(
            {
                "node_name": node_name,
                "status": status,
                "summary": summary,
                "metadata": metadata or {},
            }
        )
        return traces[-80:]

    @staticmethod
    def _scene_label(scene: str) -> str:
        return SCENE_LABELS.get((scene or "").strip().lower(), scene or "当前场景")

    def _matched_spell_names(self, state: GameState, user_input: str) -> List[str]:
        active = state.get_active_char()
        if not active:
            return []

        lowered = (user_input or "").casefold()
        matched: List[str] = []
        for spell_name in [*active.spells.cantrips, *active.spells.prepared]:
            normalized = str(spell_name or "").strip()
            if not normalized:
                continue
            details = self.library.get_spell_details(normalized)
            canonical = str(details.get("name") or normalized).strip()
            aliases = self._unique_texts(
                [
                    normalized,
                    str(details.get("name") or "").strip(),
                    str(details.get("nameEN") or "").strip(),
                ],
                limit=3,
            )
            for alias in aliases:
                if alias and alias.casefold() in lowered:
                    matched.append(canonical)
                    break
        return self._unique_texts(matched, limit=2)

    def _should_auto_retrieve_rules(self, state: GameState, user_input: str) -> tuple[bool, str]:
        intent_payload = self._classify_rule_intent(state, user_input)
        return bool(intent_payload.get("should_retrieve")), str(
            intent_payload.get("reason", "no automatic rules trigger matched")
        )

    def _build_rag_queries(self, state: GameState, user_input: str) -> List[str]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return []

        active = state.get_active_char()
        matched_spells = self._matched_spell_names(state, normalized_input)
        lowered = normalized_input.casefold()
        matched_terms = [
            term
            for term in RULE_TRIGGER_TERMS
            if term and term.casefold() in lowered and len(term.strip()) > 1
        ]
        matched_terms = self._unique_texts(matched_terms, limit=6)

        contextual_terms: List[str] = [self._scene_label(state.scene), self._scene_label(state.campaign.phase)]
        if active:
            contextual_terms.extend([active.class_name, active.species, active.background_name])
        contextual_terms.extend(matched_terms[:4])
        contextual_query = "D&D 2024 " + " ".join(term for term in contextual_terms if term)

        queries = [normalized_input, contextual_query]
        for spell_name in matched_spells:
            queries.append(f"D&D 2024 法术 规则 {spell_name}")
        if matched_terms:
            queries.append(f"D&D 2024 规则 {' '.join(matched_terms[:4])}")

        return self._unique_texts(queries, limit=4)

    @staticmethod
    def _query_phrase(*parts: str) -> str:
        return " ".join(part.strip() for part in parts if str(part or "").strip()).strip()

    @classmethod
    def _intent_term_matches(cls, text: str, terms: List[str], limit: int = 6) -> List[str]:
        lowered = (text or "").casefold()
        matches = [
            str(term).strip()
            for term in terms
            if str(term or "").strip() and str(term).casefold() in lowered
        ]
        return cls._unique_texts(matches, limit=limit)

    @staticmethod
    def _rule_intent_terms() -> Dict[str, List[str]]:
        return {
            "general_rules": [
                "rule",
                "rules",
                "ruling",
                "\u89c4\u5219",
                "\u89e3\u91ca",
                "\u8bf4\u660e",
                "\u5224\u5b9a",
            ],
            "combat_resolution": [
                "attack",
                "damage",
                "initiative",
                "turn",
                "reaction",
                "bonus action",
                "opportunity attack",
                "grapple",
                "shove",
                "advantage",
                "disadvantage",
                "save",
                "check",
                "\u653b\u51fb",
                "\u4f24\u5bb3",
                "\u5148\u653b",
                "\u56de\u5408",
                "\u53cd\u5e94",
                "\u9644\u8d60\u52a8\u4f5c",
                "\u501f\u673a\u653b\u51fb",
                "\u64d2\u62b1",
                "\u63a8\u649e",
                "\u4f18\u52bf",
                "\u52a3\u52bf",
                "\u8c41\u514d",
                "\u68c0\u5b9a",
            ],
            "spell_resolution": [
                "spell",
                "slot",
                "concentration",
                "ritual",
                "counterspell",
                "\u6cd5\u672f",
                "\u6cd5\u672f\u4f4d",
                "\u4e13\u6ce8",
                "\u65bd\u6cd5",
                "\u4eea\u5f0f",
            ],
            "condition_resolution": [
                "condition",
                "prone",
                "poisoned",
                "grappled",
                "restrained",
                "invisible",
                "\u72b6\u6001",
                "\u5012\u5730",
                "\u4e2d\u6bd2",
                "\u88ab\u64d2\u62b1",
                "\u675f\u7f1a",
                "\u9690\u5f62",
            ],
            "skill_resolution": [
                "skill",
                "ability check",
                "perception",
                "investigation",
                "stealth",
                "persuasion",
                "proficiency",
                "\u6280\u80fd",
                "\u5c5e\u6027\u68c0\u5b9a",
                "\u611f\u77e5",
                "\u8c03\u67e5",
                "\u6f5c\u884c",
                "\u8bf4\u670d",
                "\u719f\u7ec3",
            ],
            "rest_recovery": [
                "short rest",
                "long rest",
                "recover",
                "recovery",
                "\u77ed\u4f11",
                "\u957f\u4f11",
                "\u6062\u590d",
                "\u4f11\u606f",
            ],
        }

    @staticmethod
    def _rule_query_hints() -> Dict[str, str]:
        return {
            "rules_question": "\u89c4\u5219 \u89e3\u91ca",
            "general_rules": "\u89c4\u5219 \u8bf4\u660e",
            "combat_resolution": "\u6218\u6597 \u89c4\u5219",
            "spell_resolution": "\u6cd5\u672f \u65bd\u6cd5 \u6cd5\u672f\u4f4d",
            "condition_resolution": "\u72b6\u6001 \u6548\u679c \u89c4\u5219",
            "skill_resolution": "\u68c0\u5b9a \u6280\u80fd \u89c4\u5219",
            "rest_recovery": "\u4f11\u606f \u6062\u590d \u89c4\u5219",
        }

    @staticmethod
    def _looks_like_rule_question(text: str) -> bool:
        normalized = " ".join((text or "").split()).strip()
        if not normalized:
            return False
        lowered = normalized.casefold()
        markers = [
            "\u89c4\u5219",
            "\u5224\u5b9a",
            "\u89e3\u91ca",
            "\u8bf4\u660e",
            "rule",
            "rules",
            "ruling",
        ]
        if any(marker in lowered for marker in markers):
            return True

        has_question_shape = "?" in normalized or "\uff1f" in normalized
        if not has_question_shape:
            return False

        rule_markers = [
            *RULE_TRIGGER_TERMS,
            "rule",
            "rules",
            "ruling",
            "\u89c4\u5219",
            "\u89e3\u91ca",
            "\u5224\u5b9a",
            "\u6cd5\u672f",
            "\u4e13\u6ce8",
            "\u8c41\u514d",
            "\u68c0\u5b9a",
        ]
        return any(str(marker or "").casefold() in lowered for marker in rule_markers if str(marker or "").strip())

    def _classify_rule_intent(self, state: GameState, user_input: str) -> Dict[str, Any]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return {
                "intent": "none",
                "should_retrieve": False,
                "reason": "empty user input",
                "focus_terms": [],
                "matched_spells": [],
            }

        question_shape = self._looks_like_rule_question(normalized_input)
        matched_spells = self._matched_spell_names(state, normalized_input)
        category_matches = {
            name: self._intent_term_matches(normalized_input, terms)
            for name, terms in self._rule_intent_terms().items()
        }

        intent = "none"
        reason = "no automatic rules trigger matched"
        if matched_spells:
            intent = "spell_resolution"
            reason = "player referenced a prepared or known spell"
        elif category_matches["spell_resolution"] and (question_shape or state.scene == "combat"):
            intent = "spell_resolution"
            reason = "spell-related turn needs rules support"
        elif category_matches["condition_resolution"] and (question_shape or state.scene == "combat"):
            intent = "condition_resolution"
            reason = "condition-heavy turn needs rules support"
        elif category_matches["combat_resolution"] and (question_shape or state.scene == "combat"):
            intent = "combat_resolution"
            reason = "combat turn mentioned rules-sensitive actions"
        elif category_matches["rest_recovery"]:
            intent = "rest_recovery"
            reason = "player asked about recovery timing or rest rules"
        elif category_matches["skill_resolution"] and (question_shape or state.scene in {"exploration", "combat"}):
            intent = "skill_resolution"
            reason = "player asked for a skill or ability ruling"
        elif question_shape:
            intent = "rules_question"
            reason = "player asked an explicit rules question"
        elif category_matches["general_rules"]:
            intent = "general_rules"
            reason = "player referenced general rules language"

        focus_terms = self._unique_texts(
            [
                *matched_spells,
                *category_matches["combat_resolution"],
                *category_matches["spell_resolution"],
                *category_matches["condition_resolution"],
                *category_matches["skill_resolution"],
                *category_matches["rest_recovery"],
                *category_matches["general_rules"],
            ],
            limit=6,
        )
        return {
            "intent": intent,
            "should_retrieve": intent != "none",
            "reason": reason,
            "focus_terms": focus_terms,
            "matched_spells": matched_spells,
        }

    @staticmethod
    def _rule_intent_payload_from_turn_intent(turn_intent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intent": str(turn_intent.get("rag_intent") or "none"),
            "should_retrieve": bool(turn_intent.get("needs_rules")),
            "reason": str(turn_intent.get("rag_reason") or "no automatic rules trigger matched"),
            "focus_terms": list(turn_intent.get("focus_terms") or turn_intent.get("action_terms") or []),
            "matched_spells": list(turn_intent.get("matched_spells") or []),
        }

    def _classify_turn_profile(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        turn_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        phase_name = str(phase or "").strip().lower() or self._derive_phase(state)
        base_tools = self._allowed_tool_names(state, phase=phase_name)
        default_guidance = self._turn_profile_policy("action_resolution").get("guidance", "")
        intent_payload = dict(turn_intent or {})
        if not intent_payload:
            intent_payload = self._plan_turn_intent(state, user_input, phase_name).model_dump(mode="json")

        profile_name = str(intent_payload.get("turn_type") or "conversation").strip().lower()
        if profile_name not in TURN_PROFILE_POLICIES:
            profile_name = "conversation"
        reason = str(intent_payload.get("reason") or "structured turn intent selected this profile")

        policy = self._turn_profile_policy(profile_name)
        return {
            "turn_profile": profile_name,
            "turn_profile_reason": reason,
            "turn_guidance": str(policy.get("guidance") or default_guidance),
            "tool_round_limit": int(policy.get("tool_round_limit") or self.max_tool_rounds),
            "allowed_tools": self._profile_allowed_tools(base_tools, profile_name),
        }

    def _build_intent_rag_queries(
        self,
        state: GameState,
        user_input: str,
        intent_payload: Dict[str, Any],
    ) -> List[str]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return []

        active = state.get_active_char()
        intent = str(intent_payload.get("intent") or "rules_question")
        matched_spells = list(intent_payload.get("matched_spells", []))
        matched_terms = list(intent_payload.get("focus_terms", []))

        contextual_terms: List[str] = [self._scene_label(state.scene), self._scene_label(state.campaign.phase)]
        if active:
            contextual_terms.extend([active.class_name, active.species, active.background_name])
        contextual_terms.extend(matched_terms[:4])
        contextual_query = self._query_phrase("D&D 2024", *[term for term in contextual_terms if term])
        intent_hint = self._rule_query_hints().get(intent, "\u89c4\u5219")

        queries = [normalized_input]
        if contextual_query:
            queries.append(self._query_phrase(contextual_query, intent_hint))
        for spell_name in matched_spells:
            queries.append(self._query_phrase("D&D 2024", "\u6cd5\u672f", "\u89c4\u5219", spell_name))
        if matched_terms:
            queries.append(self._query_phrase("D&D 2024", intent_hint, *matched_terms[:4]))
        if active and intent in {"spell_resolution", "rest_recovery"}:
            queries.append(self._query_phrase("D&D 2024", active.class_name, intent_hint, *matched_terms[:3]))

        return self._unique_texts(queries, limit=4)

    def _prepare_turn(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        initial_game_state = dict(graph_state.get("initial_game_state") or graph_state["game_state"])
        user_input = graph_state.get("user_input", "")
        input_warnings = self._detect_input_warnings(user_input)
        payload = {"message": user_input}
        if input_warnings:
            payload["input_warnings"] = input_warnings
        player_event = self._build_event(
            event_type="player_action",
            summary="Player action",
            content=user_input,
            payload=payload,
        )
        state.timeline.append(player_event)
        return {
            "game_state": state.model_dump(mode="json"),
            "initial_game_state": initial_game_state,
            "tool_call_rounds": 0,
            "tool_results": [],
            "state_delta": {},
            "timeline_append": [player_event.model_dump(mode="json")],
            "input_warnings": input_warnings,
            "node_traces": self._append_node_trace(
                graph_state,
                "prepare_turn",
                "Player input appended to timeline.",
                {"input_warning_count": len(input_warnings)},
            ),
        }

    def _input_gate(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = str(graph_state.get("user_input", ""))
        state_delta = dict(graph_state.get("state_delta", {}))
        phase, _, _, patch, _ = self._normalize_phase_state(state)
        if patch:
            state_delta = merge_patch(state_delta, patch)

        request = self._build_required_input_request(state, user_input, phase)
        if not request or interrupt is None:
            return {
                "game_state": state.model_dump(mode="json"),
                "state_delta": state_delta,
                "turn_status": "running",
                "pending_input": {},
                "node_traces": self._append_node_trace(
                    graph_state,
                    "input_gate",
                    "Input accepted without clarification.",
                    {"phase": phase},
                ),
            }

        resumed_input = self._coerce_resume_input(interrupt(request))
        if not resumed_input:
            resumed_input = user_input
        return {
            "game_state": state.model_dump(mode="json"),
            "user_input": resumed_input,
            "state_delta": state_delta,
            "input_warnings": self._detect_input_warnings(resumed_input),
            "turn_status": "running",
            "pending_input": {},
            "node_traces": self._append_node_trace(
                graph_state,
                "input_gate",
                "Input resumed after clarification.",
                {"phase": phase},
            ),
        }

    def _plan_turn(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = str(graph_state.get("user_input", ""))
        state_delta = dict(graph_state.get("state_delta", {}))
        phase, scene, notes, patch, _ = self._normalize_phase_state(state)
        if patch:
            state_delta = merge_patch(state_delta, patch)
        turn_intent = self._plan_turn_intent(state, user_input, phase, scene)
        return {
            "game_state": state.model_dump(mode="json"),
            "phase": phase,
            "scene": scene,
            "turn_intent": turn_intent.model_dump(mode="json"),
            "state_delta": state_delta,
            "validation_notes": notes,
            "node_traces": self._append_node_trace(
                graph_state,
                "plan_turn",
                "Structured turn intent planned.",
                {
                    "turn_type": turn_intent.turn_type,
                    "risk_level": turn_intent.risk_level,
                    "needs_rules": turn_intent.needs_rules,
                    "rag_intent": turn_intent.rag_intent,
                },
            ),
        }

    def _route_phase(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = str(graph_state.get("user_input", ""))
        state_delta = dict(graph_state.get("state_delta", {}))
        phase, scene, notes, patch, policy = self._normalize_phase_state(state)
        turn_intent = dict(graph_state.get("turn_intent") or {})
        if not turn_intent:
            turn_intent = self._plan_turn_intent(state, user_input, phase, scene).model_dump(mode="json")
        turn_profile = self._classify_turn_profile(state, user_input, phase, turn_intent)
        turn_advice = self._build_turn_advice(
            state,
            user_input,
            phase,
            turn_profile["turn_profile"],
            list(turn_profile["allowed_tools"]),
            turn_intent=turn_intent,
        )
        if patch:
            state_delta = merge_patch(state_delta, patch)
            turn_intent = self._plan_turn_intent(state, user_input, phase, scene).model_dump(mode="json")
        return {
            "game_state": state.model_dump(mode="json"),
            "phase": phase,
            "scene": scene,
            "phase_objective": str(policy.get("objective", "")),
            "phase_constraints": list(policy.get("constraints", [])),
            "phase_blockers": self._phase_blockers(state, phase),
            "turn_intent": turn_intent,
            "turn_profile": turn_profile["turn_profile"],
            "turn_profile_reason": turn_profile["turn_profile_reason"],
            "turn_guidance": turn_profile["turn_guidance"],
            "turn_expectation": turn_advice["turn_expectation"],
            "suggested_tools": list(turn_advice["suggested_tools"]),
            "turn_checklist": list(turn_advice["turn_checklist"]),
            "tool_round_limit": turn_profile["tool_round_limit"],
            "allowed_tools": list(turn_advice["allowed_tools"]),
            "turn_status": str(graph_state.get("turn_status") or "running"),
            "pending_input": dict(graph_state.get("pending_input", {})),
            "state_delta": state_delta,
            "validation_notes": notes,
            "node_traces": self._append_node_trace(
                graph_state,
                "route_phase",
                "Phase policy, profile, and allowed tools selected.",
                {
                    "phase": phase,
                    "scene": scene,
                    "turn_profile": turn_profile["turn_profile"],
                    "allowed_tool_count": len(turn_advice["allowed_tools"]),
                },
            ),
        }

    def _prepare_context(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        logic = GameLogic(state)
        state_summary = logic.get_state_summary()
        recent_history = logic.get_recent_history()
        campaign_memory = compile_campaign_memory(state)
        instruction = build_dm_instruction(
            state_summary=state_summary,
            recent_history=recent_history,
            campaign_memory=campaign_memory,
            rag_enabled=self.rag_engine.is_ready(),
            retrieved_context=graph_state.get("rag_context", ""),
            phase_name=graph_state.get("phase", ""),
            phase_objective=graph_state.get("phase_objective", ""),
            phase_constraints=list(graph_state.get("phase_constraints", [])),
            phase_blockers=list(graph_state.get("phase_blockers", [])),
            turn_profile=graph_state.get("turn_profile", ""),
            turn_profile_reason=graph_state.get("turn_profile_reason", ""),
            turn_guidance=graph_state.get("turn_guidance", ""),
            tool_round_limit=int(graph_state.get("tool_round_limit", 0) or 0),
            turn_expectation=graph_state.get("turn_expectation", ""),
            suggested_tools=list(graph_state.get("suggested_tools", [])),
            turn_checklist=list(graph_state.get("turn_checklist", [])),
            turn_intent=dict(graph_state.get("turn_intent", {})),
        )
        return {
            "state_summary": state_summary,
            "recent_history": recent_history,
            "campaign_memory": campaign_memory,
            "instruction": instruction,
            "messages": [
                self._system_prompt_message(instruction),
                self._human_prompt_message(graph_state.get("user_input", "")),
            ],
            "node_traces": self._append_node_trace(
                graph_state,
                "prepare_context",
                "Prompt context prepared.",
                {
                    "rag_context_chars": len(graph_state.get("rag_context", "") or ""),
                    "campaign_memory_chars": len(campaign_memory),
                    "suggested_tool_count": len(graph_state.get("suggested_tools", [])),
                },
            ),
        }

    @staticmethod
    def _format_rag_context(
        snippets: List[Dict[str, str]],
        queries: Optional[List[str]] = None,
        intent: str = "",
    ) -> str:
        formatted: List[str] = []
        if intent:
            formatted.append(f"Retrieval intent: {intent}")
        if queries:
            formatted.append(f"Retrieval focus: {' | '.join(queries[:3])}")
        for snippet in snippets:
            heading = f" | {snippet.get('heading', '')}" if snippet.get("heading") else ""
            lines = ""
            if snippet.get("start_line") and snippet.get("end_line"):
                lines = f":L{snippet.get('start_line')}-L{snippet.get('end_line')}"
            formatted.append(
                f"--- Rule Snippet ({snippet.get('source', 'unknown')}#{snippet.get('chunk_index', '')}{lines}{heading}) ---\n"
                f"{snippet.get('content', '')}"
            )
        return "\n\n".join(formatted).strip()

    def _retrieve_rules(self, graph_state: DMGraphState) -> DMGraphState:
        n_results = int(os.getenv("RAG_AUTO_CONTEXT_RESULTS", "3") or 0)
        if n_results <= 0 or not self.rag_engine.is_ready():
            reason = "automatic retrieval disabled" if n_results <= 0 else "RAG engine is not ready"
            return {
                "rag_snippets": [],
                "rag_context": "",
                "rag_queries": [],
                "rag_intent": "none",
                "rag_reason": reason,
                "rag_metadata": {
                    "enabled": n_results > 0,
                    "ready": self.rag_engine.is_ready(),
                    "auto_context_results": n_results,
                    "intent": "none",
                    "reason": reason,
                    "queries": [],
                    "snippet_count": 0,
                    "sources": [],
                },
                "node_traces": self._append_node_trace(
                    graph_state,
                    "retrieve_rules",
                    "Automatic rules retrieval skipped.",
                    {"reason": reason, "ready": self.rag_engine.is_ready()},
                ),
            }

        state = GameState.model_validate(graph_state["game_state"])
        turn_intent = dict(graph_state.get("turn_intent") or {})
        intent_payload = (
            self._rule_intent_payload_from_turn_intent(turn_intent)
            if turn_intent
            else self._classify_rule_intent(state, graph_state.get("user_input", ""))
        )
        if not intent_payload.get("should_retrieve"):
            intent = str(intent_payload.get("intent", "none"))
            reason = str(intent_payload.get("reason", "no automatic rules trigger matched"))
            return {
                "rag_snippets": [],
                "rag_context": "",
                "rag_queries": [],
                "rag_intent": intent,
                "rag_reason": reason,
                "rag_metadata": {
                    "enabled": True,
                    "ready": True,
                    "auto_context_results": n_results,
                    "intent": intent,
                    "reason": reason,
                    "queries": [],
                    "snippet_count": 0,
                    "sources": [],
                },
                "node_traces": self._append_node_trace(
                    graph_state,
                    "retrieve_rules",
                    "Turn intent did not require automatic rules retrieval.",
                    {"intent": intent, "reason": reason},
                ),
            }

        queries = self._build_intent_rag_queries(state, graph_state.get("user_input", ""), intent_payload)
        snippets = self.library.localize_rag_snippets(
            self.rag_engine.search_many(queries, n_results=n_results)
        )
        intent = str(intent_payload.get("intent", "none"))
        reason = str(intent_payload.get("reason", ""))
        sources = self._unique_texts(
            [str(snippet.get("source", "")) for snippet in snippets],
            limit=8,
        )
        return {
            "rag_snippets": snippets,
            "rag_context": self._format_rag_context(
                snippets,
                queries=queries,
                intent=intent,
            ),
            "rag_queries": queries,
            "rag_intent": intent,
            "rag_reason": reason,
            "rag_metadata": {
                "enabled": True,
                "ready": True,
                "auto_context_results": n_results,
                "intent": intent,
                "reason": reason,
                "queries": queries,
                "snippet_count": len(snippets),
                "sources": sources,
            },
            "node_traces": self._append_node_trace(
                graph_state,
                "retrieve_rules",
                "Automatic rules retrieval completed.",
                {"intent": intent, "query_count": len(queries), "snippet_count": len(snippets)},
            ),
        }

    def _draft_response_placeholder(self, graph_state: DMGraphState) -> DMGraphState:
        return {
            "final_response": (
                "LangGraph turn workflow is prepared, but the model/tool execution node is not enabled yet."
            ),
            "node_traces": self._append_node_trace(
                graph_state,
                "draft_response",
                "Model execution skipped because enable_model is false.",
                {"enable_model": False},
            ),
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

    @staticmethod
    def _summarize_model_exception(exc: Exception) -> str:
        message = re.sub(r"\s+", " ", str(exc or "")).strip()
        if not message:
            return "Unknown model invocation error."
        return message[:320]

    @staticmethod
    def _system_prompt_message(content: str) -> Any:
        if SystemMessage is not None:
            return SystemMessage(content=content)
        return {"role": "system", "content": content}

    @staticmethod
    def _human_prompt_message(content: str) -> Any:
        if HumanMessage is not None:
            return HumanMessage(content=content)
        return {"role": "user", "content": content}

    def _call_model(self, graph_state: DMGraphState) -> DMGraphState:
        messages = list(graph_state.get("messages", []))
        if not messages:
            messages = [
                self._system_prompt_message(graph_state.get("instruction", "")),
                self._human_prompt_message(graph_state.get("user_input", "")),
            ]
        model = self._create_tool_bound_model(graph_state.get("allowed_tools", []))
        try:
            response = model.invoke(messages)
        except Exception as exc:
            detail = self._summarize_model_exception(exc)
            validation_notes = list(graph_state.get("validation_notes", []))
            validation_issues = list(graph_state.get("validation_issues", []))
            self._record_validation_issue(
                validation_notes,
                validation_issues,
                validator="model_call",
                severity="error",
                action="failed_turn",
                summary=f"Model invocation failed: {detail}",
                metadata={"detail": detail},
            )
            rag_metadata = dict(graph_state.get("rag_metadata", {}))
            rag_metadata["model_error"] = detail
            return {
                "final_response": f"当前模型服务不可用，本回合未能继续执行。原因：{detail}",
                "turn_status": "failed",
                "validation_notes": validation_notes,
                "validation_issues": validation_issues,
                "rag_metadata": rag_metadata,
                "node_traces": self._append_node_trace(
                    graph_state,
                    "draft_response",
                    "Model invocation failed.",
                    {"error": detail},
                    status="failed",
                ),
            }

        final_response = self.library.localize_game_terms(self._extract_message_content(response))
        tool_calls = self._last_message_tool_calls([response])
        retry_node_trace: List[Dict[str, Any]] = []
        repair_required = str(graph_state.get("validation_status") or "") == "repair_required"
        missing_tool_expected = self._should_retry_missing_tool_call(graph_state, final_response, tool_calls)
        if not repair_required and missing_tool_expected:
            retry_instruction = self._human_prompt_message(
                "上一条回复描述了掷骰、施法、攻击、记录、使用物品或状态变更，但没有发起工具调用。"
                "请现在只调用必要工具；在工具结果返回前不要叙述结果。"
                "如果没有任何工具适合，请简短说明无法调用工具的具体原因。"
            )
            retry_messages = [*messages, response, retry_instruction]
            try:
                retry_response = model.invoke(retry_messages)
                retry_tool_calls = self._last_message_tool_calls([retry_response])
                if retry_tool_calls:
                    messages = retry_messages
                    response = retry_response
                    tool_calls = retry_tool_calls
                    final_response = self.library.localize_game_terms(self._extract_message_content(retry_response))
                retry_node_trace = self._append_node_trace(
                    graph_state,
                    "draft_response",
                    "Retried model response after missing expected tool call.",
                    {
                        "retry_tool_call_count": len(retry_tool_calls),
                        "previous_response_chars": len(final_response),
                    },
                )
            except Exception as exc:
                detail = self._summarize_model_exception(exc)
                retry_node_trace = self._append_node_trace(
                    graph_state,
                    "draft_response",
                    "Model retry after missing tool call failed.",
                    {"error": detail},
                    status="failed",
                )
        if (repair_required or missing_tool_expected) and not tool_calls:
            validation_notes = list(graph_state.get("validation_notes", []))
            validation_issues = list(graph_state.get("validation_issues", []))
            validator = "turn_repair" if repair_required else "tool_required"
            summary = (
                "Model did not call a required repair tool after validation requested state repair."
                if repair_required
                else "Model described an action that required tools but did not call any tool."
            )
            self._record_validation_issue(
                validation_notes,
                validation_issues,
                validator=validator,
                severity="error",
                action="failed_turn",
                summary=summary,
                metadata={
                    "allowed_tools": list(graph_state.get("allowed_tools", [])),
                    "suggested_tools": list(graph_state.get("suggested_tools", [])),
                },
            )
            return {
                "messages": [*messages, response],
                "final_response": (
                    "本回合需要先通过工具修复状态或执行规则结算，但模型没有发起必要工具调用；"
                    "为避免叙事和状态不一致，本回合未提交。"
                ),
                "turn_status": "failed",
                "validation_notes": validation_notes,
                "validation_issues": validation_issues,
                "node_traces": self._append_node_trace(
                    graph_state,
                    "draft_response",
                    summary,
                    {"tool_call_count": 0, "validation_status": graph_state.get("validation_status", "")},
                    status="failed",
                ),
            }

        if not final_response and not tool_calls:
            retry_instruction = self._human_prompt_message(
                "上一条模型消息没有工具调用，也没有可展示给玩家的最终回复。"
                "如果还需要工具，请调用工具；如果工具已经成功，请基于工具结果给出简体中文的最终叙事。"
                "不要留空。"
            )
            retry_messages = [*messages, response, retry_instruction]
            try:
                retry_response = model.invoke(retry_messages)
                retry_tool_calls = self._last_message_tool_calls([retry_response])
                retry_final_response = self.library.localize_game_terms(
                    self._extract_message_content(retry_response)
                )
                if retry_tool_calls or retry_final_response:
                    messages = retry_messages
                    response = retry_response
                    tool_calls = retry_tool_calls
                    final_response = retry_final_response
                retry_node_trace = self._append_node_trace(
                    {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])},
                    "draft_response",
                    "Retried empty model response.",
                    {
                        "retry_tool_call_count": len(retry_tool_calls),
                        "retry_response_chars": len(retry_final_response),
                    },
                )
            except Exception as exc:
                detail = self._summarize_model_exception(exc)
                retry_node_trace = self._append_node_trace(
                    {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])},
                    "draft_response",
                    "Model retry after empty response failed.",
                    {"error": detail},
                    status="failed",
                )

        if not final_response and not tool_calls:
            validation_notes = list(graph_state.get("validation_notes", []))
            validation_issues = list(graph_state.get("validation_issues", []))
            summary = "Model returned an empty final response and did not call a tool."
            self._record_validation_issue(
                validation_notes,
                validation_issues,
                validator="empty_response",
                severity="error",
                action="failed_turn",
                summary=summary,
                metadata={
                    "allowed_tools": list(graph_state.get("allowed_tools", [])),
                    "suggested_tools": list(graph_state.get("suggested_tools", [])),
                    "tool_result_count": len(graph_state.get("tool_results", []) or []),
                },
            )
            return {
                "messages": [*messages, response],
                "final_response": "模型没有生成可提交的最终叙事；为避免空回复提交状态，本回合未提交。",
                "turn_status": "failed",
                "validation_notes": validation_notes,
                "validation_issues": validation_issues,
                "node_traces": self._append_node_trace(
                    {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])},
                    "draft_response",
                    summary,
                    {"tool_call_count": 0},
                    status="failed",
                ),
            }

        if final_response and not tool_calls and self._contains_internal_tool_leak(final_response):
            retry_instruction = self._human_prompt_message(
                "上一条回复泄露了内部工具、校验或参数细节。"
                "请重写为玩家可见的简体中文叙事，只描述已经由工具结果支持的剧情和状态，不要提工具、参数、校验或框架。"
            )
            retry_messages = [*messages, response, retry_instruction]
            try:
                retry_response = model.invoke(retry_messages)
                retry_tool_calls = self._last_message_tool_calls([retry_response])
                retry_final_response = self.library.localize_game_terms(
                    self._extract_message_content(retry_response)
                )
                if retry_tool_calls or retry_final_response:
                    messages = retry_messages
                    response = retry_response
                    tool_calls = retry_tool_calls
                    final_response = retry_final_response
                retry_node_trace = self._append_node_trace(
                    {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])},
                    "draft_response",
                    "Retried response after internal tool leakage.",
                    {
                        "retry_tool_call_count": len(retry_tool_calls),
                        "retry_response_chars": len(retry_final_response),
                    },
                )
            except Exception as exc:
                detail = self._summarize_model_exception(exc)
                retry_node_trace = self._append_node_trace(
                    {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])},
                    "draft_response",
                    "Model retry after internal tool leakage failed.",
                    {"error": detail},
                    status="failed",
                )

        if final_response and not tool_calls and self._contains_internal_tool_leak(final_response):
            validation_notes = list(graph_state.get("validation_notes", []))
            validation_issues = list(graph_state.get("validation_issues", []))
            summary = "Model leaked internal tool or validation details in the player-facing response."
            self._record_validation_issue(
                validation_notes,
                validation_issues,
                validator="response_leakage",
                severity="error",
                action="failed_turn",
                summary=summary,
                metadata={"response_chars": len(final_response)},
            )
            return {
                "messages": [*messages, response],
                "final_response": "模型生成了包含内部工具细节的回复；为避免破坏玩家叙事，本回合未提交。",
                "turn_status": "failed",
                "validation_notes": validation_notes,
                "validation_issues": validation_issues,
                "node_traces": self._append_node_trace(
                    {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])},
                    "draft_response",
                    summary,
                    {"response_chars": len(final_response)},
                    status="failed",
                ),
            }

        result: DMGraphState = {"messages": [*messages, response]}
        if final_response:
            result["final_response"] = final_response
        trace_base = {**graph_state, "node_traces": retry_node_trace or graph_state.get("node_traces", [])}
        result["node_traces"] = self._append_node_trace(
            trace_base,
            "draft_response",
            "Model response received.",
            {
                "tool_call_count": len(tool_calls),
                "response_chars": len(final_response),
            },
        )
        return result

    @staticmethod
    def _last_message_tool_calls(messages: List[Any]) -> List[Dict[str, Any]]:
        if not messages:
            return []
        return list(getattr(messages[-1], "tool_calls", []) or [])

    def _should_retry_missing_tool_call(
        self,
        graph_state: DMGraphState,
        response_text: str,
        tool_calls: List[Dict[str, Any]],
    ) -> bool:
        if tool_calls:
            return False
        allowed_tools = list(graph_state.get("allowed_tools", []))
        if not allowed_tools:
            return False

        user_input = str(graph_state.get("user_input") or "")
        lowered_input = user_input.casefold()
        explicit_tool_request = "\u8c03\u7528" in lowered_input or "tool" in lowered_input
        explicit_names = set(self._explicit_tool_names_in_input(user_input))
        for tool_name in allowed_tools:
            tool_lower = tool_name.casefold()
            if tool_lower and (
                f"{tool_lower}(" in lowered_input
                or f"`{tool_lower}`" in lowered_input
                or f"\u8c03\u7528 {tool_lower}" in lowered_input
                or f"\u8c03\u7528{tool_lower}" in lowered_input
                or (tool_name in explicit_names and any(marker in lowered_input for marker in ["call", "use", "\u7528", "\u8c03\u7528"]))
            ):
                explicit_tool_request = True
                break

        suggested_tools = set(graph_state.get("suggested_tools", []) or [])
        lowered_response = (response_text or "").casefold()
        response_requirements = self._response_tool_requirements(response_text, allowed_tools)
        for tool_name in response_requirements:
            if not self._tool_result_present(graph_state, tool_name):
                return True

        if explicit_tool_request:
            explicit_targets = [
                tool_name
                for tool_name in self._unique_texts([*explicit_names, *suggested_tools], limit=8)
                if tool_name in set(allowed_tools)
            ]
            if explicit_targets:
                return any(not self._tool_result_present(graph_state, tool_name) for tool_name in explicit_targets)
            return not bool(self._executed_tool_names(graph_state))

        if not suggested_tools:
            return False

        tool_intent_terms = [
            "i roll",
            "i cast",
            "i attack",
            "i record",
            "i use",
            "rolling",
            "casting",
            "\u6211\u6765",
            "\u5148\u5904\u7406",
            "\u63b7\u9ab0",
            "\u6295\u9ab0",
            "\u65bd\u653e",
            "\u65bd\u6cd5",
            "\u653b\u51fb",
            "\u8bb0\u5f55",
            "\u4f7f\u7528",
            "\u559d\u4e0b",
            "hp",
            "\u751f\u547d\u503c",
            "\u6218\u6597\u7ed3\u675f",
            "\u906d\u9047\u7ed3\u675f",
            "\u5df2\u5012\u4e0b",
        ]
        if any(term in lowered_response for term in tool_intent_terms):
            relevant_suggestions = [tool_name for tool_name in suggested_tools if tool_name in set(allowed_tools)]
            if relevant_suggestions:
                return any(
                    not self._tool_result_present(graph_state, tool_name)
                    for tool_name in relevant_suggestions
                )
            return not bool(self._executed_tool_names(graph_state))
        return False

    def _should_continue_after_model(self, graph_state: DMGraphState) -> str:
        if str(graph_state.get("turn_status") or "") == "failed":
            return "finalize_turn"
        tool_calls = self._last_message_tool_calls(list(graph_state.get("messages", [])))
        tool_round_limit = int(graph_state.get("tool_round_limit", 0) or self.max_tool_rounds)
        if tool_calls and graph_state.get("tool_call_rounds", 0) < tool_round_limit:
            return "execute_tools"
        return "finalize_turn"

    @staticmethod
    def _should_continue_after_validation(graph_state: DMGraphState) -> str:
        if str(graph_state.get("validation_status") or "") == "failed":
            return "finalize_turn"
        return "draft_response"

    def _tool_error_execution(
        self,
        tool_name: str,
        message: str,
        guardrail: Optional[Dict[str, Any]] = None,
    ) -> AgentToolExecution:
        error_response = {"ok": False, "tool_name": tool_name, "error": message}
        if guardrail:
            error_response["guardrail"] = guardrail
        return AgentToolExecution(
            ok=False,
            error=message,
            error_response=error_response,
        )

    @staticmethod
    def _is_confirmation_affirmative(value: Any) -> bool:
        if isinstance(value, dict):
            for key in ["confirmed", "confirm", "approved", "approve", "allow", "execute"]:
                if key in value:
                    return bool(value.get(key))
            text = value.get("message") or value.get("input") or value.get("content") or ""
        else:
            text = str(value or "")

        normalized = " ".join(str(text or "").split()).strip().casefold()
        if not normalized:
            return False
        negative_terms = {
            "no",
            "n",
            "cancel",
            "deny",
            "decline",
            "stop",
            "否",
            "不",
            "不要",
            "取消",
            "拒绝",
            "停止",
        }
        if normalized in negative_terms:
            return False
        affirmative_terms = {
            "yes",
            "y",
            "ok",
            "okay",
            "confirm",
            "confirmed",
            "approve",
            "approved",
            "execute",
            "go ahead",
            "确认",
            "是",
            "可以",
            "同意",
            "执行",
            "继续",
        }
        return normalized in affirmative_terms

    def _confirm_tool_execution(
        self,
        graph_state: DMGraphState,
        tool_name: str,
        args: Dict[str, Any],
        guardrail: ToolGuardrailResult,
    ) -> tuple[bool, str]:
        if not guardrail.metadata.get("requires_confirmation"):
            return True, ""
        if interrupt is None:
            return False, f"Tool requires confirmation before execution: {tool_name}"

        payload = {
            "kind": "tool_confirmation",
            "phase": str(graph_state.get("phase") or ""),
            "prompt": (
                f"工具 `{tool_name}` 会执行高风险状态变更。"
                "请回复“确认”执行，或回复“取消”跳过。"
            ),
            "details": {
                "reason": "high_risk_tool_confirmation",
                "tool_name": tool_name,
                "args": dict(args or {}),
                "guardrail": dict(guardrail.metadata),
                "turn_intent": dict(graph_state.get("turn_intent") or {}),
            },
        }
        resumed = interrupt(payload)
        if self._is_confirmation_affirmative(resumed):
            return True, ""
        return False, f"Tool execution cancelled by confirmation guardrail: {tool_name}"

    def _execute_single_tool(
        self,
        state: GameState,
        tool_name: str,
        args: Dict[str, Any],
        allowed_tools: List[str],
    ) -> AgentToolExecution:
        guardrail = self.tool_registry.validate_call(
            state=state,
            tool_name=tool_name,
            args=args,
            allowed_tools=allowed_tools,
        )
        if not guardrail.ok:
            return self._tool_error_execution(tool_name, guardrail.error, guardrail.metadata)
        if not self.tool_service:
            return self._tool_error_execution(tool_name, "Agent tool service is not configured.")
        tool = getattr(self.tool_service, tool_name, None)
        if not tool:
            return self._tool_error_execution(tool_name, f"Unknown tool: {tool_name}")
        try:
            return tool(state, **guardrail.args)
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
        tool_trace_items: List[Dict[str, Any]] = []

        for tool_call in self._last_message_tool_calls(messages):
            tool_name = tool_call.get("name", "")
            args = dict(tool_call.get("args") or {})
            guardrail = self.tool_registry.validate_call(
                state=state,
                tool_name=tool_name,
                args=args,
                allowed_tools=allowed_tools,
            )
            confirmation_status = ""
            if not guardrail.ok:
                execution = self._tool_error_execution(tool_name, guardrail.error, guardrail.metadata)
            else:
                repair_error = self._repair_tool_call_error(graph_state, tool_name, guardrail.args)
                if repair_error:
                    execution = self._tool_error_execution(tool_name, repair_error, guardrail.metadata)
                elif guardrail.metadata.get("requires_confirmation"):
                    confirmed, confirmation_error = self._confirm_tool_execution(
                        graph_state,
                        tool_name,
                        args,
                        guardrail,
                    )
                    confirmation_status = "confirmed" if confirmed else "cancelled"
                    if not confirmed:
                        execution = self._tool_error_execution(
                            tool_name,
                            confirmation_error,
                            guardrail.metadata,
                        )
                    else:
                        execution = self._execute_single_tool(state, tool_name, args, allowed_tools)
                else:
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
            tool_trace_items.append(
                {
                    "tool_name": tool_name,
                    "ok": execution.ok,
                    "error": execution.error,
                    "guardrail": dict(guardrail.metadata),
                    "confirmation_status": confirmation_status,
                }
            )

        return {
            "game_state": state.model_dump(mode="json"),
            "messages": messages,
            "tool_results": tool_results,
            "timeline_append": timeline_append,
            "state_delta": state_delta,
            "tool_call_rounds": graph_state.get("tool_call_rounds", 0) + 1,
            "allowed_tools": self._allowed_tool_names(state, phase=self._derive_phase(state)),
            "node_traces": self._append_node_trace(
                graph_state,
                "execute_tools",
                "Tool call round executed.",
                {
                    "tool_call_count": len(self._last_message_tool_calls(list(graph_state.get("messages", [])))),
                    "tool_result_count": len(tool_results),
                    "tool_round": graph_state.get("tool_call_rounds", 0) + 1,
                    "tools": tool_trace_items,
                },
            ),
        }

    @staticmethod
    def _build_validation_message(notes: List[str]) -> Optional[Any]:
        if not notes or SystemMessage is None:
            return None
        content = "State validation updates:\n- " + "\n- ".join(notes)
        return SystemMessage(content=content)

    @staticmethod
    def _record_validation_issue(
        notes: List[str],
        issues: List[Dict[str, Any]],
        *,
        validator: str,
        summary: str,
        severity: str = "info",
        action: str = "noted",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        notes.append(summary)
        issues.append(
            ValidationIssue(
                validator=validator,
                severity=severity,
                action=action,
                summary=summary,
                metadata=dict(metadata or {}),
            ).model_dump(mode="json")
        )

    def _validate_state(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        messages = list(graph_state.get("messages", []))
        timeline_append = list(graph_state.get("timeline_append", []))
        state_delta = dict(graph_state.get("state_delta", {}))
        validation_notes: List[str] = list(graph_state.get("validation_notes", []))
        validation_issues: List[Dict[str, Any]] = list(graph_state.get("validation_issues", []))
        logic = GameLogic(state)
        repair_tools: List[str] = []
        validation_status = "ok"

        def mark_repair(
            *,
            validator: str,
            summary: str,
            tools: Optional[List[str]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            nonlocal validation_status
            validation_status = "repair_required" if validation_status != "failed" else validation_status
            repair_tools.extend(tools or [])
            self._record_validation_issue(
                validation_notes,
                validation_issues,
                validator=validator,
                severity="error",
                action="repair_required",
                summary=summary,
                metadata=metadata,
            )

        def mark_failed(
            *,
            validator: str,
            summary: str,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            nonlocal validation_status
            validation_status = "failed"
            self._record_validation_issue(
                validation_notes,
                validation_issues,
                validator=validator,
                severity="error",
                action="failed_turn",
                summary=summary,
                metadata=metadata,
            )

        if state.characters and (
            not state.active_character_id or state.active_character_id not in state.characters
        ):
            mark_repair(
                validator="active_character",
                summary="Active character reference is missing or invalid; call set_active_character before narrating.",
                tools=["set_active_character"],
                metadata={"active_character_id": state.active_character_id},
            )

        encounter = state.encounter
        if encounter and encounter.active:
            if state.scene != "combat" or state.campaign.phase != "combat":
                mark_repair(
                    validator="combat_phase",
                    summary="Encounter is active but scene/campaign phase is not combat; call set_scene with combat before narrating.",
                    tools=["set_scene"],
                    metadata={"scene": state.scene, "phase": state.campaign.phase, "expected": "combat"},
                )

            if not encounter.combatants:
                mark_failed(
                    validator="encounter_integrity",
                    summary="Active encounter has no combatants; this cannot be repaired by narration.",
                    metadata={"encounter_id": encounter.encounter_id},
                )
            else:
                for combatant in encounter.combatants.values():
                    if not combatant.linked_character_id:
                        continue
                    character = state.characters.get(combatant.linked_character_id)
                    if not character:
                        continue
                    expected_skills = logic._character_skill_modifiers(character)
                    expected_saves = logic._character_save_modifiers(character)
                    if (
                        combatant.hp_current != character.hp_current
                        or combatant.hp_max != character.hp_max
                        or combatant.ac != character.ac
                        or combatant.initiative_bonus != character.initiative_bonus
                        or combatant.status_effects != list(character.status_effects)
                        or combatant.defeat_state != character.defeat_state
                        or combatant.stats != character.stats
                        or combatant.skills != expected_skills
                        or combatant.saving_throws != expected_saves
                    ):
                        mark_failed(
                            validator="party_combatant_sync",
                            summary=(
                                "Party combatant mirror differs from its character sheet; "
                                "the mutating tool must sync both views instead of validate_state patching it."
                            ),
                            metadata={"combatant_id": combatant.combatant_id, "character_id": character.character_id},
                        )
                        break

                order_index = {
                    combatant_id: index
                    for index, combatant_id in enumerate(encounter.initiative_order)
                }
                expected_order = sorted(
                    encounter.combatants.values(),
                    key=lambda combatant: (
                        combatant.initiative is None,
                        -(combatant.initiative or -999),
                        order_index.get(combatant.combatant_id, 9999),
                        combatant.name,
                    ),
                )
                expected_order_ids = [combatant.combatant_id for combatant in expected_order]
                if encounter.initiative_order != expected_order_ids:
                    mark_failed(
                        validator="initiative_order",
                        summary="Initiative order is out of sync; initiative-mutating tools must refresh it.",
                        metadata={"initiative_order": encounter.initiative_order, "expected_order": expected_order_ids},
                    )

                if encounter.current_combatant_id and encounter.current_combatant_id not in encounter.combatants:
                    mark_repair(
                        validator="current_combatant",
                        summary="Current combatant reference is invalid; call advance_turn to select a legal combatant.",
                        tools=["advance_turn"],
                        metadata={"current_combatant_id": encounter.current_combatant_id},
                    )

                all_initiatives_ready = bool(encounter.initiative_order) and all(
                    encounter.combatants.get(combatant_id)
                    and encounter.combatants[combatant_id].initiative is not None
                    for combatant_id in encounter.initiative_order
                )
                eligible_order = [
                    combatant_id
                    for combatant_id in encounter.initiative_order
                    if logic._combatant_can_take_turn(encounter.combatants.get(combatant_id))
                ]
                if not encounter.turn_order_started and all_initiatives_ready:
                    mark_repair(
                        validator="turn_order",
                        summary="Initiative is ready but turn order has not started; call advance_turn before narrating turns.",
                        tools=["advance_turn"],
                    )
                elif encounter.turn_order_started and eligible_order and encounter.current_combatant_id not in eligible_order:
                    mark_repair(
                        validator="current_combatant",
                        summary="Current combatant cannot act; call advance_turn before narrating another action.",
                        tools=["advance_turn"],
                        metadata={"current_combatant_id": encounter.current_combatant_id},
                    )
                elif encounter.turn_order_started and not eligible_order and encounter.current_combatant_id is not None:
                    mark_repair(
                        validator="current_combatant",
                        summary="No combatant can currently act but current_combatant_id is still set; call advance_turn or end_encounter.",
                        tools=["advance_turn", "end_encounter"],
                        metadata={"current_combatant_id": encounter.current_combatant_id},
                    )

                current = encounter.get_current_combatant()
                if current and current.linked_character_id and current.linked_character_id in state.characters:
                    if state.active_character_id != current.linked_character_id:
                        mark_repair(
                            validator="active_character",
                            summary="Active character does not match the current party combatant; call set_active_character.",
                            tools=["set_active_character"],
                            metadata={
                                "active_character_id": state.active_character_id,
                                "expected_active_character_id": current.linked_character_id,
                            },
                        )

                enemies = [combatant for combatant in encounter.combatants.values() if combatant.side == "enemy"]
                active_enemies = [
                    combatant
                    for combatant in enemies
                    if combatant.hp_current > 0 and combatant.defeat_state == "active"
                ]
                if enemies and not active_enemies:
                    mark_repair(
                        validator="encounter_end_condition",
                        summary="No active enemies remain; call end_encounter before final narration.",
                        tools=["end_encounter"],
                        metadata={"reason": "no_active_enemies"},
                    )
        elif state.scene == "combat":
            mark_repair(
                validator="combat_phase",
                summary="Scene is combat but no active encounter exists; call set_scene before narrating.",
                tools=["set_scene"],
                metadata={"scene": state.scene, "phase": state.campaign.phase},
            )

        if self._chapter_completion_requested(graph_state.get("user_input", "")):
            chapter_payloads = self._tool_result_payloads(graph_state, "record_chapter_progress")
            has_completed_chapter_record = any(
                bool(payload.get("completed")) or str(payload.get("status", "")).strip().lower() == "completed"
                for payload in chapter_payloads
            )
            if not has_completed_chapter_record:
                latest_chapter_payload = dict(chapter_payloads[-1]) if chapter_payloads else {}
                mark_repair(
                    validator="chapter_completion",
                    summary=(
                        "Player asked to complete the chapter, but no successful record_chapter_progress result "
                        "marked the chapter completed; call record_chapter_progress with completed=true before final narration."
                    ),
                    tools=["record_chapter_progress"],
                    metadata={
                        "chapter_number": latest_chapter_payload.get("chapter_number", state.campaign.current_chapter_number),
                        "chapter_title": latest_chapter_payload.get("title", state.campaign.current_chapter_title),
                        "completed": latest_chapter_payload.get("completed", False),
                        "status": latest_chapter_payload.get("status", ""),
                    },
                )

        phase = self._derive_phase(state)
        scene = self._expected_scene_for_phase(phase, state.scene)
        policy = self._phase_policy(phase)
        turn_intent = self._plan_turn_intent(state, graph_state.get("user_input", ""), phase, scene).model_dump(mode="json")
        turn_profile = self._classify_turn_profile(state, graph_state.get("user_input", ""), phase, turn_intent)
        turn_advice = self._build_turn_advice(
            state,
            graph_state.get("user_input", ""),
            phase,
            turn_profile["turn_profile"],
            list(turn_profile["allowed_tools"]),
            turn_intent=turn_intent,
        )

        repair_tools = self._unique_texts(repair_tools, limit=8)
        if validation_status == "repair_required":
            repair_requirements: List[str] = []
            if self._has_validation_issue({"validation_issues": validation_issues}, "chapter_completion", "repair_required"):
                repair_requirements.append(
                    "For chapter_completion, call record_chapter_progress with completed=true. "
                    "Do not call it with completed omitted or false."
                )
            repair_text = (
                "State verification requires repair before any final narration.\n"
                f"Allowed repair tools: {' | '.join(repair_tools) if repair_tools else 'none'}.\n"
                f"Mandatory repair requirements: {' | '.join(repair_requirements) if repair_requirements else 'Use the exact repair requested by the issue.'}\n"
                "Call the necessary repair tool now. Do not narrate outcomes until the repair tool succeeds.\n"
                "Issues:\n- " + "\n- ".join(validation_notes[-6:])
            )
            messages.append(self._system_prompt_message(repair_text))
            turn_advice["allowed_tools"] = repair_tools
            turn_advice["suggested_tools"] = repair_tools
            turn_advice["turn_expectation"] = "Repair state with a tool call only; no final narration yet."
            turn_advice["turn_checklist"] = ["Call a repair tool before narration."]
            turn_profile["turn_guidance"] = "State verification found an inconsistency that must be repaired by tools."
            turn_profile["tool_round_limit"] = max(
                int(turn_profile["tool_round_limit"] or 0),
                int(graph_state.get("tool_call_rounds", 0) or 0) + 1,
            )
        else:
            validation_message = self._build_validation_message(validation_notes)
            if validation_message is not None:
                messages.append(validation_message)

        final_response = ""
        turn_status = str(graph_state.get("turn_status") or "running")
        if validation_status == "failed":
            final_response = "状态校验发现无法安全自动修复的问题；为避免叙事和状态不一致，本回合未提交。"
            turn_status = "failed"

        return {
            "game_state": state.model_dump(mode="json"),
            "messages": messages,
            "timeline_append": timeline_append,
            "state_delta": state_delta,
            "phase": phase,
            "scene": scene,
            "phase_objective": str(policy.get("objective", "")),
            "phase_constraints": list(policy.get("constraints", [])),
            "phase_blockers": self._phase_blockers(state, phase),
            "turn_intent": turn_intent,
            "turn_profile": turn_profile["turn_profile"],
            "turn_profile_reason": turn_profile["turn_profile_reason"],
            "turn_guidance": turn_profile["turn_guidance"],
            "turn_expectation": turn_advice["turn_expectation"],
            "suggested_tools": list(turn_advice["suggested_tools"]),
            "turn_checklist": list(turn_advice["turn_checklist"]),
            "tool_round_limit": turn_profile["tool_round_limit"],
            "allowed_tools": list(turn_advice["allowed_tools"]),
            "turn_status": turn_status,
            "final_response": final_response,
            "validation_status": validation_status,
            "validation_repair_tools": repair_tools,
            "validation_notes": validation_notes,
            "validation_issues": validation_issues,
            "node_traces": self._append_node_trace(
                graph_state,
                "validate_state",
                "State validation completed.",
                {
                    "validation_note_count": len(validation_notes),
                    "validation_issue_count": len(validation_issues),
                    "validation_error_count": sum(
                        1 for issue in validation_issues if issue.get("severity") == "error"
                    ),
                    "validation_warning_count": sum(
                        1 for issue in validation_issues if issue.get("severity") == "warning"
                    ),
                    "validation_status": validation_status,
                    "repair_tool_count": len(repair_tools),
                    "phase": phase,
                    "scene": scene,
                },
            ),
        }

    def _finalize_turn(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = graph_state.get("user_input", "")
        turn_status = str(graph_state.get("turn_status") or "completed")
        if turn_status == "running":
            turn_status = "completed"
        final_response = self.library.localize_game_terms(
            graph_state.get("final_response") or "本回合没有生成可展示的最终回复。"
        )
        tool_results = [
            item if isinstance(item, ToolResult) else ToolResult.model_validate(item)
            for item in graph_state.get("tool_results", [])
        ]

        if turn_status == "failed":
            initial_payload = graph_state.get("initial_game_state") or graph_state.get("game_state", {})
            state = GameState.model_validate(initial_payload)
            state.pending_turn = None
            state.latest_tool_results = []

            player_events = [
                item if isinstance(item, SessionEvent) else SessionEvent.model_validate(item)
                for item in graph_state.get("timeline_append", [])
                if (item.type if isinstance(item, SessionEvent) else dict(item or {}).get("type")) == "player_action"
            ]
            assistant_event = self._build_event(
                event_type="assistant_response",
                summary="DM response",
                content=final_response,
                payload={"message": final_response, "turn_status": "failed"},
            )
            state.timeline.extend(player_events)
            state.timeline.append(assistant_event)
            history_append = [
                ChatMessage(role="user", content=user_input),
                ChatMessage(role="assistant", content=final_response),
            ]
            state.chat_history.extend(history_append)
            timeline_append = [item.model_dump(mode="json") for item in player_events]
            timeline_append.append(assistant_event.model_dump(mode="json"))
            return {
                "game_state": state.model_dump(mode="json"),
                "history_append": [item.model_dump(mode="json") for item in history_append],
                "timeline_append": timeline_append,
                "tool_results": [item.model_dump(mode="json") for item in tool_results],
                "final_response": final_response,
                "turn_status": turn_status,
                "pending_input": {},
                "rag_metadata": dict(graph_state.get("rag_metadata", {})),
                "input_warnings": list(graph_state.get("input_warnings", [])),
                "validation_notes": list(graph_state.get("validation_notes", [])),
                "validation_issues": list(graph_state.get("validation_issues", [])),
                "node_traces": self._append_node_trace(
                    graph_state,
                    "finalize_turn",
                    "Turn finalized without committing failed tool mutations.",
                    {"turn_status": turn_status, "turn_number": state.turn_number},
                ),
            }

        state.pending_turn = None
        if turn_status != "failed":
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
            "turn_status": turn_status,
            "pending_input": {},
            "rag_metadata": dict(graph_state.get("rag_metadata", {})),
            "input_warnings": list(graph_state.get("input_warnings", [])),
            "validation_notes": list(graph_state.get("validation_notes", [])),
            "validation_issues": list(graph_state.get("validation_issues", [])),
            "node_traces": self._append_node_trace(
                graph_state,
                "finalize_turn",
                "Turn finalized.",
                {"turn_status": turn_status, "turn_number": state.turn_number},
            ),
        }

    def _build_graph(self):
        self._require_langgraph()
        builder = StateGraph(DMGraphState)
        builder.add_node("prepare_turn", self._prepare_turn)
        builder.add_node("input_gate", self._input_gate)
        builder.add_node("plan_turn", self._plan_turn)
        builder.add_node("route_phase", self._route_phase)
        builder.add_node("retrieve_rules", self._retrieve_rules)
        builder.add_node("prepare_context", self._prepare_context)
        model_node = self._call_model if self.enable_model else self._draft_response_placeholder
        builder.add_node("draft_response", model_node)
        builder.add_node("execute_tools", self._execute_tools)
        builder.add_node("validate_state", self._validate_state)
        builder.add_node("finalize_turn", self._finalize_turn)
        builder.add_edge(START, "prepare_turn")
        builder.add_edge("prepare_turn", "input_gate")
        builder.add_edge("input_gate", "plan_turn")
        builder.add_edge("plan_turn", "route_phase")
        builder.add_edge("route_phase", "retrieve_rules")
        builder.add_edge("retrieve_rules", "prepare_context")
        builder.add_edge("prepare_context", "draft_response")
        builder.add_conditional_edges(
            "draft_response",
            self._should_continue_after_model,
            {
                "execute_tools": "execute_tools",
                "finalize_turn": "finalize_turn",
            },
        )
        builder.add_edge("execute_tools", "validate_state")
        builder.add_conditional_edges(
            "validate_state",
            self._should_continue_after_validation,
            {
                "draft_response": "draft_response",
                "finalize_turn": "finalize_turn",
            },
        )
        builder.add_edge("finalize_turn", END)
        if self._checkpointer is not None:
            return builder.compile(checkpointer=self._checkpointer)
        return builder.compile()

    @staticmethod
    def _interrupt_values(result: Any) -> List[Any]:
        raw_interrupts = []
        if isinstance(result, dict):
            raw_interrupts = list(result.get("__interrupt__", []))
        else:
            raw_interrupts = list(getattr(result, "interrupts", []) or [])
        values: List[Any] = []
        for item in raw_interrupts:
            values.append(getattr(item, "value", item))
        return values

    @staticmethod
    def _pending_turn_from_interrupt(thread_id: str, payload: Any, original_input: str) -> PendingTurnState:
        if isinstance(payload, dict):
            details = payload.get("details")
            normalized_details = dict(details) if isinstance(details, dict) else {}
            return PendingTurnState(
                thread_id=thread_id,
                kind=str(payload.get("kind") or "clarification"),
                phase=str(payload.get("phase") or ""),
                prompt=str(payload.get("prompt") or payload.get("question") or "需要更多输入后才能继续当前回合。"),
                original_input=original_input,
                details=normalized_details,
            )
        return PendingTurnState(
            thread_id=thread_id,
            prompt=str(payload or "需要更多输入后才能继续当前回合。"),
            original_input=original_input,
        )

    @staticmethod
    def _trace_turn_number(updated_state: GameState, turn_status: str) -> int:
        base = int(updated_state.turn_number or 0)
        if turn_status == "input_required":
            return base + 1
        return base

    def _build_turn_trace(
        self,
        result_payload: Dict[str, Any],
        updated_state: GameState,
        fallback_state: GameState,
        user_input: str,
        thread_id: str,
        turn_status: str,
        response: str,
        pending_input: Dict[str, Any],
        tool_results: List[ToolResult],
    ) -> TurnTrace:
        mode = "resume" if fallback_state.pending_turn else "start"
        return TurnTrace(
            turn_number=self._trace_turn_number(updated_state, turn_status),
            turn_status=turn_status,
            mode=mode,
            thread_id=thread_id,
            phase=str(result_payload.get("phase") or updated_state.campaign.phase or ""),
            scene=str(result_payload.get("scene") or updated_state.scene or ""),
            turn_intent=(
                TurnIntent.model_validate(result_payload.get("turn_intent"))
                if result_payload.get("turn_intent")
                else None
            ),
            turn_profile=str(result_payload.get("turn_profile") or ""),
            tool_round_limit=int(result_payload.get("tool_round_limit", 0) or 0),
            user_input=str(user_input or ""),
            response=str(response or ""),
            input_warnings=list(result_payload.get("input_warnings", [])),
            pending_input=dict(pending_input or {}),
            suggested_tools=list(result_payload.get("suggested_tools", [])),
            allowed_tools=list(result_payload.get("allowed_tools", [])),
            validation_notes=list(result_payload.get("validation_notes", [])),
            validation_issues=[
                item if isinstance(item, ValidationIssue) else ValidationIssue.model_validate(item)
                for item in result_payload.get("validation_issues", [])
            ],
            tool_results=tool_results,
            rag_metadata=dict(result_payload.get("rag_metadata", {})),
            state_delta=dict(result_payload.get("state_delta", {})),
            node_traces=list(result_payload.get("node_traces", [])),
        )

    @staticmethod
    def _append_turn_trace(state: GameState, trace: TurnTrace) -> None:
        state.turn_traces.append(trace)
        state.turn_traces = state.turn_traces[-50:]

    @staticmethod
    def _merge_trace_history(updated_state: GameState, fallback_state: GameState) -> None:
        if not fallback_state.turn_traces:
            return
        existing_ids = {trace.trace_id for trace in updated_state.turn_traces}
        merged = list(updated_state.turn_traces)
        for trace in fallback_state.turn_traces:
            if trace.trace_id not in existing_ids:
                merged.append(trace)
        updated_state.turn_traces = merged[-50:]

    def _result_to_turn_result(self, result: Any, fallback_state: GameState, user_input: str, thread_id: str) -> TurnResult:
        result_payload = result if isinstance(result, dict) else getattr(result, "value", {})
        if not isinstance(result_payload, dict):
            result_payload = {}

        interrupt_values = self._interrupt_values(result)
        updated_state = GameState.model_validate(result_payload.get("game_state", fallback_state.model_dump(mode="json")))
        self._merge_trace_history(updated_state, fallback_state)
        history_append = [
            item if isinstance(item, ChatMessage) else ChatMessage.model_validate(item)
            for item in result_payload.get("history_append", [])
        ]
        timeline_append = [
            item if isinstance(item, SessionEvent) else SessionEvent.model_validate(item)
            for item in result_payload.get("timeline_append", [])
        ]
        tool_results = [
            item if isinstance(item, ToolResult) else ToolResult.model_validate(item)
            for item in result_payload.get("tool_results", [])
        ]
        validation_issues = [
            item if isinstance(item, ValidationIssue) else ValidationIssue.model_validate(item)
            for item in result_payload.get("validation_issues", [])
        ]

        if interrupt_values:
            pending_turn = self._pending_turn_from_interrupt(thread_id, interrupt_values[0], user_input)
            updated_state.pending_turn = pending_turn
            prompt = pending_turn.prompt or "需要更多输入后才能继续当前回合。"
            trace = self._build_turn_trace(
                result_payload=result_payload,
                updated_state=updated_state,
                fallback_state=fallback_state,
                user_input=user_input,
                thread_id=thread_id,
                turn_status="input_required",
                response=prompt,
                pending_input=pending_turn.to_client_payload(),
                tool_results=tool_results,
            )
            self._append_turn_trace(updated_state, trace)
            return TurnResult(
                response=prompt,
                turn_status="input_required",
                pending_input=pending_turn.to_client_payload(),
                turn_trace=trace,
                history=updated_state.chat_history,
                history_append=[],
                timeline=updated_state.timeline,
                timeline_append=timeline_append,
                tool_results=tool_results,
                rag_metadata=dict(result_payload.get("rag_metadata", {})),
                input_warnings=list(result_payload.get("input_warnings", [])),
                validation_issues=validation_issues,
                state_delta=dict(result_payload.get("state_delta", {})),
                game_state=updated_state,
            )

        updated_state.pending_turn = None
        trace = self._build_turn_trace(
            result_payload=result_payload,
            updated_state=updated_state,
            fallback_state=fallback_state,
            user_input=user_input,
            thread_id=thread_id,
            turn_status=str(result_payload.get("turn_status") or "completed"),
            response=str(result_payload.get("final_response", "")),
            pending_input=dict(result_payload.get("pending_input", {})),
            tool_results=tool_results,
        )
        self._append_turn_trace(updated_state, trace)
        return TurnResult(
            response=result_payload.get("final_response", ""),
            turn_status=str(result_payload.get("turn_status") or "completed"),
            pending_input=dict(result_payload.get("pending_input", {})),
            turn_trace=trace,
            history=updated_state.chat_history,
            history_append=history_append,
            timeline=updated_state.timeline,
            timeline_append=timeline_append,
            tool_results=tool_results,
            rag_metadata=dict(result_payload.get("rag_metadata", {})),
            input_warnings=list(result_payload.get("input_warnings", [])),
            validation_issues=validation_issues,
            state_delta=dict(result_payload.get("state_delta", {})),
            game_state=updated_state,
        )

    def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        if self._graph is None:
            self._graph = self._build_graph()
        if state.pending_turn:
            raise RuntimeError("This game already has a pending turn waiting for more input.")

        thread_id = self._new_thread_id(state)
        result = self._graph.invoke(
            {
                "game_state": state.model_dump(mode="json"),
                "initial_game_state": state.model_dump(mode="json"),
                "user_input": user_input,
            },
            config=self._graph_config(thread_id),
        )
        return self._result_to_turn_result(result, state, user_input, thread_id)

    def resume_turn(self, state: GameState, user_input: str) -> TurnResult:
        if self._graph is None:
            self._graph = self._build_graph()
        if not state.pending_turn:
            raise RuntimeError("This game does not have a pending turn to resume.")
        if Command is None:
            raise RuntimeError("LangGraph resume support is unavailable in this runtime.")

        thread_id = state.pending_turn.thread_id
        try:
            result = self._graph.invoke(
                Command(resume={"message": user_input}),
                config=self._graph_config(thread_id),
            )
        except Exception as exc:
            error_text = str(exc).lower()
            if not any(token in error_text for token in ("checkpoint", "thread", "resume", "interrupt")):
                raise
            fallback_state = state.model_copy(deep=True)
            fallback_state.pending_turn = None
            return self.run_turn(fallback_state, user_input)
        return self._result_to_turn_result(result, state, user_input, thread_id)
