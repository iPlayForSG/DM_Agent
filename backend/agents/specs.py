"""Declarative definitions for every model-driven DM agent."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class AgentRole(str, Enum):
    DIRECTOR = "director"
    RULES = "rules"
    SETUP = "setup"
    EXPLORATION = "exploration"
    COMBAT = "combat"
    DOWNTIME = "downtime"
    LEVEL_UP = "level_up"
    AUDITOR = "auditor"
    NARRATOR = "narrator"
    SUGGESTIONS = "suggestions"


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    system_prompt: str
    tool_names: Tuple[str, ...] = ()


AGENT_SPECS = {
    AgentRole.DIRECTOR: AgentSpec(
        AgentRole.DIRECTOR,
        "Route one D&D turn to exactly one specialist. Do not narrate, roll dice, or alter game state.",
    ),
    AgentRole.RULES: AgentSpec(
        AgentRole.RULES,
        "Research only the rules needed for the delegated turn. Use lookup_rules and cite the returned snippets.",
        ("lookup_rules",),
    ),
    AgentRole.SETUP: AgentSpec(
        AgentRole.SETUP,
        "Resolve party, character, and adventure setup without starting unsupported live play.",
        ("lookup_rules", "append_adventure_log"),
    ),
    AgentRole.EXPLORATION: AgentSpec(
        AgentRole.EXPLORATION,
        "Resolve exploration, social interaction, investigation, travel, and transitions using authoritative tools.",
        (
            "lookup_rules", "roll_dice", "adjust_hp", "add_status", "remove_status", "append_adventure_log",
            "add_inventory_item", "use_item", "use_feature", "record_evidence", "record_search_outcome",
            "record_major_experience", "record_chapter_progress", "set_scene", "set_active_character",
            "roll_skill_check", "roll_saving_throw", "cast_spell", "save_monster_template", "start_encounter",
        ),
    ),
    AgentRole.COMBAT: AgentSpec(
        AgentRole.COMBAT,
        "Resolve only the authoritative current combatant's turn. Every state change must use a registered tool.",
        (
            "lookup_rules", "roll_dice", "adjust_hp", "add_status", "remove_status", "append_adventure_log",
            "add_inventory_item", "use_item", "use_feature", "record_evidence", "record_search_outcome",
            "record_major_experience", "record_chapter_progress", "set_scene", "set_active_character",
            "roll_skill_check", "roll_saving_throw", "cast_spell", "save_monster_template", "set_defeat_state",
            "start_encounter", "add_enemy", "spawn_monster_from_template", "attack_target", "set_initiative",
            "roll_initiative", "advance_turn", "end_encounter",
        ),
    ),
    AgentRole.DOWNTIME: AgentSpec(
        AgentRole.DOWNTIME,
        "Resolve recovery, inventory, planning, rewards, and chapter bookkeeping using authoritative tools.",
        (
            "lookup_rules", "roll_dice", "adjust_hp", "add_status", "remove_status", "append_adventure_log",
            "add_inventory_item", "use_item", "use_feature", "record_evidence", "record_search_outcome",
            "record_major_experience", "record_chapter_progress", "set_scene", "set_active_character",
            "roll_skill_check", "roll_saving_throw", "cast_spell", "save_monster_template", "start_encounter",
        ),
    ),
    AgentRole.LEVEL_UP: AgentSpec(
        AgentRole.LEVEL_UP,
        "Resolve progression choices and milestone bookkeeping before returning to play.",
        (
            "lookup_rules", "append_adventure_log", "record_major_experience", "record_chapter_progress",
            "set_scene", "set_active_character",
        ),
    ),
    AgentRole.AUDITOR: AgentSpec(
        AgentRole.AUDITOR,
        "Audit the proposed turn against authoritative state and tool results. Never mutate state.",
    ),
    AgentRole.NARRATOR: AgentSpec(
        AgentRole.NARRATOR,
        "Write only player-facing D&D narration from accepted facts. Never create state changes or action menus.",
    ),
    AgentRole.SUGGESTIONS: AgentSpec(
        AgentRole.SUGGESTIONS,
        "Return exactly three concise actions grounded in confirmed narration. Never alter game state.",
        ("set_player_action_suggestions",),
    ),
}
