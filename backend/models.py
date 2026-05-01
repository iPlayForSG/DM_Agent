"""Shared Pydantic models for character sheets, encounters, and turn results."""

import hashlib
import re
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def stable_id(prefix: str, raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if slug:
        return f"{prefix}-{slug[:40]}"
    digest = hashlib.md5((raw_value or prefix).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def random_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class SpellSlot(BaseModel):
    total: int = 0
    used: int = 0


# Core character-sheet primitives.
class ResourcePool(BaseModel):
    current_value: int = 0
    max_value: int = 0
    recovery: str = "long_rest"
    description: str = ""


class Spellbook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cantrips: List[str] = Field(default_factory=list)
    prepared: List[str] = Field(default_factory=list)
    slots: Dict[str, SpellSlot] = Field(default_factory=dict)
    ability: str = "INT"
    casting_mode: str = "prepared"

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if value is None:
            return {}

        if isinstance(value, list):
            return {"prepared": value}

        if not isinstance(value, dict):
            return value

        data = dict(value)
        cantrips = data.get("cantrips")
        prepared = data.get("prepared")

        if prepared is None and isinstance(data.get("known"), list):
            prepared = data["known"]
        elif prepared is None and isinstance(data.get("known"), dict):
            if cantrips is None:
                raw_cantrips = data["known"].get("0") or data["known"].get(0) or data["known"].get("cantrips")
                if isinstance(raw_cantrips, list):
                    cantrips = [str(name) for name in raw_cantrips]
            flattened: List[str] = []
            for key, names in data["known"].items():
                if str(key) in {"0", "cantrips"}:
                    continue
                if isinstance(names, list):
                    flattened.extend(str(name) for name in names)
            prepared = flattened
        elif prepared is None and isinstance(data.get("spells"), list):
            prepared = data["spells"]

        data["cantrips"] = list(dict.fromkeys(cantrips or []))
        data["prepared"] = list(dict.fromkeys(prepared or []))
        data.setdefault("slots", {})
        data.setdefault("ability", "INT")
        return data


class InventoryItem(BaseModel):
    name: str
    quantity: int = 1
    is_equipped: bool = False
    type: str = "misc"
    notes: str = ""
    source: str = ""
    tags: List[str] = Field(default_factory=list)
    attack_bonus: Optional[int] = None
    damage_expression: str = ""
    damage_type: str = ""
    armor_class_bonus: int = 0
    properties: List[str] = Field(default_factory=list)


class StarterPurchaseSelection(BaseModel):
    item_id: str
    quantity: int = 1


class PendingCustomEquipment(BaseModel):
    name: str = ""
    quantity: int = 1
    reserved_cost_gp: int = 0
    notes: str = ""


class Stats(BaseModel):
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10


class CharacterSummary(BaseModel):
    character_id: str
    name: str
    class_name: str
    level: int


# Persistent player-facing character state.
class Character(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character_id: str = ""
    name: str
    species: str = "Human"
    race: str = "Human"
    background_name: str = ""
    origin_feat: str = ""
    class_name: str = "Commoner"
    level: int = 1
    experience_points: int = 0
    inspiration: bool = False
    starter_option_id: str = ""
    starter_choice_ids: Dict[str, str] = Field(default_factory=dict)
    equipment_mode: str = "starter_package"
    custom_purchase_items: List[StarterPurchaseSelection] = Field(default_factory=list)
    custom_pending_item: PendingCustomEquipment = Field(default_factory=PendingCustomEquipment)
    gold_gp: int = 0

    hp_current: int = 10
    hp_max: int = 10
    temp_hp: int = 0
    ac: int = 10
    speed: int = 30
    initiative_bonus: int = 0

    stats: Stats = Field(default_factory=Stats)
    spells: Spellbook = Field(default_factory=Spellbook)
    resources: Dict[str, ResourcePool] = Field(default_factory=dict)
    inventory: List[InventoryItem] = Field(default_factory=list)
    status_effects: List[str] = Field(default_factory=list)
    defeat_state: str = "active"
    skill_proficiencies: Dict[str, int] = Field(default_factory=dict)
    save_proficiencies: Dict[str, bool] = Field(default_factory=dict)
    major_experiences: List[str] = Field(default_factory=list)

    background: str = ""
    alignment: str = "Neutral"

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        if "display_name" in data and "name" not in data:
            data["name"] = data["display_name"]
        if "species" not in data and "race" in data:
            data["species"] = data["race"]
        if "hp" in data and "hp_current" not in data:
            data["hp_current"] = data["hp"]
        if "hpm" in data and "hp_max" not in data:
            data["hp_max"] = data["hpm"]
        if "gold" in data and "gold_gp" not in data:
            data["gold_gp"] = data["gold"]
        if "gp" in data and "gold_gp" not in data:
            data["gold_gp"] = data["gp"]
        if "starter_choices" in data and "starter_choice_ids" not in data and isinstance(data["starter_choices"], dict):
            data["starter_choice_ids"] = data["starter_choices"]
        if isinstance(data.get("custom_purchase_items"), dict):
            data["custom_purchase_items"] = [
                {"item_id": item_id, "quantity": quantity}
                for item_id, quantity in data["custom_purchase_items"].items()
            ]
        data["character_id"] = data.get("character_id") or stable_id("char", data.get("name", "character"))
        return data

    def to_summary(self) -> CharacterSummary:
        return CharacterSummary(
            character_id=self.character_id,
            name=self.name,
            class_name=self.class_name,
            level=self.level,
        )


class ChatMessage(BaseModel):
    role: str
    content: str
    kind: str = "message"


class ToolResult(BaseModel):
    tool_name: str
    summary: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "success"


class MonsterTextEntry(BaseModel):
    name: str
    description: str


class MonsterSummary(BaseModel):
    monster_id: str
    name: str
    creature_type: str
    challenge_rating: str
    source: str


class MonsterTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    monster_id: str = ""
    name: str
    size: str = "Medium"
    creature_type: str = "Beast"
    alignment: str = "Unaligned"
    challenge_rating: str = "1"
    proficiency_bonus: int = 2
    ac: int = 10
    hp_max: int = 10
    initiative_bonus: int = 0
    speed: int = 30
    stats: Stats = Field(default_factory=Stats)
    saving_throws: Dict[str, int] = Field(default_factory=dict)
    skills: Dict[str, int] = Field(default_factory=dict)
    senses: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    damage_resistances: List[str] = Field(default_factory=list)
    damage_immunities: List[str] = Field(default_factory=list)
    damage_vulnerabilities: List[str] = Field(default_factory=list)
    condition_immunities: List[str] = Field(default_factory=list)
    traits: List[MonsterTextEntry] = Field(default_factory=list)
    actions: List[MonsterTextEntry] = Field(default_factory=list)
    reactions: List[MonsterTextEntry] = Field(default_factory=list)
    bonus_actions: List[MonsterTextEntry] = Field(default_factory=list)
    notes: str = ""
    source: str = "ai-authored"

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        if "type" in data and "creature_type" not in data:
            data["creature_type"] = data["type"]
        if "hp" in data and "hp_max" not in data:
            data["hp_max"] = data["hp"]
        data["monster_id"] = data.get("monster_id") or stable_id("mon", data.get("name", "monster"))
        return data

    def to_summary(self) -> MonsterSummary:
        return MonsterSummary(
            monster_id=self.monster_id,
            name=self.name,
            creature_type=self.creature_type,
            challenge_rating=self.challenge_rating,
            source=self.source,
        )


class AdventureHook(BaseModel):
    adventure_id: str = ""
    title: str
    summary: str
    tone: str = "grim"
    difficulty: str = "medium"
    opening_scene: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        data["adventure_id"] = data.get("adventure_id") or stable_id("adv", data.get("title", "adventure"))
        return data


# Chapter summaries let the campaign remember what has already been resolved.
class ChapterRecord(BaseModel):
    chapter_number: int = 0
    title: str = ""
    summary: str = ""
    status: str = "completed"


class EvidenceRecord(BaseModel):
    evidence_id: str = ""
    title: str
    summary: str = ""
    holder_character_id: Optional[str] = None
    source_ref: str = ""
    location: str = ""
    tags: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        data["evidence_id"] = data.get("evidence_id") or stable_id("evi", data.get("title", "evidence"))
        return data


class SearchRecord(BaseModel):
    search_id: str = ""
    searcher_character_id: Optional[str] = None
    target_ref: str = ""
    location: str = ""
    summary: str = ""
    recovered_items: List[str] = Field(default_factory=list)
    recovered_evidence_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        seed = f"{data.get('searcher_character_id', '')}-{data.get('target_ref', '')}-{data.get('summary', '')}"
        data["search_id"] = data.get("search_id") or stable_id("srch", seed or "search")
        return data


class CampaignFlowState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phase: str = "character_creation"
    milestone_mode: bool = True
    party_size_limit: int = 4
    available_adventures: List[AdventureHook] = Field(default_factory=list)
    selected_adventure_id: Optional[str] = None
    setup_complete: bool = False
    current_chapter_number: int = 0
    current_chapter_title: str = ""
    current_chapter_summary: str = ""
    completed_chapters: List[ChapterRecord] = Field(default_factory=list)

    def selected_adventure(self) -> Optional[AdventureHook]:
        if not self.selected_adventure_id:
            return None
        for hook in self.available_adventures:
            if hook.adventure_id == self.selected_adventure_id:
                return hook
        return None


# Timeline and combat state power both the UI and the LangGraph runtime state.
class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str = ""
    type: str
    summary: str
    content: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        data["event_id"] = data.get("event_id") or random_id("evt")
        return data


class Combatant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    combatant_id: str = ""
    name: str
    side: str = "enemy"
    linked_character_id: Optional[str] = None
    monster_template_id: Optional[str] = None
    hp_current: int = 10
    hp_max: int = 10
    ac: int = 10
    initiative_bonus: int = 0
    initiative: Optional[int] = None
    status_effects: List[str] = Field(default_factory=list)
    defeat_state: str = "active"
    stats: Stats = Field(default_factory=Stats)
    skills: Dict[str, int] = Field(default_factory=dict)
    saving_throws: Dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        identifier_seed = (
            data.get("linked_character_id")
            or data.get("monster_template_id")
            or data.get("name")
            or "combatant"
        )
        data["combatant_id"] = data.get("combatant_id") or stable_id("cmb", identifier_seed)
        return data


class EncounterState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    encounter_id: str = ""
    active: bool = True
    round_number: int = 1
    current_combatant_id: Optional[str] = None
    turn_order_started: bool = False
    initiative_order: List[str] = Field(default_factory=list)
    combatants: Dict[str, Combatant] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if value is None:
            return None

        if not isinstance(value, dict):
            return value

        data = dict(value)
        normalized_combatants: Dict[str, Combatant] = {}
        raw_combatants = data.get("combatants") or {}

        if isinstance(raw_combatants, dict):
            for key, raw_combatant in raw_combatants.items():
                combatant = raw_combatant if isinstance(raw_combatant, Combatant) else Combatant.model_validate(raw_combatant)
                normalized_combatants[combatant.combatant_id] = combatant
        elif isinstance(raw_combatants, list):
            for raw_combatant in raw_combatants:
                combatant = Combatant.model_validate(raw_combatant)
                normalized_combatants[combatant.combatant_id] = combatant

        data["combatants"] = normalized_combatants
        data["encounter_id"] = data.get("encounter_id") or random_id("enc")
        data.setdefault("initiative_order", list(normalized_combatants.keys()))
        data.setdefault("turn_order_started", False)
        return data

    def get_current_combatant(self) -> Optional[Combatant]:
        if self.current_combatant_id and self.current_combatant_id in self.combatants:
            return self.combatants[self.current_combatant_id]
        return None


class GameSummary(BaseModel):
    game_id: str
    title: str
    scene: str
    character_count: int
    encounter_active: bool = False
    phase: str = "character_creation"
    updated_at: Optional[str] = None


class GameState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 3
    game_id: str = ""
    title: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    characters: Dict[str, Character] = Field(default_factory=dict)
    active_character_id: Optional[str] = None

    scene: str = "setup"
    turn_number: int = 0
    adventure_log: List[str] = Field(default_factory=list)
    evidence_records: List[EvidenceRecord] = Field(default_factory=list)
    search_records: List[SearchRecord] = Field(default_factory=list)
    chat_history: List[ChatMessage] = Field(default_factory=list)
    timeline: List[SessionEvent] = Field(default_factory=list)
    latest_tool_results: List[ToolResult] = Field(default_factory=list)
    encounter: Optional[EncounterState] = None
    campaign: CampaignFlowState = Field(default_factory=CampaignFlowState)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        normalized_characters: Dict[str, Character] = {}
        raw_characters = data.get("characters") or {}

        # Accept both map-style and list-style payloads from older saves and runtime patches.
        if isinstance(raw_characters, dict):
            for key, raw_char in raw_characters.items():
                if isinstance(raw_char, Character):
                    char = raw_char
                else:
                    payload = dict(raw_char)
                    payload["character_id"] = payload.get("character_id") or stable_id(
                        "char", payload.get("name", str(key))
                    )
                    char = Character.model_validate(payload)
                normalized_characters[char.character_id] = char
        elif isinstance(raw_characters, list):
            for raw_char in raw_characters:
                char = Character.model_validate(raw_char)
                normalized_characters[char.character_id] = char

        data["characters"] = normalized_characters
        data["game_id"] = data.get("game_id", "")
        if not data.get("title"):
            data["title"] = data["game_id"]

        active_character_id = data.get("active_character_id")
        if active_character_id and active_character_id not in normalized_characters:
            for char_id, char in normalized_characters.items():
                if char.name == active_character_id:
                    data["active_character_id"] = char_id
                    break
        elif not active_character_id and normalized_characters:
            data["active_character_id"] = next(iter(normalized_characters.keys()))

        data["scene"] = str(data.get("scene", "setup")).lower()
        data.setdefault("adventure_log", [])
        data.setdefault("evidence_records", [])
        data.setdefault("search_records", [])
        data.setdefault("chat_history", [])
        data.setdefault("timeline", [])
        data.setdefault("latest_tool_results", [])
        data["evidence_records"] = [
            item if isinstance(item, EvidenceRecord) else EvidenceRecord.model_validate(item)
            for item in data.get("evidence_records", [])
        ]
        data["search_records"] = [
            item if isinstance(item, SearchRecord) else SearchRecord.model_validate(item)
            for item in data.get("search_records", [])
        ]
        data["encounter"] = EncounterState.model_validate(data["encounter"]) if data.get("encounter") else None
        data["campaign"] = CampaignFlowState.model_validate(data["campaign"]) if data.get("campaign") else CampaignFlowState()
        data.setdefault("schema_version", 3)
        return data

    def get_active_char(self) -> Optional[Character]:
        if self.active_character_id and self.active_character_id in self.characters:
            return self.characters[self.active_character_id]
        return None

    def to_summary(self) -> GameSummary:
        return GameSummary(
            game_id=self.game_id,
            title=self.title or self.game_id,
            scene=self.scene,
            character_count=len(self.characters),
            encounter_active=bool(self.encounter and self.encounter.active),
            phase=self.campaign.phase,
            updated_at=self.updated_at,
        )


class TurnResult(BaseModel):
    # This mirrors the full post-turn payload returned to the frontend.
    response: str
    history: List[ChatMessage] = Field(default_factory=list)
    history_append: List[ChatMessage] = Field(default_factory=list)
    timeline: List[SessionEvent] = Field(default_factory=list)
    timeline_append: List[SessionEvent] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    rag_metadata: Dict[str, Any] = Field(default_factory=dict)
    input_warnings: List[str] = Field(default_factory=list)
    state_delta: Dict[str, Any] = Field(default_factory=dict)
    game_state: GameState
