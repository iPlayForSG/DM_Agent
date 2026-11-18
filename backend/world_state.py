"""战役世界的存档契约、确定性工具和 DM 私有上下文。"""

from __future__ import annotations

import json
from typing import Annotated, Literal, TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

if TYPE_CHECKING:
    from models import GameState


WorldID = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]


class WorldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fact(WorldModel):
    title: Title
    summary: Note
    links: list[WorldID] = Field(default_factory=list, max_length=16)


class NPC(Fact):
    kind: Literal["npc"]
    motive: Note
    attitude: Note
    actor_id: Title | None = None


class Location(Fact):
    kind: Literal["location"]


class Secret(Fact):
    kind: Literal["secret"]


class Clue(Fact):
    kind: Literal["clue"]
    evidence_id: Title | None = None


class Clock(Fact):
    kind: Literal["clock"]
    segments: int = Field(ge=1, le=24)
    trigger: Note


class Quest(Fact):
    kind: Literal["quest"]
    status: Literal["open", "completed", "failed"]


WorldFact = Annotated[NPC | Location | Secret | Clue | Clock | Quest, Field(discriminator="kind")]


class Discovery(WorldModel):
    # 公开标识独立生成；DM 可能把真凶身份写在私有 ID 或标题里。
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: Title
    summary: Note


class WorldEntry(WorldModel):
    fact: WorldFact
    basis: Note
    updated_turn: int = Field(ge=0)
    progress: int | None = None
    discovery: Discovery | None = None

    @model_validator(mode="after")
    def validate_progress(self):
        if isinstance(self.fact, Clock):
            if self.progress is None or not 0 <= self.progress <= self.fact.segments:
                raise ValueError("Clock progress must be within its segments.")
        elif self.progress is not None:
            raise ValueError("Only clocks have progress.")
        return self


class CampaignWorld(WorldModel):
    entries: dict[WorldID, WorldEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_links(self):
        for entry_id, entry in self.entries.items():
            self.validate_links(entry_id, entry.fact.links)
        return self

    def validate_links(self, entry_id: str, links: list[str]) -> None:
        if entry_id in links or len(set(links)) != len(links) or any(key not in self.entries for key in links):
            raise ValueError("Links must name distinct, existing, other world entries.")

    def require(self, entry_id: str) -> WorldEntry:
        if entry_id not in self.entries:
            raise ValueError("World entry does not exist.")
        return self.entries[entry_id]

    def context(self, user_input: str, max_chars: int) -> str:
        # 优先取本回合点名的人物/地点，然后补近期事实。预算不足时跳过整条，避免半截秘密被误读。
        query = user_input.casefold()
        mentioned = {
            key for key, entry in self.entries.items()
            if key in query or entry.fact.title.casefold() in query
            or (entry.discovery and entry.discovery.title.casefold() in query)
        }
        related = {link for key in mentioned for link in self.entries[key].fact.links}
        ordered = sorted(self.entries.items(), key=lambda pair: (
            pair[0] in mentioned, pair[0] in related, pair[1].updated_turn,
        ), reverse=True)
        lines = []
        remaining = max_chars
        for entry_id, entry in ordered:
            line = json.dumps({entry_id: entry.model_dump(exclude_none=True)}, ensure_ascii=False)
            if len(line) + 1 <= remaining:
                lines.append(line)
                remaining -= len(line) + 1
        return "\n".join(lines)


class RecordWorldEntry(WorldModel):
    """Create or replace a complete private fact using a stable ID and an established fictional basis. Preserve existing links when updating. Publish observations separately with reveal_world_entry."""

    entry_id: WorldID
    fact: WorldFact
    basis: Note

    def apply(self, state: GameState) -> WorldEntry:
        world = state.world
        old = world.entries.get(self.entry_id)
        if old and old.fact.kind != self.fact.kind:
            raise ValueError("An established entry cannot change kind.")
        if isinstance(self.fact, Clock) and old and old.fact.segments != self.fact.segments:
            raise ValueError("An established clock cannot change size.")
        # 重述人物或线索时常只改性格/描述；只有显式传空才能解除已确认的关联。
        retained = {}
        if old:
            for field in ("links", "actor_id", "evidence_id"):
                if hasattr(old.fact, field) and field not in self.fact.model_fields_set:
                    retained[field] = getattr(old.fact, field)
        fact = self.fact.model_copy(update=retained, deep=True)
        world.validate_links(self.entry_id, fact.links)
        if isinstance(fact, NPC) and fact.actor_id:
            actors = state.encounter.combatants if state.encounter else {}
            if fact.actor_id not in state.scene_actors and fact.actor_id not in actors:
                if not old or old.fact.actor_id != fact.actor_id:
                    raise ValueError("actor_id must identify an established rules actor.")
        if isinstance(fact, Clue) and fact.evidence_id:
            if not any(item.evidence_id == fact.evidence_id for item in state.evidence_records):
                raise ValueError("evidence_id must identify established party evidence.")
        progress = old.progress if old else None
        if isinstance(fact, Clock) and progress is None:
            progress = 0
        return WorldEntry(
            fact=fact, basis=self.basis, updated_turn=state.turn_number + 1,
            discovery=old.discovery if old else None, progress=progress,
        )


class AdvanceWorldClock(WorldModel):
    """Advance a clock after its fictional trigger occurs. Supply the observed starting progress to prevent duplicate advances."""

    entry_id: WorldID
    expected_progress: int = Field(ge=0, le=23)
    steps: int = Field(ge=1, le=24)
    basis: Note

    def apply(self, state: GameState) -> WorldEntry:
        entry = state.world.require(self.entry_id)
        if not isinstance(entry.fact, Clock) or entry.progress != self.expected_progress:
            raise ValueError("Clock kind or expected progress does not match.")
        progress = self.expected_progress + self.steps
        if progress > entry.fact.segments:
            raise ValueError("Advance exceeds the clock size.")
        return entry.model_copy(update={"progress": progress, "basis": self.basis, "updated_turn": state.turn_number + 1})


class RevealWorldEntry(WorldModel):
    """Publish only the title and cumulative observations actually learned by the party. Private names, motives and links stay in the DM record."""

    entry_id: WorldID
    title: Title
    summary: Note

    def apply(self, state: GameState) -> WorldEntry:
        entry = state.world.require(self.entry_id)
        discovery = (entry.discovery.model_copy(update={"title": self.title, "summary": self.summary})
                     if entry.discovery else Discovery(title=self.title, summary=self.summary))
        return entry.model_copy(update={"discovery": discovery, "updated_turn": state.turn_number + 1})


class LookupWorldEntry(WorldModel):
    """Read private campaign entries by stable ID or part of a title. An exact ID returns that one record."""

    query: Title

    def search(self, world: CampaignWorld) -> dict:
        term = self.query.casefold()
        matches = [key for key, entry in world.entries.items()
                   if term in key or term in entry.fact.title.casefold()
                   or (entry.discovery and term in entry.discovery.title.casefold())]
        if term in world.entries:
            matches = [term]
        return {"count": len(matches), "entries": {
            key: world.entries[key].model_dump(mode="json", exclude_none=True) for key in matches[:5]
        }}


WORLD_WRITES = {
    "record_world_entry": RecordWorldEntry,
    "advance_world_clock": AdvanceWorldClock,
    "reveal_world_entry": RevealWorldEntry,
}
WORLD_TOOLS = {**WORLD_WRITES, "lookup_world_entry": LookupWorldEntry}
