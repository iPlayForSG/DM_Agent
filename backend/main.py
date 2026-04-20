"""FastAPI entrypoint exposing builder, campaign, encounter, and local action routes."""

import re
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import DMAgent
from action_service import GameActionService
from adventure_service import generate_initial_adventures
from game_logic import GameLogic
from library import Library
from models import Character, GameState, MonsterTemplate
from rules_catalog import RuleCatalog, proficiency_bonus_for_level
from storage import CharacterStorage, GameStorage, MonsterStorage

app = FastAPI(title="D&D 2024 DM Agent")

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
rule_catalog = RuleCatalog()
action_service = GameActionService()


# Request payloads stay intentionally thin and map 1:1 to frontend form state.
class ChatRequest(BaseModel):
    message: str


class CreateGameRequest(BaseModel):
    game_id: str
    title: str = ""
    character_ids: List[str] = Field(default_factory=list)
    character_names: List[str] = Field(default_factory=list)


class SelectAdventureRequest(BaseModel):
    adventure_id: str


class AttackActionRequest(BaseModel):
    attacker_ref: str
    target_ref: str
    attack_bonus: int
    damage_expression: str
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
    dc: int
    modifier: int | None = None


class CastSpellActionRequest(BaseModel):
    caster_ref: str
    spell_name: str
    slot_level: int = 0


class UseItemActionRequest(BaseModel):
    user_ref: str
    item_name: str
    quantity: int = 1


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


# Small payload builders keep the route handlers mostly orchestration-only.
def health_payload():
    return {
        "status": "ok",
        "rag_enabled": agent.rag_engine.is_ready(),
        "rag_status": agent.rag_engine.status_payload(),
    }


def classes_payload():
    return {"classes": library.get_all_classes()}


def spells_payload(class_name: str):
    return {"spells": library.get_spells_by_class(rule_catalog.resolve_spell_library_key(class_name))}


def builder_payload():
    return rule_catalog.get_builder_catalog()


def characters_payload():
    summaries = [summary.model_dump(mode="json") for summary in char_storage.list_character_summaries()]
    return {
        "characters": summaries,
        "names": [summary["name"] for summary in summaries],
    }


def monsters_payload():
    summaries = [summary.model_dump(mode="json") for summary in monster_storage.list_monster_summaries()]
    return {
        "monsters": summaries,
        "names": [summary["name"] for summary in summaries],
    }


def games_payload():
    summaries = [summary.model_dump(mode="json") for summary in game_storage.list_game_summaries()]
    return {
        "games": summaries,
        "ids": [summary["game_id"] for summary in summaries],
    }


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
                "attack_bonus": attack_bonus,
                "damage_expression": item.damage_expression,
                "damage_type": item.damage_type,
                "source": "inventory",
            }
        )
    return attacks


def _derive_monster_attack_options(monster):
    attacks = []
    for action in monster.actions:
        parsed = _parse_monster_action(action.description)
        if parsed:
            attacks.append({"name": action.name, **parsed})
    return attacks


def _build_spell_options(character: Character):
    options = []

    for spell_name in character.spells.cantrips:
        details = library.get_spell_details(spell_name) or {}
        options.append(
            {
                "name": spell_name,
                "level": int(details.get("level", 0)),
                "school": details.get("school", ""),
                "requires_slot": False,
                "available": True,
                "available_slot_levels": [],
            }
        )

    for spell_name in character.spells.prepared:
        details = library.get_spell_details(spell_name) or {}
        spell_level = int(details.get("level", 0))
        available_slot_levels = [
            int(level)
            for level, slot in character.spells.slots.items()
            if int(level) >= spell_level and slot.total - slot.used > 0
        ]
        options.append(
            {
                "name": spell_name,
                "level": spell_level,
                "school": details.get("school", ""),
                "requires_slot": spell_level > 0,
                "available": spell_level == 0 or bool(available_slot_levels),
                "available_slot_levels": available_slot_levels,
            }
        )

    return sorted(options, key=lambda item: (item["level"], item["name"]))


def _parse_monster_action(text: str):
    normalized = text.strip()
    if not normalized:
        return None

    attack_bonus = None
    damage_expression = ""
    damage_type = ""

    match_bonus = re.search(r"([+-]\d+)\s*to hit", normalized, re.IGNORECASE)
    if match_bonus:
        attack_bonus = int(match_bonus.group(1))

    match_damage = re.search(r"(\d+d\d+(?:[+-]\d+)?)", normalized, re.IGNORECASE)
    if match_damage:
        damage_expression = match_damage.group(1)

    match_type = re.search(r"(slashing|piercing|bludgeoning|fire|cold|lightning|thunder|acid|poison|necrotic|radiant|force|psychic)", normalized, re.IGNORECASE)
    if match_type:
        damage_type = match_type.group(1).lower()

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
        actors.append(
            {
                "ref": character.character_id,
                "name": character.name,
                "type": "character",
                "side": "party",
                "is_current_actor": is_current_actor,
                "defeat_state": character.defeat_state,
                "gold_gp": character.gold_gp,
                "starter_option_id": character.starter_option_id,
                "spells": {
                    "cantrips": list(character.spells.cantrips),
                    "prepared": list(character.spells.prepared),
                    "options": _build_spell_options(character),
                    "slots": {
                        level: {"total": slot.total, "used": slot.used}
                        for level, slot in character.spells.slots.items()
                    },
                },
                "items": [
                    {
                        "name": item.name,
                        "quantity": item.quantity,
                        "type": item.type,
                    }
                    for item in character.inventory
                ],
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
                    "initiative": combatant.initiative,
                    "monster_template_id": combatant.monster_template_id,
                    "skills": sorted(combatant.skills.keys()),
                    "saves": sorted(combatant.saving_throws.keys()),
                    "attacks": [],
                }
            )

            if combatant.monster_template_id:
                monster = monster_storage.load_monster(combatant.monster_template_id)
                if monster:
                    actors[-1]["attacks"] = _derive_monster_attack_options(monster)

    return {
        "phase": state.campaign.phase,
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


def _roll_missing_initiative(logic, encounter):
    for combatant_id in encounter.initiative_order:
        combatant = encounter.combatants.get(combatant_id)
        if combatant and combatant.initiative is None:
            logic.roll_initiative(combatant.combatant_id)


@app.get("/api/v1/health")
async def health_check():
    return health_payload()


@app.get("/api/v1/config")
async def get_config():
    return {
        "rag_enabled": agent.rag_engine.is_ready(),
        "rag_status": agent.rag_engine.status_payload(),
        "chat_backend": agent.backend_name,
        "model_provider": "openai-compatible",
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


@app.post("/api/v1/rag/search")
async def search_rules(req: RuleLookupRequest):
    snippets = agent.rag_engine.search(req.query, n_results=req.n_results)
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


@app.get("/api/v1/characters/{identifier}")
async def get_character(identifier: str):
    char = char_storage.load_character(identifier)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    return char


@app.get("/api/v1/monsters")
async def list_monsters():
    return monsters_payload()


@app.post("/api/v1/monsters")
async def create_monster(monster: MonsterTemplate):
    monster_storage.save_monster(monster)
    return {"status": "saved", "monster": monster.to_summary().model_dump(mode="json")}


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
    return {"status": "created", "game": new_state.to_summary().model_dump(mode="json")}


@app.get("/api/v1/games/{game_id}")
async def get_game_state(game_id: str) -> GameState:
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state


@app.get("/api/v1/games/{game_id}/action-options")
async def get_game_action_options(game_id: str):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return action_options_payload(state)


@app.post("/api/v1/games/{game_id}/select-adventure")
async def select_adventure(game_id: str, req: SelectAdventureRequest):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")

    selected = None
    for hook in state.campaign.available_adventures:
        if hook.adventure_id == req.adventure_id:
            selected = hook
            break

    if not selected:
        raise HTTPException(status_code=404, detail="Adventure option not found")

    state.campaign.selected_adventure_id = selected.adventure_id
    state.campaign.phase = "exploration"
    state.campaign.setup_complete = True
    state.scene = "exploration"
    state.adventure_log.append(f"Selected adventure: {selected.title}")
    game_storage.save_game(game_id, state)
    return {"status": "selected", "adventure": selected.model_dump(mode="json"), "game_state": state}


@app.post("/api/v1/games/{game_id}/encounters/start")
async def start_encounter(game_id: str, req: StartEncounterRequest):
    state = _load_game_or_404(game_id)
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
    state = _load_game_or_404(game_id)
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
    state = _load_game_or_404(game_id)
    monster = monster_storage.load_monster(req.monster_id)
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
    state = _load_game_or_404(game_id)
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
    state = _load_game_or_404(game_id)
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
    state = _load_game_or_404(game_id)
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
    state = _load_game_or_404(game_id)
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


@app.post("/api/v1/games/{game_id}/turns")
async def run_turn(game_id: str, req: ChatRequest):
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")

    try:
        result = await agent.run_turn(state, req.message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DM agent request failed: {exc}") from exc

    game_storage.save_game(game_id, result.game_state)
    return result


def _load_game_or_404(game_id: str) -> GameState:
    state = game_storage.load_game(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state


# Deterministic local action routes complement the freer LangGraph text turns.
@app.post("/api/v1/games/{game_id}/actions/advance-turn")
async def advance_turn_action(game_id: str):
    state = _load_game_or_404(game_id)
    try:
        result = action_service.advance_turn(state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/attack")
async def attack_action(game_id: str, req: AttackActionRequest):
    state = _load_game_or_404(game_id)
    try:
        result = action_service.attack_target(
            state=state,
            attacker_ref=req.attacker_ref,
            target_ref=req.target_ref,
            attack_bonus=req.attack_bonus,
            damage_expression=req.damage_expression,
            damage_type=req.damage_type,
            resolution_mode=req.resolution_mode,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/skill-check")
async def skill_check_action(game_id: str, req: SkillCheckActionRequest):
    state = _load_game_or_404(game_id)
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
    state = _load_game_or_404(game_id)
    try:
        result = action_service.saving_throw(
            state=state,
            target_ref=req.target_ref,
            save_name=req.save_name,
            dc=req.dc,
            modifier=req.modifier,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/cast-spell")
async def cast_spell_action(game_id: str, req: CastSpellActionRequest):
    state = _load_game_or_404(game_id)
    try:
        result = action_service.cast_spell(
            state=state,
            caster_ref=req.caster_ref,
            spell_name=req.spell_name,
            slot_level=req.slot_level,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game_storage.save_game(game_id, result["game_state"])
    return result


@app.post("/api/v1/games/{game_id}/actions/use-item")
async def use_item_action(game_id: str, req: UseItemActionRequest):
    state = _load_game_or_404(game_id)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=23333)
