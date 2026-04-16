"""Deterministic local actions that bypass the language model."""

from typing import Any, Dict, Optional

from game_logic import GameLogic
from models import ChatMessage, GameState, SessionEvent, ToolResult
from rules_catalog import ABILITY_ALIAS, RuleCatalog, SKILL_TO_ABILITY


class GameActionService:
    def __init__(self):
        self.rules = RuleCatalog()

    def _combatant_ability_modifier(self, combatant, ability_name: str) -> int:
        attr = ABILITY_ALIAS.get(ability_name, ability_name).lower()
        return (getattr(combatant.stats, attr, 10) - 10) // 2

    # Every local action returns the same response shape the frontend already expects.
    def _append_result(
        self,
        state: GameState,
        summary: str,
        event_type: str,
        payload: Dict[str, Any],
        patch: Optional[Dict[str, Any]] = None,
        content: str = "",
    ) -> Dict[str, Any]:
        event = SessionEvent(type=event_type, summary=summary, content=content, payload=payload)
        tool_result = ToolResult(tool_name=event_type, summary=summary, payload=payload)
        state.timeline.append(event)
        state.latest_tool_results.append(tool_result)
        state.chat_history.append(ChatMessage(role="system", content=summary, kind="tool_result"))
        return {
            "summary": summary,
            "tool_result": tool_result,
            "event": event,
            "state_delta": patch or {},
            "game_state": state,
        }

    def advance_turn(self, state: GameState) -> Dict[str, Any]:
        logic = GameLogic(state)
        combatant = logic.advance_turn()
        if not combatant:
            raise ValueError("No active encounter or initiative order")
        payload = {
            "current_combatant_id": combatant.combatant_id,
            "current_combatant_name": combatant.name,
            "round_number": state.encounter.round_number if state.encounter else 0,
        }
        return self._append_result(
            state,
            summary=f"Turn advanced to {combatant.name}",
            event_type="turn_advanced",
            payload=payload,
            patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
        )

    # Combat actions mutate authoritative state first, then emit a timeline/tool record.
    def attack_target(
        self,
        state: GameState,
        attacker_ref: str,
        target_ref: str,
        attack_bonus: int,
        damage_expression: str,
        damage_type: str = "",
        resolution_mode: str = "normal",
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        logic.require_current_actor(attacker_ref)
        result = logic.resolve_attack(
            attacker_ref,
            target_ref,
            attack_bonus,
            damage_expression,
            damage_type,
            resolution_mode=resolution_mode,
        )
        if not result:
            raise ValueError(f"Attack target not found: {target_ref}")

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
        }
        summary = (
            f"{result['attacker_name']} attacks {result['target_name']}: "
            f"{result['attack_total']} vs AC {result['target_ac']} -> {'hit' if result['hit'] else 'miss'}"
        )
        if result["hit"]:
            summary += f", damage {result['damage_total']}"
            if damage_type:
                summary += f" {damage_type}"
            if result["target_defeat_state"] != "active":
                summary += f" | target {result['target_defeat_state']}"
        return self._append_result(
            state,
            summary=summary,
            event_type="attack_resolved",
            payload=payload,
            patch=result["patch"],
        )

    def skill_check(
        self,
        state: GameState,
        actor_ref: str,
        skill_name: str,
        dc: int = 0,
        modifier: Optional[int] = None,
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        logic.require_current_actor(actor_ref)
        actor = logic.get_character(actor_ref)
        if modifier is not None:
            resolved_modifier = modifier
        elif actor:
            resolved_modifier = self.rules.get_skill_modifier(actor, skill_name)
        else:
            combatant = logic.get_combatant(actor_ref)
            resolved_modifier = int(
                combatant.skills.get(skill_name, self._combatant_ability_modifier(combatant, SKILL_TO_ABILITY.get(skill_name, "wisdom")))
            ) if combatant else 0
        result = logic.roll_skill_check(actor_ref, skill_name, int(resolved_modifier), dc)
        summary = f"{result['actor_name']} {skill_name} check {result['total']}"
        if dc > 0:
            summary += f" vs DC {dc} -> {'success' if result['success'] else 'fail'}"
        return self._append_result(
            state,
            summary=summary,
            event_type="skill_check",
            payload=result,
        )

    def saving_throw(
        self,
        state: GameState,
        target_ref: str,
        save_name: str,
        dc: int,
        modifier: Optional[int] = None,
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        target = logic.get_character(target_ref)
        if modifier is not None:
            resolved_modifier = modifier
        elif target:
            resolved_modifier = self.rules.get_save_modifier(target, save_name)
        else:
            combatant = logic.get_combatant(target_ref)
            resolved_modifier = int(
                combatant.saving_throws.get(save_name, self._combatant_ability_modifier(combatant, save_name))
            ) if combatant else 0
        result = logic.roll_saving_throw(target_ref, save_name, int(resolved_modifier), dc)
        summary = f"{result['target_name']} {save_name} save {result['total']} vs DC {dc} -> {'success' if result['success'] else 'fail'}"
        return self._append_result(
            state,
            summary=summary,
            event_type="saving_throw",
            payload=result,
        )

    def cast_spell(
        self,
        state: GameState,
        caster_ref: str,
        spell_name: str,
        slot_level: int = 0,
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        logic.require_current_actor(caster_ref)
        caster = logic.get_character(caster_ref)
        if not caster:
            raise ValueError(f"Spell caster not found: {caster_ref}")

        validation = self.rules.can_cast_spell(caster, spell_name, slot_level or None)
        if not validation["ok"]:
            raise ValueError(validation["error"])

        resolved_slot = int(validation["resolved_slot_level"])
        self.rules.consume_spell_slot(caster, resolved_slot)
        payload = {
            "caster_id": caster.character_id,
            "caster_name": caster.name,
            "spell_name": spell_name,
            "spell_level": int(validation["spell"].get("level", 0)),
            "resolved_slot_level": resolved_slot,
            "remaining_slots": {
                level: {"total": slot.total, "used": slot.used}
                for level, slot in caster.spells.slots.items()
            },
        }
        summary = f"{caster.name} casts {spell_name}"
        if resolved_slot > 0:
            summary += f" using a level {resolved_slot} slot"
        return self._append_result(
            state,
            summary=summary,
            event_type="spell_cast",
            payload=payload,
            patch={"characters": {caster.character_id: {"spells": caster.spells.model_dump(mode="json")}}},
        )

    def use_item(self, state: GameState, user_ref: str, item_name: str, quantity: int = 1) -> Dict[str, Any]:
        logic = GameLogic(state)
        logic.require_current_actor(user_ref)
        user = logic.get_character(user_ref)
        if not user:
            raise ValueError(f"Item user not found: {user_ref}")

        item = next((entry for entry in user.inventory if entry.name == item_name), None)
        if not item or item.quantity < quantity:
            raise ValueError(f"Not enough item quantity for {item_name}")

        item.quantity -= quantity
        payload = {
            "user_id": user.character_id,
            "user_name": user.name,
            "item_name": item_name,
            "quantity_used": quantity,
            "quantity_remaining": item.quantity,
        }
        summary = f"{user.name} uses {quantity} x {item_name}"
        return self._append_result(
            state,
            summary=summary,
            event_type="item_used",
            payload=payload,
            patch={"characters": {user.character_id: {"inventory": [entry.model_dump(mode='json') for entry in user.inventory]}}},
        )

    # Story-state helpers persist rewards and chapter outcomes without requiring ad hoc JSON edits.
    def add_inventory_item(
        self,
        state: GameState,
        character_ref: str,
        item_name: str,
        quantity: int = 1,
        item_type: str = "misc",
        notes: str = "",
        source: str = "",
        tags: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
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
            raise ValueError(f"Character not found for inventory update: {character_ref}")

        item = result["item"]
        return self._append_result(
            state,
            summary=f"{result['character'].name} gains {item.quantity if quantity <= 0 else quantity} x {item.name}",
            event_type="inventory_item_added",
            payload={
                "character_id": result["character"].character_id,
                "character_name": result["character"].name,
                "item_name": item.name,
                "quantity": quantity,
                "item_type": item.type,
                "notes": item.notes,
                "source": item.source,
                "tags": list(item.tags),
            },
            patch=result["patch"],
        )

    def record_evidence(
        self,
        state: GameState,
        title: str,
        summary: str,
        holder_ref: str = "",
        source_ref: str = "",
        location: str = "",
        tags: Optional[list[str]] = None,
        add_to_inventory: bool = True,
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        result = logic.record_evidence(
            title=title,
            summary=summary,
            holder_ref=holder_ref,
            source_ref=source_ref,
            location=location,
            tags=tags,
            add_to_inventory=add_to_inventory,
        )
        evidence = result["evidence"]
        holder = result.get("character")
        holder_name = holder.name if holder else ""
        return self._append_result(
            state,
            summary=f"Evidence recorded: {evidence.title}",
            event_type="evidence_recorded",
            payload={
                "evidence_id": evidence.evidence_id,
                "title": evidence.title,
                "summary": evidence.summary,
                "holder_character_id": evidence.holder_character_id,
                "holder_character_name": holder_name,
                "source_ref": evidence.source_ref,
                "location": evidence.location,
                "tags": list(evidence.tags),
            },
            patch=result["patch"],
        )

    def record_search_outcome(
        self,
        state: GameState,
        searcher_ref: str,
        target_ref: str,
        summary: str,
        location: str = "",
        recovered_items: Optional[list[str]] = None,
        recovered_evidence_ids: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        result = logic.record_search_outcome(
            searcher_ref=searcher_ref,
            target_ref=target_ref,
            summary=summary,
            location=location,
            recovered_items=recovered_items,
            recovered_evidence_ids=recovered_evidence_ids,
        )
        record = result["search_record"]
        return self._append_result(
            state,
            summary=f"Search recorded: {result['character'].name} searched {record.target_ref or 'target'}",
            event_type="search_recorded",
            payload=record.model_dump(mode="json"),
            patch=result["patch"],
        )

    def add_major_experience(self, state: GameState, character_ref: str, entry: str) -> Dict[str, Any]:
        logic = GameLogic(state)
        result = logic.add_major_experience(character_ref, entry)
        if not result:
            raise ValueError(f"Character not found for major experience: {character_ref}")

        return self._append_result(
            state,
            summary=f"Major experience recorded for {result['character'].name}",
            event_type="major_experience_recorded",
            payload={
                "character_id": result["character"].character_id,
                "character_name": result["character"].name,
                "entry": result["entry"],
            },
            patch=result["patch"],
        )

    def record_chapter_progress(
        self,
        state: GameState,
        title: str,
        summary: str,
        chapter_number: int = 0,
        completed: bool = False,
    ) -> Dict[str, Any]:
        logic = GameLogic(state)
        result = logic.record_chapter_progress(
            title=title,
            summary=summary,
            chapter_number=chapter_number,
            completed=completed,
        )
        chapter = result["chapter"]
        return self._append_result(
            state,
            summary=f"Chapter recorded: {chapter.chapter_number} - {chapter.title}",
            event_type="chapter_recorded",
            payload=chapter.model_dump(mode="json"),
            patch=result["patch"],
        )

    def end_encounter(self, state: GameState) -> Dict[str, Any]:
        logic = GameLogic(state)
        outcome = logic.finalize_encounter()
        if not outcome:
            raise ValueError("No active encounter to end")

        encounter = outcome["encounter"]
        payload = {
            **outcome["summary_payload"],
            "adventure_log_entry": outcome["adventure_log_entry"],
        }
        return self._append_result(
            state,
            summary=outcome["summary"],
            event_type="encounter_ended",
            payload=payload,
            patch={
                "scene": state.scene,
                "campaign": {"phase": state.campaign.phase},
                "encounter": encounter.model_dump(mode="json"),
                "adventure_log": state.adventure_log,
            },
        )
