"""Runtime agent identities and phase capability sets."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple


class AgentRole(str, Enum):
    DM = "dm"
    SUGGESTIONS = "suggestions"


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    system_prompt: str
    tool_names: Tuple[str, ...] = ()


SETUP_CATALOG_TOOL_NAMES = (
    "list_character_options",
    "list_class_spells",
    "list_starter_equipment",
    "validate_character_sheet",
)

PLAYER_CHOICE_TOOL_NAMES = ("request_player_choice",)

BASE_DM_TOOL_NAMES = (
    *PLAYER_CHOICE_TOOL_NAMES,
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
    "estimate_encounter_difficulty",
    "estimate_monster_cr",
)

COMBAT_DM_TOOL_NAMES = (
    "set_defeat_state",
    "start_encounter",
    "add_enemy",
    "spawn_monster_from_template",
    "attack_target",
    "set_initiative",
    "roll_initiative",
    "advance_turn",
    "remove_combatant",
    "end_encounter",
)

PHASE_CAPABILITY_TOOL_NAMES: Dict[str, Tuple[str, ...]] = {
    "party_creation": (
        *PLAYER_CHOICE_TOOL_NAMES,
        "lookup_rules",
        "generate_ability_scores",
        *SETUP_CATALOG_TOOL_NAMES,
        "create_party_character",
    ),
    "character_creation": (
        *PLAYER_CHOICE_TOOL_NAMES,
        "lookup_rules",
        "generate_ability_scores",
        *SETUP_CATALOG_TOOL_NAMES,
        "create_party_character",
    ),
    "adventure_selection": (
        *PLAYER_CHOICE_TOOL_NAMES,
        "lookup_rules",
        "append_adventure_log",
        *SETUP_CATALOG_TOOL_NAMES,
        "select_adventure_hook",
    ),
    "exploration": (*BASE_DM_TOOL_NAMES, "start_encounter"),
    "combat": (*BASE_DM_TOOL_NAMES, *COMBAT_DM_TOOL_NAMES),
    "downtime": (*BASE_DM_TOOL_NAMES, "start_encounter"),
    "level_up": (
        *PLAYER_CHOICE_TOOL_NAMES,
        "lookup_rules",
        "append_adventure_log",
        "record_major_experience",
        "record_chapter_progress",
        "set_scene",
        "set_active_character",
        "list_character_options",
        "list_class_spells",
        "validate_character_sheet",
    ),
}

DM_TOOL_NAMES = tuple(
    dict.fromkeys(
        tool_name
        for phase_tools in PHASE_CAPABILITY_TOOL_NAMES.values()
        for tool_name in phase_tools
    )
)


AGENT_SPECS = {
    AgentRole.DM: AgentSpec(
        AgentRole.DM,
        "Act as the persistent Dungeon Master for the whole campaign. Preserve continuity, adjudicate only through "
        "authoritative tools, and narrate the resolved outcome in your own voice. The current phase and allowed tool "
        "set are capability constraints, not a handoff to another persona.",
        DM_TOOL_NAMES,
    ),
    AgentRole.SUGGESTIONS: AgentSpec(
        AgentRole.SUGGESTIONS,
        "Return exactly three concise actions grounded in confirmed narration. Never alter game state.",
        ("set_player_action_suggestions",),
    ),
}
