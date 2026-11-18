"""Model-facing schemas for the registered game tools."""

from typing import Any, Dict, List

from world_state import WORLD_TOOLS


LANGGRAPH_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    *(
        {"name": name, "description": command.__doc__, "parameters": command.model_json_schema()}
        for name, command in WORLD_TOOLS.items()
    ),
    {"name":"check_spell_sequence", "description":"Before executing multiple spells in one player instruction, check the whole intended sequence. This is read-only and rolls no dice. A conflict must be explained through report_rule_conflict so the player can revise. preserve_effects=True checks whether earlier effects would be ended by later spells; use false only when the player explicitly intends that consequence.",
     "parameters":{"type":"object","properties":{"caster_ref":{"type":"string"},"preserve_effects":{"type":"boolean","default":True},
         "casts":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"object","properties":{"spell_name":{"type":"string"},"slot_level":{"type":"integer"},"target_refs":{"type":"array","items":{"type":"string"}}},"required":["spell_name"]}}},"required":["caster_ref","casts"]}},

    {"name": "register_scene_actor", "description": "Register an already established NPC as a rules target without starting combat. Reuse a known template or provide all six verified ability scores and creature type; never infer a saving throw from narrative mood. Existing identities and resources are not reset.",
     "parameters": {"type": "object", "properties": {"name": {"type":"string"}, "source":{"type":"string"},
         "creature_type":{"type":"string"}, "template_ref":{"type":"string"},
         "ability_scores":{"type":"object","additionalProperties":{"type":"integer"}},
         "hp_max":{"type":"integer","minimum":1},"ac":{"type":"integer","minimum":1},
         "saving_throws":{"type":"object","additionalProperties":{"type":"integer"}},
         "condition_immunities":{"type":"array","items":{"type":"string"}}},"required":["name","source"]}},
    {"name": "report_rule_conflict", "description": "Stop this attempted action and explain a concrete rule conflict so the player can revise it. All staged gameplay changes are rolled back. Supply only a short player-facing explanation, optionally a correction; no scene narration or filler. Narrative length preferences do not apply. Do not blame player rules for technical failures or demand confirmation of already-recorded spell effects. State inspection is the DM's responsibility; name a concrete rule conflict.",
     "parameters": {"type":"object","properties":{"message":{"type":"string","minLength":1,"maxLength":1200}},"required":["message"]}},

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
        "name": "generate_ability_scores",
        "description": (
            "Prepare authoritative D&D ability scores during character setup. Use point_buy to validate six supplied "
            "scores, standard_array for the configured array, or rolled for six 4d6-drop-lowest results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["point_buy", "standard_array", "rolled"],
                },
                "scores": {
                    "type": "object",
                    "properties": {
                        "strength": {"type": "integer"},
                        "dexterity": {"type": "integer"},
                        "constitution": {"type": "integer"},
                        "intelligence": {"type": "integer"},
                        "wisdom": {"type": "integer"},
                        "charisma": {"type": "integer"},
                    },
                },
            },
            "required": ["method"],
        },
    },
    {
        "name": "list_character_options",
        "description": (
            "Read the authoritative character builder catalog: ability generation config, species, backgrounds, "
            "origin feats, and classes. Always consult this before proposing build choices; never invent options."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                "subclass_id": {"type": "string", "default": ""},
                "category": {
                    "type": "string",
                    "enum": ["all", "species", "backgrounds", "origin_feats", "classes", "ability_generation"],
                    "default": "all",
                },
                "name": {
                    "type": "string",
                    "default": "",
                    "description": "Optional exact name to expand one species, background, or class definition.",
                },
            },
        },
    },
    {
        "name": "list_class_spells",
        "description": (
            "Read the local spell library. Omit all arguments to list spellcasting classes, pass class_name for that "
            "class spell list, or pass spell_name for one spell's full details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {"type": "string", "default": ""},
                "max_level": {"type": "integer", "description": "Optional inclusive spell level cap."},
                "spell_name": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "list_starter_equipment",
        "description": (
            "Read starter equipment packages, embedded choice groups, custom purchase budget, and the shop catalog "
            "for one class. Use the returned option and choice ids when creating a character."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "class_name": {"type": "string"},
                "option_id": {"type": "string", "default": ""},
            },
            "required": ["class_name"],
        },
    },
    {
        "name": "validate_character_sheet",
        "description": (
            "Validate one existing party member against the authoritative build rules and report concrete errors. "
            "Read-only; never mutates the sheet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "character_ref": {"type": "string"},
            },
            "required": ["character_ref"],
        },
    },
    {
        "name": "create_party_character",
        "description": (
            "Create one validated party member in the current game. Every field must come from list_character_options, "
            "list_class_spells, and list_starter_equipment. Ability scores must satisfy the chosen generation method; "
            "the character is rejected instead of partially saved when validation fails."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "class_name": {"type": "string"},
                "species": {"type": "string", "default": "Human"},
                "background_name": {"type": "string", "default": ""},
                "ability_scores": {
                    "type": "object",
                    "properties": {
                        "strength": {"type": "integer"},
                        "dexterity": {"type": "integer"},
                        "constitution": {"type": "integer"},
                        "intelligence": {"type": "integer"},
                        "wisdom": {"type": "integer"},
                        "charisma": {"type": "integer"},
                    },
                },
                "ability_generation_method": {
                    "type": "string",
                    "enum": ["point_buy", "standard_array", "rolled"],
                    "default": "standard_array",
                },
                "skill_proficiencies": {"type": "array", "items": {"type": "string"}, "default": []},
                "cantrips": {"type": "array", "items": {"type": "string"}, "default": []},
                "prepared_spells": {"type": "array", "items": {"type": "string"}, "default": []},
                "starter_option_id": {"type": "string", "default": ""},
                "starter_choice_ids": {"type": "object", "default": {}},
                "alignment": {"type": "string", "default": "Neutral"},
                "set_active": {"type": "boolean", "default": True},
                "level": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                "subclass_id": {"type": "string", "default": ""},
                "subclass_spell_variant": {"type": "string", "default": ""},
                "bonus_spells": {"type": "array", "items": {"type": "string"}},
                "ability_increases": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}, "description": "At each earned ASI level, choose two ability names for +1 each (same name twice grants +2)."},
                "expertise_skills": {"type": "array", "items": {"type": "string"}},
                "mystic_arcanum": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["name", "class_name"],
        },
    },
    {
        "name": "request_player_choice",
        "description": (
            "Pause for the player only when a consequential in-world branch genuinely lacks their decision. "
            "When the turn must wait for that decision, call this tool instead of asking for the choice in normal prose. "
            "Provide a natural prompt and two to four concrete options. Never use this for an action the player "
            "already stated, deterministic rules resolution, DM bookkeeping, or generic confirmation of a state write. "
            "Call it before any state mutation whose outcome depends on the missing choice."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["prompt", "options"],
        },
    },
    {
        "name": "select_adventure_hook",
        "description": (
            "Lock in one adventure hook already offered in campaign.available_adventures and advance the campaign into "
            "exploration with chapter one. Only valid once the party exists and no adventure is selected yet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "adventure_id": {"type": "string"},
            },
            "required": ["adventure_id"],
        },
    },
    {
        "name": "roll_dice",
        "description": "Roll dice locally for checks, attacks, damage, healing, or random outcomes. Mark genuine DM dark rolls as hidden.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "reason": {"type": "string", "default": ""},
                "visibility": {
                    "type": "string",
                    "enum": ["public", "hidden"],
                    "default": "public",
                    "description": "Whether the player may see this roll result. Use hidden only for genuine DM dark rolls.",
                },
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
        "name": "adjust_currency",
        "description": "Receive or pay ordinary money in the character inventory, the only money ledger. Positive amount receives; negative amount pays. CP/SP/EP/GP/PP are exact denominations. The runtime checks funds and makes equivalent change if needed. Never use adjust_hp, prose, or a separate gold balance for payment; never convert gems/collectibles automatically. Report a currency only once, not also through add_inventory_item.",
        "parameters": {"type":"object", "properties": {
            "character_ref":{"type":"string"}, "amount":{"type":"integer"},
            "denomination":{"type":"string", "description":"cp/sp/ep/gp/pp or exact Chinese coin name"},
            "reason":{"type":"string"}}, "required":["character_ref","amount","denomination","reason"]},
    },
    {
        "name": "add_inventory_item",
        "description": (
            "For ordinary money prefer adjust_currency; this tool can receive named coins but cannot pay. Never record the same reward twice. Add a named item, clue, or loot entry to a character inventory. Known items are enriched from the "
            "rules catalog. For other usable items, look up their rules and record confirmed damage dice/type, "
            "healing dice, or effect conditions; identify the spell and level on known scrolls. "
            "Leave genuinely unidentified effects unknown, never fabricate them."
        ),
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
                "rules_name": {"type": "string", "default": "", "description": "Optional exact catalog name for descriptive loot names, e.g. Scimitar for a goblin scimitar. Known catalog effects are supplied by the rules layer."},
                "damage_expression": {"type": "string", "default": "", "description": "Confirmed custom damage dice, e.g. 1d6+2. Never invent missing rules."},
                "damage_type": {"type": "string", "default": ""},
                "healing_expression": {"type": "string", "default": "", "description": "Confirmed healing amount, e.g. 2d4+2."},
                "effect_description": {"type": "string", "default": "", "description": "Confirmed use effects and conditions, including per-target/per-hit dice qualifiers. Look up unknown item rules first."},
                "properties": {"type": "array", "items": {"type": "string"}, "default": []},
                "spell_name": {"type": "string", "default": "", "description": "Exact spell on a scroll, if known; do not guess unidentified scrolls."},
                "spell_level": {"type": "integer", "minimum": 0, "maximum": 9, "description": "Spell level recorded on the scroll, if known."},
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
        "description": "Bardic Inspiration MUST specify target_ref, distance_feet and target_can_perceive; grants a real expiring recipient die. Do not finish the encounter before resolving declared legal bonus actions. Record a class feature, monster feature, trait, bonus action, or reaction use, consuming the chosen turn slot and optional character resource.",
        "parameters": {
            "type": "object",
            "properties": {
                "actor_ref": {"type": "string"},
                "feature_name": {"type": "string"},
                "target_ref": {"type":"string"},
                "distance_feet": {"type":"number", "minimum":0},
                "target_can_perceive": {"type":"boolean"},
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
        "description": (
            "Persist a named clue, document, or investigation artifact as structured evidence. Call it when "
            "authoritative context establishes that the party obtains, accepts, or keeps the artifact and no "
            "matching evidence record exists."
        ),
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
                "surprised_refs": {"type": "array", "items": {"type": "string"}, "default": [], "description": "Names of newly added enemies or party character names/ids caught unaware by combat starting. Decide BEFORE initiative; never grant a skipped turn."},
                "surprise_reason": {"type": "string", "default": "", "description": "Established reason those participants are unaware of danger; required when surprised_refs is nonempty."},
                "approach_reason": {"type": "string", "default": "", "description": "For a requested ambush that cannot use Hide, explain the observed lack of cover or enemy awareness. Do not claim a successful hide without hide_actor."},
                "surprise_basis": {"type": "string", "enum": ["hidden", "other"], "default": "hidden", "description": "hidden requires successful concealment for a player ambush. other requires approach_reason explaining an independently established unaware combat start (e.g. an unexpected betrayal); it is not a way to turn a failed Hide into success."},
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
        "description": "Resolve an attack roll and damage. For throwing a held item set attack_mode=thrown, distance_feet, physical damage_type and reason; keep attack_name exactly the inventory name. Non-Thrown weapons use improvised 1d4, not melee math. Never repeat a successful attack. For a spell attack, pass the cast_id returned by cast_spell; the runtime derives spell math and does not spend the action twice. Resolve every remaining beam before final narration.",
        "parameters": {
            "type": "object",
            "properties": {
                "attacker_sees_invisible": {"type": "boolean", "default": False, "description": "Only true for an established sense that sees an Invisible target; explain in reason."},
                "target_sees_invisible": {"type": "boolean", "default": False, "description": "Only true when the target can actually see the Invisible attacker; explain in reason."},
                "attacker_ref": {"type": "string"},
                "cast_id": {"type": "string", "default": ""},
                "target_ref": {"type": "string"},
                "attack_name": {"type": "string", "default": ""},
                "attack_mode": {"type":"string", "enum":["normal","melee","thrown","improvised_melee"], "default":"normal"},
                "distance_feet": {"type":"number", "minimum":0},
                "equivalent_weapon": {"type":"string", "description":"Only for established similarity to a catalogue weapon; explain in reason."},
                "attack_bonus": {"type": "integer"},
                "damage_expression": {"type": "string"},
                "damage_type": {"type": "string", "default": ""},
                "resolution_mode": {"type": "string", "default": "normal"},
                "roll_mode": {"type": "string", "enum": ["normal", "advantage", "disadvantage"], "default": "normal"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["attacker_ref", "target_ref"],
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
                "dc": {"type": "integer", "default": 0},
                "roll_mode": {"type": "string", "enum": ["normal", "advantage", "disadvantage"], "default": "normal"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["actor_ref", "skill_name"],
        },
    },
    {
        "name": "roll_saving_throw",
        "description": (
            "Resolve a saving throw for an existing target. For a character spell, pass source_ref and spell_name; "
            "the runtime derives the spell save DC and required ability from authoritative character and spell data. "
            "Use an explicit dc only for environmental or non-character effects."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_ref": {"type": "string"},
                "save_name": {"type": "string"},
                "dc": {"type": "integer", "default": 0},
                "source_ref": {"type": "string", "default": ""},
                "spell_name": {"type": "string", "default": ""},
                "roll_mode": {"type": "string", "enum": ["normal", "advantage", "disadvantage"], "default": "normal"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["target_ref", "save_name"],
        },
    },
    {
        "name": "cast_spell",
        "description": (
            "Validate spell access and spend a spell slot if required. The successful result includes the authoritative "
            "spell desc. If cast_id is present, call attack_target with that cast_id for each attack_count; do not invent "
            "spell bonuses or use a weapon profile for the spell. Registered effect rules require explicit valid targets and resolve saves, effects, and their triggers atomically. Do not separately roll their saves or apply their conditions. Unknown required mechanics are rejected before resources are spent; do not describe bookkeeping alone as a resolved spell."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "caster_ref": {"type": "string"},
                "spell_name": {"type": "string"},
                "slot_level": {"type": "integer", "default": 0},
                "target_ref": {"type": "string", "default": ""},
                "target_refs": {"type": "array", "items": {"type": "string"}, "description": "Distinct established targets in spell range; target limits and creature restrictions come from the spell rules."},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["caster_ref", "spell_name"],
        },
    },
    {
        "name": "end_concentration",
        "description": "End the specified character's concentration and all effects owned by it. Only do this for a stated intent or established rules cause; no action slot is consumed.",
        "parameters": {"type":"object", "properties":{"caster_ref":{"type":"string"}}, "required":["caster_ref"]},
    },
    {
        "name": "advance_time",
        "description": "Outside active combat, advance established in-world elapsed time in seconds; resolves ongoing saves and expirations. Never use wall-clock waiting or bypass initiative.",
        "parameters": {"type":"object", "properties":{"seconds":{"type":"integer","minimum":1,"maximum":86400},"reason":{"type":"string"}}, "required":["seconds","reason"]},
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
        "name": "estimate_encounter_difficulty",
        "description": (
            "Score an encounter against the party's 2024 XP budget and return the low/moderate/high thresholds. "
            "Omit enemies to score the currently active encounter. Read-only planning aid; it never changes state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "enemies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "challenge_rating": {"type": "string"},
                            "count": {"type": "integer", "default": 1},
                        },
                        "required": ["challenge_rating"],
                    },
                    "default": [],
                },
                "party_levels": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "default": [],
                    "description": "Optional override; defaults to the live party levels.",
                },
            },
        },
    },
    {
        "name": "estimate_monster_cr",
        "description": (
            "Derive a challenge rating from defensive and offensive statistics before saving or spawning a custom "
            "monster. Pass save_dc instead of attack_bonus when the creature's main threat forces saving throws. "
            "Read-only; pass monster_ref to compare against a template's declared CR."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hp": {"type": "integer"},
                "ac": {"type": "integer"},
                "damage_per_round": {"type": "integer"},
                "attack_bonus": {"type": "integer", "default": 0},
                "save_dc": {"type": "integer", "default": 0},
                "monster_ref": {"type": "string", "default": ""},
            },
            "required": ["hp", "ac", "damage_per_round"],
        },
    },
    {
        "name": "remove_combatant",
        "description": (
            "Remove one non-party combatant from the active encounter, for example a creature that flees, is dismissed, "
            "or was spawned by mistake. Party members cannot be removed with this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "combatant_ref": {"type": "string"},
            },
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


LANGGRAPH_TOOL_SCHEMAS.extend([
    {"name": "hide_actor", "description": "Take the 2024 Hide action: require established cover and being out of every enemy's sight; roll authoritative DC15 Dexterity (Stealth). Success records a Hide-specific Invisible state and detection DC. In combat this spends an action even on a failed check; it does not grant Sneak Attack damage.",
     "parameters": {"type": "object", "properties": {
         "actor_ref": {"type": "string"},
         "cover": {"type": "string", "enum": ["none", "heavily_obscured", "three_quarters", "total"]},
         "observed": {"type": "boolean", "description": "Whether any enemy can currently see the actor; base this on established scene facts."},
         "reason": {"type": "string"},
         "roll_mode": {"type": "string", "enum": ["normal", "advantage", "disadvantage"], "default": "normal"}},
         "required": ["actor_ref", "cover", "observed", "reason"]}},
    {"name": "search_hidden", "description": "Attempt to detect an actor with active Hide state. Active Wisdom (Perception) search spends an action; passive=true uses authoritative passive perception without a roll or action when the DM judges it applicable. An enemy finding the hider ends Hide, not magical invisibility.",
     "parameters": {"type": "object", "properties": {
         "actor_ref": {"type": "string"}, "target_ref": {"type": "string"},
         "passive": {"type": "boolean", "default": False},
         "roll_mode": {"type": "string", "enum": ["normal", "advantage", "disadvantage"], "default": "normal"}},
         "required": ["actor_ref", "target_ref"]}},
    {"name": "end_hiding", "description": "End Hide when established noise above a whisper, enemy sight/special senses, exposure or a voluntary reveal invalidates it. Give the concrete scene reason. Attacks and verbal spell casts already end Hide automatically. Does not remove magical invisibility.",
     "parameters": {"type": "object", "properties": {"actor_ref": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["actor_ref", "reason"]}},
])
