"""Framework-neutral DM tool implementations for agent runtimes."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ability_scores import AbilityScoreService
from encounter_math import (
    defensive_challenge_rating,
    estimate_challenge_rating,
    estimate_encounter_difficulty,
    normalize_cr,
)
from game_logic import DiceRoller, GameLogic
from library import Library
from models import Character, GameState, MonsterTemplate, MonsterTextEntry, SessionEvent, Stats, ToolResult
from rag import RAGEngine
from rules_catalog import ABILITY_ALIAS, SKILL_TO_ABILITY, RuleCatalog
from starter_shop import get_shop_catalog
from storage import MonsterStorage
from roll_capture import dice_context


def merge_patch(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_patch(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class AgentToolExecution:
    ok: bool
    payload: Dict[str, Any] = field(default_factory=dict)
    tool_result: Optional[ToolResult] = None
    timeline_event: Optional[SessionEvent] = None
    state_patch: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_response: Dict[str, Any] = field(default_factory=dict)

    def response(self, include_ok: bool = True) -> Dict[str, Any]:
        if not self.ok:
            if self.error_response:
                return self.error_response
            return {"ok": False, "error": self.error}
        if not include_ok:
            return dict(self.payload)
        return {"ok": True, **self.payload}


class AgentToolService:
    """Runs DM tools without depending on orchestration runtime objects."""

    def __init__(
        self,
        rag_engine: RAGEngine,
        monster_storage: MonsterStorage,
        rules_catalog: RuleCatalog,
    ):
        self.rag_engine = rag_engine
        self.monster_storage = monster_storage
        self.rules_catalog = rules_catalog
        self.library = Library()
        self.ability_scores = AbilityScoreService(rules_catalog)

    def _build_event(
        self,
        event_type: str,
        summary: str,
        content: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> SessionEvent:
        return SessionEvent(type=event_type, summary=summary, content=content, payload=payload or {})

    def _success(
        self,
        *,
        tool_name: str,
        summary: str,
        payload: Dict[str, Any],
        event_type: str,
        content: str = "",
        state_patch: Optional[Dict[str, Any]] = None,
        status: str = "success",
    ) -> AgentToolExecution:
        tool_result = ToolResult(tool_name=tool_name, summary=summary, payload=payload, status=status)
        event = self._build_event(event_type=event_type, summary=summary, content=content, payload=payload)
        return AgentToolExecution(
            ok=True,
            payload=payload,
            tool_result=tool_result,
            timeline_event=event,
            state_patch=state_patch or {},
        )

    @staticmethod
    def _error(message: str, response: Optional[Dict[str, Any]] = None) -> AgentToolExecution:
        return AgentToolExecution(ok=False, error=message, error_response=response or {})

    @staticmethod
    def _concentration_summary(check: Optional[Dict[str, Any]]) -> str:
        if not check:
            return ""
        spell_name = str(check.get("previous_spell") or "专注法术")
        if check.get("save"):
            save = dict(check.get("save") or {})
            outcome = "成功" if save.get("success") else "失败"
            suffix = "，维持专注" if save.get("success") else f"，{spell_name}专注结束"
            return f" | 专注豁免 {save.get('total')} vs DC {check.get('dc')} -> {outcome}{suffix}"
        if check.get("broken"):
            return f" | {spell_name}专注因失能或败北而结束"
        return ""

    @staticmethod
    def _action_cost_display(action_cost: str) -> str:
        if action_cost == "bonus_action":
            return "附赠动作"
        if action_cost == "reaction":
            return "反应"
        if action_cost == "free":
            return "自由动作"
        return "动作"

    @staticmethod
    def _combatant_ability_modifier(combatant, ability_name: str) -> int:
        attr = ABILITY_ALIAS.get(ability_name, ability_name).lower()
        return (getattr(combatant.stats, attr, 10) - 10) // 2

    @staticmethod
    def _roll_mode_error(reason: str, roll_mode: str) -> str:
        normalized_reason = str(reason or "").casefold()
        normalized_mode = str(roll_mode or "normal").casefold()
        claims_advantage = "优势" in normalized_reason or "advantage" in normalized_reason
        claims_disadvantage = "劣势" in normalized_reason or "disadvantage" in normalized_reason
        if claims_advantage and normalized_mode != "advantage":
            return "reason claims mechanical advantage but roll_mode is not advantage"
        if claims_disadvantage and normalized_mode != "disadvantage":
            return "reason claims mechanical disadvantage but roll_mode is not disadvantage"
        return ""

    @staticmethod
    def _roll_mode_summary(roll_mode: str) -> str:
        if roll_mode == "advantage":
            return "（优势）"
        if roll_mode == "disadvantage":
            return "（劣势）"
        return ""

    @staticmethod
    def _linked_character(state: GameState, logic: GameLogic, identifier: str):
        character = logic.get_character(identifier)
        if character:
            return character
        combatant = logic.get_combatant(identifier)
        if combatant and combatant.linked_character_id:
            return state.characters.get(combatant.linked_character_id)
        return None

    @staticmethod
    def _normalize_text_entries(entries: Optional[List[str]]) -> List[MonsterTextEntry]:
        normalized: List[MonsterTextEntry] = []
        for index, item in enumerate(entries or [], start=1):
            text = str(item).strip()
            if text:
                normalized.append(MonsterTextEntry(name=f"Entry {index}", description=text))
        return normalized

    def _load_monster_template(self, state: GameState, monster_ref: str) -> Optional[MonsterTemplate]:
        monster = state.monster_templates.get(monster_ref)
        if monster:
            return monster
        for template in state.monster_templates.values():
            if template.name == monster_ref:
                return template
        return self.monster_storage.load_monster(monster_ref)

    def lookup_rules(self, state: GameState, query: str, n_results: int = 3) -> AgentToolExecution:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return self._error("query is required")
        if not self.rag_engine.is_ready():
            return self._error(
                self.rag_engine.last_error or "RAG is not available",
                {
                    "ok": False,
                    "error": self.rag_engine.last_error or "RAG is not available",
                    "rag_status": self.rag_engine.status_payload(),
                },
            )

        snippets = self.library.localize_rag_snippets(
            self.rag_engine.search(normalized_query, n_results=n_results)
        )
        payload = {
            "query": normalized_query,
            "result_count": len(snippets),
            "snippets": snippets,
        }
        return self._success(
            tool_name="knowledge.lookup_rules",
            summary=f"规则检索“{self.library.localize_game_terms(normalized_query)}”返回 {len(snippets)} 条片段",
            payload=payload,
            event_type="rules_retrieved",
            content=normalized_query,
            status="success" if snippets else "empty",
        )

    def generate_ability_scores(
        self,
        state: GameState,
        method: str,
        scores: Optional[Dict[str, int]] = None,
    ) -> AgentToolExecution:
        result = self.ability_scores.generate(method, scores)
        normalized_method = str(result.get("method") or method).strip().lower()
        method_labels = {
            "point_buy": "point buy",
            "standard_array": "standard array",
            "rolled": "4d6 drop lowest",
        }
        return self._success(
            tool_name="character.generate_ability_scores",
            summary=f"Prepared ability scores using {method_labels.get(normalized_method, normalized_method)}.",
            payload=result,
            event_type="ability_scores_generated",
            content=normalized_method,
        )

    def set_player_action_suggestions(
        self,
        state: GameState,
        suggestions: List[Dict[str, Any]],
    ) -> AgentToolExecution:
        normalized: List[Dict[str, str]] = []
        for item in suggestions or []:
            if not isinstance(item, dict):
                continue
            label = " ".join(str(item.get("label") or "").split()).strip()
            action = " ".join(str(item.get("action") or "").split()).strip()
            if label and action:
                normalized.append({"label": label, "action": action})

        if len(normalized) != 3:
            return self._error("set_player_action_suggestions requires exactly three valid suggestions.")

        return AgentToolExecution(
            ok=True,
            payload={"suggestions": normalized},
        )

    def roll_dice(
        self,
        state: GameState,
        expression: str,
        reason: str = "",
        visibility: str = "public",
    ) -> AgentToolExecution:
        normalized_visibility = str(visibility or "public").strip().casefold()
        if normalized_visibility not in {"public", "hidden"}:
            return self._error("visibility must be public or hidden")
        with dice_context(visibility=normalized_visibility, reason=reason):
            total, detail = DiceRoller.roll(expression)
        payload = {
            "expression": expression,
            "reason": reason,
            "total": total,
            "detail": detail,
            "visibility": normalized_visibility,
        }
        return self._success(
            tool_name="dice.roll",
            summary=f"掷骰 {expression}: {detail} = {total}" + (f" | {self.library.localize_game_terms(reason)}" if reason else ""),
            payload=payload,
            event_type="dice_result",
            content=reason,
        )

    def adjust_hp(self, state: GameState, target_ref: str, amount: int, reason: str = "") -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.update_target_hp(target_ref, amount)
        if not result:
            return self._error(f"Target not found: {target_ref}")

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
        concentration_check = result.get("concentration_check")
        if concentration_check:
            payload["concentration_check"] = concentration_check
        summary = (
            f"{target.name} HP {amount:+d} -> {target.hp_current}/{target.hp_max}"
            + self._concentration_summary(concentration_check)
            + (f" | {self.library.localize_game_terms(reason)}" if reason else "")
        )
        return self._success(
            tool_name="target.adjust_hp",
            summary=summary,
            payload=payload,
            event_type="hp_changed",
            content=reason,
            state_patch=result["patch"],
        )

    def add_status(self, state: GameState, target_ref: str, status: str) -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.add_status(target_ref, status)
        if not result:
            return self._error(f"Target not found: {target_ref}")

        target = result["target"]
        display_status = self.library.localize_game_terms(status)
        payload = {
            "target_type": result["target_type"],
            "target_name": target.name,
            "status": status,
            "status_display": display_status,
            "status_effects": list(target.status_effects),
            "status_effects_display": [
                self.library.localize_game_terms(item) for item in target.status_effects
            ],
        }
        return self._success(
            tool_name="target.add_status",
            summary=f"{target.name} 获得状态：{display_status}",
            payload=payload,
            event_type="status_added",
            state_patch=result["patch"],
        )

    def remove_status(self, state: GameState, target_ref: str, status: str) -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.remove_status(target_ref, status)
        if not result:
            return self._error(f"Target not found: {target_ref}")

        target = result["target"]
        display_status = self.library.localize_game_terms(status)
        payload = {
            "target_type": result["target_type"],
            "target_name": target.name,
            "status": status,
            "status_display": display_status,
            "status_effects": list(target.status_effects),
            "status_effects_display": [
                self.library.localize_game_terms(item) for item in target.status_effects
            ],
        }
        return self._success(
            tool_name="target.remove_status",
            summary=f"{target.name} 移除状态：{display_status}",
            payload=payload,
            event_type="status_removed",
            state_patch=result["patch"],
        )

    def append_adventure_log(self, state: GameState, entry: str) -> AgentToolExecution:
        logic = GameLogic(state)
        logic.append_adventure_log(entry)
        payload = {"entry": entry, "log_size": len(state.adventure_log)}
        return self._success(
            tool_name="log.append",
            summary=f"Adventure log appended: {entry}",
            payload=payload,
            event_type="log_entry",
            content=entry,
        )

    def add_inventory_item(
        self,
        state: GameState,
        character_ref: str,
        item_name: str,
        quantity: int = 1,
        item_type: str = "misc",
        notes: str = "",
        source: str = "",
        tags: Optional[List[str]] = None,
    ) -> AgentToolExecution:
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
            return self._error(f"Character not found: {character_ref}")

        item = result["item"]
        payload = {
            "character_id": result["character"].character_id,
            "character_name": result["character"].name,
            "item_name": item.name,
            "item_name_display": self.library.localize_game_terms(item.name),
            "quantity": quantity,
            "item_type": item.type,
            "item_type_display": self.library.localize_game_terms(item.type),
            "notes": item.notes,
            "source": item.source,
            "tags": list(item.tags),
        }
        return self._success(
            tool_name="character.add_inventory_item",
            summary=f"{result['character'].name} 获得 {quantity} x {self.library.localize_game_terms(item.name)}",
            payload=payload,
            event_type="inventory_item_added",
            state_patch=result["patch"],
        )

    def record_evidence(
        self,
        state: GameState,
        title: str,
        summary: str,
        holder_ref: str = "",
        source_ref: str = "",
        location: str = "",
        tags: Optional[List[str]] = None,
        add_to_inventory: bool = True,
    ) -> AgentToolExecution:
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
            return self._error(str(exc))

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
        return self._success(
            tool_name="story.record_evidence",
            summary=f"证据已记录：{self.library.localize_game_terms(evidence.title)}",
            payload=payload,
            event_type="evidence_recorded",
            state_patch=result["patch"],
        )

    def record_search_outcome(
        self,
        state: GameState,
        searcher_ref: str,
        target_ref: str,
        summary: str,
        location: str = "",
        recovered_items: Optional[List[str]] = None,
        recovered_evidence_ids: Optional[List[str]] = None,
    ) -> AgentToolExecution:
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
            return self._error(str(exc))

        record = result["search_record"]
        payload = record.model_dump(mode="json")
        return self._success(
            tool_name="story.record_search_outcome",
            summary=f"搜索已记录：{result['character'].name} 搜索 {self.library.localize_game_terms(record.target_ref or '目标')}",
            payload=payload,
            event_type="search_recorded",
            state_patch=result["patch"],
        )

    def record_major_experience(self, state: GameState, character_ref: str, entry: str) -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.add_major_experience(character_ref, entry)
        if not result:
            return self._error(f"Character not found: {character_ref}")

        payload = {
            "character_id": result["character"].character_id,
            "character_name": result["character"].name,
            "entry": result["entry"],
        }
        return self._success(
            tool_name="character.record_major_experience",
            summary=f"重大经历已记录：{result['character'].name}",
            payload=payload,
            event_type="major_experience_recorded",
            state_patch=result["patch"],
        )

    def record_chapter_progress(
        self,
        state: GameState,
        chapter_title: str,
        summary: str,
        chapter_number: int = 0,
        completed: bool = False,
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.record_chapter_progress(
            title=chapter_title,
            summary=summary,
            chapter_number=chapter_number,
            completed=completed,
        )
        chapter = result["chapter"]
        payload = chapter.model_dump(mode="json")
        return self._success(
            tool_name="campaign.record_chapter_progress",
            summary=f"章节已记录：{chapter.chapter_number} - {chapter.title}",
            payload=payload,
            event_type="chapter_recorded",
            state_patch=result["patch"],
        )

    def set_defeat_state(self, state: GameState, target_ref: str, defeat_state: str) -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.set_defeat_state(target_ref, defeat_state)
        if not result:
            return self._error(f"Target not found: {target_ref}")

        target = result["target"]
        defeat_state_display = self.library.localize_game_terms(target.defeat_state.title())
        payload = {
            "target_name": target.name,
            "target_ref": target_ref,
            "defeat_state": target.defeat_state,
            "defeat_state_display": defeat_state_display,
            "status_effects": list(target.status_effects),
            "status_effects_display": [
                self.library.localize_game_terms(item) for item in target.status_effects
            ],
        }
        return self._success(
            tool_name="combat.set_defeat_state",
            summary=f"{target.name} 败北状态：{defeat_state_display}",
            payload=payload,
            event_type="defeat_state_set",
            state_patch=result["patch"],
        )

    def set_scene(self, state: GameState, scene: str) -> AgentToolExecution:
        logic = GameLogic(state)
        normalized = logic.set_scene(scene)
        payload = {"scene": normalized}
        return self._success(
            tool_name="scene.set",
            summary=f"场景切换为：{self.library.localize_game_terms(normalized)}",
            payload=payload,
            event_type="scene_changed",
            state_patch={"scene": normalized},
        )

    def set_active_character(self, state: GameState, character_ref: str) -> AgentToolExecution:
        logic = GameLogic(state)
        character = logic.set_active_character(character_ref)
        if not character:
            return self._error(f"Character not found: {character_ref}")

        payload = {
            "active_character_id": character.character_id,
            "active_character_name": character.name,
        }
        return self._success(
            tool_name="character.set_active",
            summary=f"当前角色：{character.name}",
            payload=payload,
            event_type="active_character_changed",
            state_patch={"active_character_id": character.character_id},
        )

    def start_encounter(
        self,
        state: GameState,
        enemy_names: List[str],
        enemy_hp: int = 10,
        enemy_ac: int = 10,
        auto_roll_initiative: bool = True,
    ) -> AgentToolExecution:
        balance_error = self.rules_catalog.solo_level_one_encounter_error(
            state,
            enemy_names,
            enemy_hp,
            enemy_ac,
        )
        if balance_error:
            return self._error(balance_error)
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
        return self._success(
            tool_name="encounter.start",
            summary=f"遭遇开始：{len(enemy_names)} 组敌人",
            payload=payload,
            event_type="encounter_started",
            state_patch={"scene": "combat", "encounter": encounter.model_dump(mode="json")},
        )

    def add_enemy(
        self,
        state: GameState,
        name: str,
        hp_max: int = 10,
        ac: int = 10,
        initiative_bonus: int = 0,
        side: str = "enemy",
        auto_roll_initiative: bool = True,
    ) -> AgentToolExecution:
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
        return self._success(
            tool_name="encounter.add_enemy",
            summary=f"敌人已加入：{combatant.name}",
            payload=payload,
            event_type="combatant_added",
            state_patch={"scene": "combat", "encounter": state.encounter.model_dump(mode="json")},
        )

    def save_monster_template(
        self,
        state: GameState,
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
    ) -> AgentToolExecution:
        if state.encounter and state.encounter.active:
            balance_error = self.rules_catalog.solo_level_one_monster_template_error(
                state,
                challenge_rating,
                hp_max,
                ac,
                actions,
            )
            if balance_error:
                return self._error(balance_error)
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
            traits=self._normalize_text_entries(traits),
            actions=self._normalize_text_entries(actions),
            reactions=self._normalize_text_entries(reactions),
            bonus_actions=self._normalize_text_entries(bonus_actions),
            source="game-authored",
        )
        state.monster_templates[monster.monster_id] = monster

        payload = {
            "monster_id": monster.monster_id,
            "name": monster.name,
            "creature_type": monster.creature_type,
            "challenge_rating": monster.challenge_rating,
            "scope": "game",
        }
        return self._success(
            tool_name="monster.save_game_template",
            summary=f"本局怪物模板已保存：{monster.name}",
            payload=payload,
            event_type="monster_template_saved",
            state_patch={"monster_templates": {monster.monster_id: monster.model_dump(mode="json")}},
        )

    def spawn_monster_from_template(
        self,
        state: GameState,
        monster_ref: str,
        quantity: int = 1,
        custom_name: str = "",
        hp_override: int = 0,
        side: str = "enemy",
        auto_roll_initiative: bool = True,
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        monster = self._load_monster_template(state, monster_ref)
        if not monster:
            return self._error(f"Monster template not found: {monster_ref}")

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
        return self._success(
            tool_name="monster.spawn_from_template",
            summary=f"Spawned {len(spawned)} combatant(s) from template {monster.name}",
            payload=payload,
            event_type="monster_spawned",
            state_patch={"scene": "combat", "encounter": state.encounter.model_dump(mode="json")},
        )

    def attack_target(
        self,
        state: GameState,
        attacker_ref: str,
        target_ref: str,
        attack_bonus: Optional[int] = None,
        damage_expression: str = "",
        damage_type: str = "",
        resolution_mode: str = "normal",
        reason: str = "",
        attack_name: str = "",
        roll_mode: str = "normal",
        cast_id: str = "",
    ) -> AgentToolExecution:
        if cast_id:
            from spell_resolution import resolve_spell_attack
            try:
                result = resolve_spell_attack(state, attacker_ref, target_ref, cast_id, damage_type, roll_mode)
            except ValueError as exc:
                return self._error(str(exc))
            return self._success(
                tool_name="combat.attack_target", event_type="attack_resolved",
                summary=f"{result['attacker_name']} {result['spell_name']}：{result['attack_total']} vs AC {result['target_ac']}，伤害 {result['damage_total']}",
                payload={key: value for key, value in result.items() if key != "patch"}, state_patch=result["patch"],
            )
        logic = GameLogic(state)
        try:
            logic.require_current_actor(attacker_ref)
            logic.require_turn_action_available("attack_target")
        except ValueError as exc:
            return self._error(str(exc))

        roll_mode_error = self._roll_mode_error(reason, roll_mode)
        if roll_mode_error:
            return self._error(roll_mode_error)

        requested_attack_bonus = attack_bonus
        requested_damage_expression = damage_expression
        attacker = self._linked_character(state, logic, attacker_ref)
        if attacker:
            try:
                profile = self.rules_catalog.resolve_character_attack_profile(
                    attacker,
                    attack_name=attack_name,
                    requested_attack_bonus=attack_bonus,
                    requested_damage_expression=damage_expression,
                )
            except ValueError as exc:
                return self._error(str(exc))
            attack_bonus = int(profile["attack_bonus"])
            damage_expression = str(profile["damage_expression"])
            damage_type = str(profile["damage_type"])
            resolved_attack_name = str(profile["attack_name"])
            modifier_source = "character_sheet"
        else:
            if attack_bonus is None or not str(damage_expression or "").strip():
                return self._error("Non-character attacks require attack_bonus and damage_expression")
            attack_bonus = int(attack_bonus)
            balance_error = self.rules_catalog.solo_level_one_npc_attack_error(
                state,
                attack_bonus,
                damage_expression,
            )
            if balance_error:
                return self._error(balance_error)
            resolved_attack_name = str(attack_name or "")
            modifier_source = "explicit_non_character"

        result = logic.resolve_attack(
            attacker_ref=attacker_ref,
            target_ref=target_ref,
            attack_bonus=attack_bonus,
            damage_expression=damage_expression,
            damage_type=damage_type,
            resolution_mode=resolution_mode,
            roll_mode=roll_mode,
        )
        if not result:
            return self._error(f"Attack target not found: {target_ref}")

        damage_type_display = self.library.localize_game_terms(result["damage_type"])
        target_defeat_state_display = self.library.localize_game_terms(result["target_defeat_state"].title())
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
            "damage_type_display": damage_type_display,
            "resolution_mode": result["resolution_mode"],
            "roll_mode": result["roll_mode"],
            "attack_name": resolved_attack_name,
            "requested_attack_bonus": requested_attack_bonus,
            "requested_damage_expression": requested_damage_expression,
            "modifier_source": modifier_source,
            "target_hp_current": result["target_hp_current"],
            "target_defeat_state": result["target_defeat_state"],
            "target_defeat_state_display": target_defeat_state_display,
            "reason": reason,
        }
        concentration_check = result.get("concentration_check")
        if concentration_check:
            payload["concentration_check"] = concentration_check
        hit_display = "命中" if result["hit"] else "未命中"
        summary = (
            f"{result['attacker_name']} 攻击 {result['target_name']}{self._roll_mode_summary(roll_mode)}："
            f"{result['attack_total']} vs AC {result['target_ac']} -> "
            f"{hit_display}"
        )
        if result["hit"]:
            summary += f"，伤害 {result['damage_total']}"
            if damage_type:
                summary += f" {damage_type_display}"
            summary += self._concentration_summary(concentration_check)
            if result["target_defeat_state"] != "active":
                summary += f" | 目标{target_defeat_state_display}"
        if reason:
            summary += f" | {self.library.localize_game_terms(reason)}"
        try:
            action_patch = logic.mark_current_action_used("attack_target")
        except ValueError as exc:
            return self._error(str(exc))
        return self._success(
            tool_name="combat.attack_target",
            summary=summary,
            payload=payload,
            event_type="attack_resolved",
            content=reason,
            state_patch=GameLogic._merge_patches(result["patch"], action_patch),
        )

    def roll_skill_check(
        self,
        state: GameState,
        actor_ref: str,
        skill_name: str,
        modifier: Optional[int] = None,
        dc: int = 0,
        reason: str = "",
        roll_mode: str = "normal",
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        try:
            logic.require_current_actor(actor_ref)
            logic.require_turn_action_available("roll_skill_check")
        except ValueError as exc:
            return self._error(str(exc))

        roll_mode_error = self._roll_mode_error(reason, roll_mode)
        if roll_mode_error:
            return self._error(roll_mode_error)

        requested_skill_name = skill_name
        canonical_skill_name = self.rules_catalog.normalize_skill_name(skill_name)
        actor = logic.get_character(actor_ref)
        resolved_modifier: Optional[int] = None
        if actor:
            resolved_modifier = self.rules_catalog.get_skill_modifier(actor, canonical_skill_name)
        else:
            combatant = logic.get_combatant(actor_ref)
            if combatant:
                resolved_modifier = int(
                    combatant.skills.get(
                        canonical_skill_name,
                        combatant.skills.get(
                            requested_skill_name,
                            self._combatant_ability_modifier(
                                combatant,
                                SKILL_TO_ABILITY.get(canonical_skill_name, "wisdom"),
                            ),
                        ),
                    )
                )
        result = logic.roll_skill_check(
            actor_ref=actor_ref,
            skill_name=canonical_skill_name,
            modifier=int(resolved_modifier or 0),
            dc=dc,
            roll_mode=roll_mode,
        )
        skill_display = self.library.localize_game_terms(canonical_skill_name)
        payload = {
            **result,
            "requested_skill_name": requested_skill_name,
            "skill_name_display": skill_display,
            "modifier_source": "character_sheet" if actor else "combatant_sheet",
            "reason": reason,
        }
        summary = f"{result['actor_name']} {skill_display}检定{self._roll_mode_summary(roll_mode)} {result['total']}"
        if dc > 0:
            summary += f" vs DC {dc} -> {'成功' if result['success'] else '失败'}"
        if reason:
            summary += f" | {self.library.localize_game_terms(reason)}"
        try:
            action_patch = logic.mark_current_action_used("roll_skill_check")
        except ValueError as exc:
            return self._error(str(exc))
        return self._success(
            tool_name="check.skill",
            summary=summary,
            payload=payload,
            event_type="skill_check",
            content=reason,
            state_patch=action_patch,
        )

    def roll_saving_throw(
        self,
        state: GameState,
        target_ref: str,
        save_name: str,
        dc: int = 0,
        modifier: Optional[int] = None,
        reason: str = "",
        roll_mode: str = "normal",
        source_ref: str = "",
        spell_name: str = "",
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        roll_mode_error = self._roll_mode_error(reason, roll_mode)
        if roll_mode_error:
            return self._error(roll_mode_error)
        requested_save_name = save_name
        canonical_save_name = self.rules_catalog.normalize_save_name(save_name)
        target = self._linked_character(state, logic, target_ref)
        combatant = logic.get_combatant(target_ref)
        if not target and not combatant:
            return self._error(f"Saving throw target not found: {target_ref}")
        if target:
            resolved_modifier = self.rules_catalog.get_save_modifier(target, canonical_save_name)
            modifier_source = "character_sheet"
        elif modifier is not None:
            resolved_modifier = int(modifier)
            modifier_source = "explicit_non_character"
        elif combatant:
            resolved_modifier = int(
                combatant.saving_throws.get(
                    canonical_save_name,
                    combatant.saving_throws.get(
                        requested_save_name,
                        self._combatant_ability_modifier(combatant, canonical_save_name),
                    ),
                )
            )
            modifier_source = "combatant_sheet"

        requested_dc = int(dc or 0)
        resolved_dc = requested_dc
        dc_source = "explicit_effect"
        resolved_spell_name = ""
        if source_ref:
            source_character = self._linked_character(state, logic, source_ref)
            source_combatant = logic.get_combatant(source_ref)
            if not source_character and not source_combatant:
                return self._error(f"Saving throw source not found: {source_ref}")
            if source_character:
                if not str(spell_name or "").strip():
                    return self._error("Character-caused saving throws require spell_name")
                try:
                    spell_profile = self.rules_catalog.get_spell_save_profile(source_character, spell_name)
                except ValueError as exc:
                    return self._error(str(exc))
                if canonical_save_name != spell_profile["save_name"]:
                    return self._error(
                        f"{spell_profile['spell_name']} requires a {spell_profile['save_name']} saving throw, "
                        f"not {canonical_save_name}"
                    )
                resolved_dc = int(spell_profile["dc"])
                dc_source = str(spell_profile["dc_source"])
                resolved_spell_name = str(spell_profile["spell_name"])
            else:
                dc_source = "explicit_non_character_effect"
        elif str(spell_name or "").strip():
            return self._error("spell_name requires source_ref")
        if resolved_dc <= 0:
            return self._error("Saving throw DC must be a positive integer")

        result = logic.roll_saving_throw(
            target_ref=target_ref,
            save_name=canonical_save_name,
            modifier=int(resolved_modifier or 0),
            dc=resolved_dc,
            roll_mode=roll_mode,
        )
        save_display = self.library.localize_game_terms(canonical_save_name.title())
        payload = {
            **result,
            "requested_save_name": requested_save_name,
            "save_name_display": save_display,
            "modifier_source": modifier_source,
            "requested_dc": requested_dc,
            "dc_source": dc_source,
            "source_ref": source_ref,
            "spell_name": resolved_spell_name,
            "reason": reason,
        }
        summary = f"{result['target_name']} {save_display}豁免{self._roll_mode_summary(roll_mode)} {result['total']} vs DC {resolved_dc} -> {'成功' if result['success'] else '失败'}"
        if reason:
            summary += f" | {self.library.localize_game_terms(reason)}"
        return self._success(
            tool_name="check.saving_throw",
            summary=summary,
            payload=payload,
            event_type="saving_throw",
            content=reason,
        )

    def cast_spell(self, state: GameState, caster_ref: str, spell_name: str,
                   slot_level: int = 0, reason: str = "") -> AgentToolExecution:
        from spell_resolution import cast_spell
        try:
            payload, patch = cast_spell(state, self.rules_catalog, caster_ref, spell_name, slot_level)
        except ValueError as exc:
            return self._error(str(exc))
        payload["reason"] = reason
        summary = f"{payload['caster_name']} 施放 {payload['spell_name']}"
        if payload["resolved_slot_level"]:
            summary += f"，消耗 {payload['resolved_slot_level']} 环法术位"
        return self._success(tool_name="magic.cast_spell", summary=summary, payload=payload,
                             event_type="spell_cast", content=reason, state_patch=patch)


    def use_item(
        self,
        state: GameState,
        user_ref: str,
        item_name: str,
        quantity: int = 1,
        reason: str = "",
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        try:
            logic.require_turn_action_available("use_item")
            result = logic.use_inventory_item(
                user_ref=user_ref,
                item_name=item_name,
                quantity=quantity,
            )
        except ValueError as exc:
            return self._error(str(exc))

        user = result["character"]
        item = result["item"]
        payload = {
            "user_id": user.character_id,
            "user_name": user.name,
            "item_name": item.name,
            "item_name_display": self.library.localize_game_terms(item.name),
            "quantity_used": result["quantity"],
            "quantity_remaining": item.quantity,
            "reason": reason,
        }
        summary = f"{user.name} 使用 {result['quantity']} x {self.library.localize_game_terms(item.name)}"
        if reason:
            summary += f" | {self.library.localize_game_terms(reason)}"
        try:
            action_patch = logic.mark_current_action_used("use_item")
        except ValueError as exc:
            return self._error(str(exc))
        return self._success(
            tool_name="inventory.use_item",
            summary=summary,
            payload=payload,
            event_type="item_used",
            content=reason,
            state_patch=GameLogic._merge_patches(result["patch"], action_patch),
        )

    def use_feature(
        self,
        state: GameState,
        actor_ref: str,
        feature_name: str,
        action_cost: str = "action",
        resource_name: str = "",
        resource_cost: int = 0,
        reason: str = "",
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        try:
            result = logic.resolve_feature_use(
                actor_ref=actor_ref,
                feature_name=feature_name,
                action_cost=action_cost,
                resource_name=resource_name,
                resource_cost=resource_cost,
            )
        except ValueError as exc:
            return self._error(str(exc))

        feature_display = self.library.localize_game_terms(result["feature_name"])
        payload = {
            "actor_type": result["actor_type"],
            "actor_id": result["actor_id"],
            "actor_name": result["actor_name"],
            "feature_name": result["feature_name"],
            "feature_name_display": feature_display,
            "action_cost": result["action_cost"],
            "action_cost_display": self._action_cost_display(result["action_cost"]),
            "resource_name": result["resource_name"],
            "resource_cost": result["resource_cost"],
            "resource_before": result["resource_before"],
            "resource_after": result["resource_after"],
            "reason": reason,
        }
        summary = (
            f"{result['actor_name']} 使用特性：{feature_display}"
            f"（{payload['action_cost_display']}）"
        )
        if result["resource_cost"] > 0:
            summary += (
                f"，消耗 {result['resource_cost']} 点 {self.library.localize_game_terms(result['resource_name'])}"
                f"（{result['resource_after']} 剩余）"
            )
        if reason:
            summary += f" | {self.library.localize_game_terms(reason)}"
        return self._success(
            tool_name="feature.use",
            summary=summary,
            payload=payload,
            event_type="feature_used",
            content=reason,
            state_patch=result["patch"],
        )

    def set_initiative(self, state: GameState, combatant_ref: str, initiative: int) -> AgentToolExecution:
        logic = GameLogic(state)
        combatant = logic.set_initiative(combatant_ref, initiative)
        if not combatant:
            return self._error(f"Combatant not found: {combatant_ref}")

        payload = {
            "combatant_id": combatant.combatant_id,
            "name": combatant.name,
            "initiative": combatant.initiative,
        }
        return self._success(
            tool_name="encounter.set_initiative",
            summary=f"{combatant.name} 先攻设为 {combatant.initiative}",
            payload=payload,
            event_type="initiative_set",
            state_patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
        )

    def roll_initiative(self, state: GameState, combatant_ref: str) -> AgentToolExecution:
        logic = GameLogic(state)
        result = logic.roll_initiative(combatant_ref)
        if not result:
            return self._error(f"Combatant not found: {combatant_ref}")

        combatant = result["combatant"]
        payload = {
            "combatant_id": combatant.combatant_id,
            "name": combatant.name,
            "initiative": combatant.initiative,
            "expression": result["expression"],
            "detail": result["detail"],
        }
        return self._success(
            tool_name="encounter.roll_initiative",
            summary=f"{combatant.name} 先攻 {combatant.initiative}，掷骰 {result['expression']}",
            payload=payload,
            event_type="initiative_rolled",
            state_patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
        )

    def advance_turn(self, state: GameState) -> AgentToolExecution:
        logic = GameLogic(state)
        combatant = logic.advance_turn()
        if not combatant:
            return self._error("No active encounter or initiative order")

        payload = {
            "current_combatant_id": combatant.combatant_id,
            "current_combatant_name": combatant.name,
            "round_number": state.encounter.round_number if state.encounter else 0,
        }
        return self._success(
            tool_name="encounter.advance_turn",
            summary=f"回合推进至 {combatant.name}",
            payload=payload,
            event_type="turn_advanced",
            state_patch={"encounter": state.encounter.model_dump(mode="json") if state.encounter else None},
        )

    # --- Setup catalog reads -------------------------------------------------
    # 这些只读工具让 Setup Agent 能拿到与前端建卡界面同一份权威目录，
    # 否则模型只能凭训练记忆臆造物种/背景/装备，导致后续 validate_character 必然失败。

    @staticmethod
    def _summarize_species(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": entry.get("name", ""),
            "speed": entry.get("speed", 30),
            "traits": list(entry.get("traits", [])),
        }

    @staticmethod
    def _summarize_background(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": entry.get("name", ""),
            "ability_bonuses": dict(entry.get("ability_bonuses", {})),
            "origin_feat": entry.get("origin_feat", ""),
            "skill_proficiencies": list(entry.get("skill_proficiencies", [])),
        }

    @staticmethod
    def _summarize_class(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": entry.get("name", ""),
            "hit_die": entry.get("hit_die", 8),
            "spellcasting_ability": entry.get("spellcasting_ability", ""),
            "spellcasting_mode": entry.get("spellcasting_mode", ""),
            "save_proficiencies": list(entry.get("save_proficiencies", [])),
            "skill_choices": list(entry.get("skill_choices", [])),
            "skills_to_choose": entry.get("skills_to_choose", 0),
            "starting_cantrips": entry.get("starting_cantrips", 0),
            "starting_prepared_spells": entry.get("starting_prepared_spells", 0),
            "starter_equipment_option_ids": [
                option.get("id", "")
                for option in (entry.get("starter_equipment_options") or [])
            ],
        }

    def list_character_options(self, state: GameState, category: str = "all", name: str = "") -> AgentToolExecution:
        normalized_category = str(category or "all").strip().lower()
        supported = {"all", "species", "backgrounds", "origin_feats", "classes", "ability_generation"}
        if normalized_category not in supported:
            return self._error(
                f"Unsupported category: {category}. Use one of {', '.join(sorted(supported))}."
            )

        catalog = self.rules_catalog.get_builder_catalog()
        lookup = str(name or "").strip()
        payload: Dict[str, Any] = {"category": normalized_category}

        if lookup:
            # 指定名称时返回单条完整定义，避免模型对着摘要继续猜细节。
            resolvers = {
                "species": self.rules_catalog.get_species,
                "backgrounds": self.rules_catalog.get_background,
                "classes": self.rules_catalog.get_class_def,
            }
            if normalized_category not in resolvers:
                return self._error("The name filter only applies to species, backgrounds, or classes.")
            entry = resolvers[normalized_category](lookup)
            if not entry:
                return self._error(f"Unknown {normalized_category[:-1] if normalized_category.endswith('s') else normalized_category}: {lookup}")
            payload["entry"] = entry
            summary = f"建卡目录：{lookup}"
        else:
            if normalized_category in {"all", "ability_generation"}:
                payload["ability_generation"] = catalog.get("ability_generation", {})
            if normalized_category in {"all", "species"}:
                payload["species"] = [self._summarize_species(item) for item in catalog.get("species", [])]
            if normalized_category in {"all", "backgrounds"}:
                payload["backgrounds"] = [self._summarize_background(item) for item in catalog.get("backgrounds", [])]
            if normalized_category in {"all", "origin_feats"}:
                payload["origin_feats"] = [item.get("name", "") for item in catalog.get("origin_feats", [])]
            if normalized_category in {"all", "classes"}:
                payload["classes"] = [self._summarize_class(item) for item in catalog.get("classes", [])]
            summary = f"建卡目录已读取：{normalized_category}"

        return self._success(
            tool_name="character.list_options",
            summary=summary,
            payload=payload,
            event_type="character_options_listed",
            content=normalized_category,
        )

    def list_class_spells(
        self,
        state: GameState,
        class_name: str = "",
        max_level: Optional[int] = None,
        spell_name: str = "",
    ) -> AgentToolExecution:
        requested_spell = str(spell_name or "").strip()
        if requested_spell:
            details = self.library.get_spell_details(requested_spell)
            if not details:
                return self._error(f"Unknown spell: {requested_spell}")
            return self._success(
                tool_name="library.spell_details",
                summary=f"法术资料：{details.get('name', requested_spell)}",
                payload={"spell": details},
                event_type="spell_details_read",
                content=str(details.get("name") or requested_spell),
            )

        requested_class = str(class_name or "").strip()
        if not requested_class:
            return self._success(
                tool_name="library.class_list",
                summary="可用施法职业法术库列表",
                payload={"classes": self.library.get_all_classes()},
                event_type="spell_library_listed",
            )

        library_key = self.rules_catalog.resolve_spell_library_key(requested_class)
        spells = self.library.get_spells_by_class(library_key)
        if not spells:
            return self._error(
                f"No spell library for class: {requested_class}. Available keys: {', '.join(self.library.get_all_classes())}"
            )

        if max_level is not None:
            try:
                level_cap = int(max_level)
            except (TypeError, ValueError):
                return self._error("max_level must be an integer spell level.")
            spells = [item for item in spells if int(item.get("level", 0)) <= level_cap]

        payload = {
            "class_name": requested_class,
            "spell_library_key": library_key,
            "spells": [
                {
                    "name": item.get("name", ""),
                    "level": item.get("level", 0),
                    "school": item.get("school", ""),
                    "casting_time": item.get("casting_time", ""),
                    "concentration": bool(item.get("concentration", False)),
                }
                for item in spells
            ],
        }
        return self._success(
            tool_name="library.class_spells",
            summary=f"{requested_class} 法术列表（{len(payload['spells'])} 条）",
            payload=payload,
            event_type="class_spells_listed",
            content=library_key,
        )

    def list_starter_equipment(self, state: GameState, class_name: str, option_id: str = "") -> AgentToolExecution:
        class_def = self.rules_catalog.get_class_def(str(class_name or "").strip())
        if not class_def:
            return self._error(f"Unknown class: {class_name}")

        options = self.rules_catalog.get_starter_options(class_def)
        payload: Dict[str, Any] = {
            "class_name": class_def.get("name", class_name),
            "custom_purchase_budget_gp": self.rules_catalog.get_custom_purchase_budget_gp(class_def),
            "options": [
                {
                    "id": option.get("id", ""),
                    "label": option.get("label", ""),
                    "description": option.get("description", ""),
                    "gold_gp": int(option.get("gold_gp", 0)),
                    "items": [item.get("name", "") for item in option.get("items", [])],
                    "choices": [
                        {
                            "id": group.get("id", ""),
                            "label": group.get("label", ""),
                            "options": [
                                {
                                    "id": choice.get("id", ""),
                                    "label": choice.get("label", ""),
                                    "items": [item.get("name", "") for item in choice.get("items", [])],
                                }
                                for choice in group.get("options", [])
                            ],
                        }
                        for group in option.get("choices", [])
                    ],
                }
                for option in options
            ],
        }

        requested_option = str(option_id or "").strip()
        if requested_option:
            selected = self.rules_catalog.get_starter_option(class_def, requested_option)
            if not selected or selected.get("id") != requested_option:
                return self._error(f"Unknown starter equipment option for {class_name}: {requested_option}")
            payload["selected_option"] = selected

        payload["shop_catalog"] = [
            {
                "item_id": item.get("id", ""),
                "name": item.get("name", ""),
                "cost_gp": item.get("cost_gp", 0),
                "type": item.get("type", ""),
            }
            for item in get_shop_catalog()
        ]

        return self._success(
            tool_name="character.list_starter_equipment",
            summary=f"{payload['class_name']} 初始装备选项（{len(payload['options'])} 组）",
            payload=payload,
            event_type="starter_equipment_listed",
            content=str(payload["class_name"]),
        )

    def validate_character_sheet(self, state: GameState, character_ref: str) -> AgentToolExecution:
        logic = GameLogic(state)
        character = logic.get_character(character_ref)
        if not character:
            return self._error(f"Unknown character: {character_ref}")

        errors = self.rules_catalog.validate_character(character)
        payload = {
            "character_id": character.character_id,
            "name": character.name,
            "valid": not errors,
            "errors": errors,
        }
        summary = (
            f"角色卡校验通过：{character.name}"
            if not errors
            else f"角色卡校验发现 {len(errors)} 个问题：{character.name}"
        )
        return self._success(
            tool_name="character.validate_sheet",
            summary=summary,
            payload=payload,
            event_type="character_sheet_validated",
            content=character.name,
            status="success" if not errors else "warning",
        )

    def create_party_character(
        self,
        state: GameState,
        name: str,
        class_name: str,
        species: str = "Human",
        background_name: str = "",
        ability_scores: Optional[Dict[str, int]] = None,
        ability_generation_method: str = "standard_array",
        skill_proficiencies: Optional[List[str]] = None,
        cantrips: Optional[List[str]] = None,
        prepared_spells: Optional[List[str]] = None,
        starter_option_id: str = "",
        starter_choice_ids: Optional[Dict[str, str]] = None,
        alignment: str = "Neutral",
        set_active: bool = True,
    ) -> AgentToolExecution:
        if state.campaign.setup_complete:
            return self._error("Party setup is already complete; use level_up or downtime tools instead.")

        limit = int(state.campaign.party_size_limit or 0)
        if limit and len(state.characters) >= limit:
            return self._error(f"Party size limit reached: {limit}")

        clean_name = " ".join(str(name or "").split()).strip()
        if not clean_name:
            return self._error("create_party_character requires a non-empty character name.")
        if any(existing.name == clean_name for existing in state.characters.values()):
            return self._error(f"A party member named {clean_name} already exists.")

        draft = Character(
            name=clean_name,
            species=str(species or "Human").strip() or "Human",
            race=str(species or "Human").strip() or "Human",
            background_name=str(background_name or "").strip(),
            class_name=str(class_name or "").strip(),
            ability_generation_method=str(ability_generation_method or "standard_array").strip().lower(),
            skill_proficiencies={str(skill): 1 for skill in (skill_proficiencies or []) if str(skill).strip()},
            starter_option_id=str(starter_option_id or "").strip(),
            starter_choice_ids={str(key): str(value) for key, value in (starter_choice_ids or {}).items()},
            alignment=str(alignment or "Neutral").strip() or "Neutral",
        )
        if ability_scores:
            draft.stats = Stats(**{
                key: int(value)
                for key, value in ability_scores.items()
                if key in Stats.model_fields
            })
        draft.spells.cantrips = [str(item) for item in (cantrips or []) if str(item).strip()]
        draft.spells.prepared = [str(item) for item in (prepared_spells or []) if str(item).strip()]

        draft = self.rules_catalog.apply_builder_defaults(draft)
        errors = self.rules_catalog.validate_character(draft)
        if errors:
            # 校验失败时绝不落地半成品角色，让模型带着具体错误重试。
            return self._error(
                "Character validation failed: " + "; ".join(errors),
                response={"ok": False, "error": "Character validation failed", "errors": errors},
            )

        state.characters[draft.character_id] = draft
        if set_active or not state.active_character_id:
            state.active_character_id = draft.character_id

        if state.campaign.phase in {"character_creation", "party_creation"} and state.characters:
            state.campaign.phase = "adventure_selection"

        payload = {
            "character_id": draft.character_id,
            "name": draft.name,
            "species": draft.species,
            "class_name": draft.class_name,
            "level": draft.level,
            "hp_max": draft.hp_max,
            "ac": draft.ac,
            "stats": draft.stats.model_dump(mode="json"),
            "active_character_id": state.active_character_id,
            "party_size": len(state.characters),
            "campaign_phase": state.campaign.phase,
        }
        return self._success(
            tool_name="character.create_party_member",
            summary=f"队伍成员已创建：{draft.name}（{draft.class_name} {draft.level} 级）",
            payload=payload,
            event_type="party_character_created",
            content=draft.name,
            state_patch={
                "characters": {draft.character_id: draft.model_dump(mode="json")},
                "active_character_id": state.active_character_id,
                "campaign": {"phase": state.campaign.phase},
            },
        )

    def select_adventure_hook(self, state: GameState, adventure_id: str) -> AgentToolExecution:
        if not state.characters:
            return self._error("Select an adventure only after at least one party member exists.")
        if state.campaign.selected_adventure_id:
            return self._error(
                f"An adventure is already locked in: {state.campaign.selected_adventure_id}"
            )

        requested = str(adventure_id or "").strip()
        selected = None
        for hook in state.campaign.available_adventures:
            if hook.adventure_id == requested or hook.title == requested:
                selected = hook
                break
        if not selected:
            available = ", ".join(
                f"{hook.adventure_id}({hook.title})" for hook in state.campaign.available_adventures
            )
            return self._error(f"Unknown adventure option: {adventure_id}. Available: {available or 'none'}")

        # 与 REST 的 select-adventure 保持同一套阶段推进，但不在这里写存档或聊天记录；
        # 主回合的 finalize_turn 才是唯一提交点。
        state.campaign.selected_adventure_id = selected.adventure_id
        state.campaign.phase = "exploration"
        state.campaign.setup_complete = True
        state.campaign.current_chapter_number = 1
        state.campaign.current_chapter_title = f"第一章：{selected.title}"
        state.campaign.current_chapter_summary = selected.summary
        state.scene = "exploration"
        log_entry = f"选择冒险：{selected.title}"
        state.adventure_log.append(log_entry)

        payload = {
            "adventure_id": selected.adventure_id,
            "title": selected.title,
            "summary": selected.summary,
            "opening_scene": selected.opening_scene or selected.summary,
            "chapter_number": state.campaign.current_chapter_number,
            "chapter_title": state.campaign.current_chapter_title,
        }
        return self._success(
            tool_name="campaign.select_adventure",
            summary=f"冒险已选定：{selected.title}",
            payload=payload,
            event_type="adventure_selected",
            content=selected.title,
            state_patch={
                "scene": state.scene,
                "adventure_log": state.adventure_log,
                "campaign": {
                    "phase": state.campaign.phase,
                    "selected_adventure_id": state.campaign.selected_adventure_id,
                    "setup_complete": state.campaign.setup_complete,
                    "current_chapter_number": state.campaign.current_chapter_number,
                    "current_chapter_title": state.campaign.current_chapter_title,
                    "current_chapter_summary": state.campaign.current_chapter_summary,
                },
            },
        )

    # --- Encounter math ------------------------------------------------------
    # 表格与算法移植自 5e.tools（见 encounter_math 模块头部注释）。这两个工具只做
    # 计算和建议，不改动任何权威状态：难度是 DM 的判断依据，不是结算结果。

    def _party_levels(self, state: GameState) -> List[int]:
        return [max(1, int(character.level)) for character in state.characters.values()]

    def _encounter_enemy_groups(self, state: GameState) -> List[Dict[str, Any]]:
        """Collapse the active encounter's non-party combatants into CR groups."""

        if not (state.encounter and state.encounter.active):
            return []

        grouped: Dict[tuple, Dict[str, Any]] = {}
        for combatant in state.encounter.combatants.values():
            if combatant.linked_character_id:
                continue
            if combatant.defeat_state and combatant.defeat_state != "active":
                continue
            template = None
            if combatant.monster_template_id:
                template = state.monster_templates.get(combatant.monster_template_id)
                if template is None:
                    template = self.monster_storage.load_monster(combatant.monster_template_id)
            challenge_rating = template.challenge_rating if template else ""
            cr_source = "template"
            if not normalize_cr(challenge_rating):
                # start_encounter/add_enemy 允许即兴敌人，它们没有模板也没有伤害输出信息，
                # 只能按防御面估一个近似 CR，并如实标注来源，避免读者当成权威数据。
                estimated = defensive_challenge_rating(combatant.hp_max, combatant.ac)
                challenge_rating = estimated or ""
                cr_source = "estimated_from_defense" if estimated else "unknown"
            key = (combatant.name, str(challenge_rating), cr_source)
            if key in grouped:
                grouped[key]["count"] += 1
            else:
                grouped[key] = {
                    "name": combatant.name,
                    "challenge_rating": challenge_rating,
                    "count": 1,
                    "cr_source": cr_source,
                }
        return list(grouped.values())

    def estimate_encounter_difficulty(
        self,
        state: GameState,
        enemies: Optional[List[Dict[str, Any]]] = None,
        party_levels: Optional[List[int]] = None,
    ) -> AgentToolExecution:
        levels = [int(level) for level in (party_levels or []) if int(level) > 0]
        if not levels:
            levels = self._party_levels(state)
        if not levels:
            return self._error("No party members are available to budget an encounter against.")

        groups = list(enemies or [])
        source = "arguments"
        if not groups:
            groups = self._encounter_enemy_groups(state)
            source = "active_encounter"
        if not groups:
            return self._error(
                "Provide enemies with challenge ratings, or run this while an encounter with living enemies is active."
            )

        try:
            result = estimate_encounter_difficulty(levels, groups)
        except ValueError as exc:
            return self._error(str(exc))

        if not result["breakdown"]:
            return self._error(
                "No enemy had a usable challenge rating: " + ", ".join(result["unknown_challenge_ratings"])
            )

        result["enemy_source"] = source
        summary = (
            f"遭遇难度：{result['difficulty_label']}（{result['encounter_xp']} XP / "
            f"中等预算 {result['budget']['moderate']} XP）"
        )
        return self._success(
            tool_name="encounter.estimate_difficulty",
            summary=summary,
            payload=result,
            event_type="encounter_difficulty_estimated",
            content=str(result["difficulty"]),
        )

    def estimate_monster_cr(
        self,
        state: GameState,
        hp: int,
        ac: int,
        damage_per_round: int,
        attack_bonus: int = 0,
        save_dc: int = 0,
        monster_ref: str = "",
    ) -> AgentToolExecution:
        try:
            result = estimate_challenge_rating(
                hp=int(hp),
                ac=int(ac),
                damage_per_round=int(damage_per_round),
                attack_bonus=int(attack_bonus),
                save_dc=int(save_dc),
            )
        except (TypeError, ValueError) as exc:
            return self._error(str(exc))

        reference = str(monster_ref or "").strip()
        if reference:
            template = self._load_monster_template(state, reference)
            if not template:
                return self._error(f"Unknown monster template: {reference}")
            declared = normalize_cr(template.challenge_rating)
            result["monster_ref"] = reference
            result["declared_challenge_rating"] = declared or str(template.challenge_rating)
            result["matches_declared"] = bool(declared) and declared == result["challenge_rating"]

        summary = (
            f"CR 估算：{result['challenge_rating']}"
            f"（防御 {result['defensive_cr']} / 攻击 {result['offensive_cr']}，{result['experience_points']} XP）"
        )
        return self._success(
            tool_name="monster.estimate_cr",
            summary=summary,
            payload=result,
            event_type="monster_cr_estimated",
            content=str(result["challenge_rating"]),
        )

    def remove_combatant(self, state: GameState, combatant_ref: str) -> AgentToolExecution:
        logic = GameLogic(state)
        try:
            combatant = logic.remove_combatant(combatant_ref)
        except ValueError as exc:
            return self._error(str(exc))
        if not combatant:
            return self._error(f"Combatant not found in the active encounter: {combatant_ref}")

        payload = {
            "combatant_id": combatant.combatant_id,
            "name": combatant.name,
            "encounter_active": bool(state.encounter and state.encounter.active),
        }
        return self._success(
            tool_name="encounter.remove_combatant",
            summary=f"{combatant.name} 已离开战斗",
            payload=payload,
            event_type="combatant_removed",
            state_patch={
                "scene": state.scene,
                "campaign": {"phase": state.campaign.phase},
                "encounter": state.encounter.model_dump(mode="json") if state.encounter else None,
            },
        )

    def end_encounter(self, state: GameState) -> AgentToolExecution:
        logic = GameLogic(state)
        outcome = logic.finalize_encounter()
        if not outcome:
            return self._error("No encounter to end")

        encounter = outcome["encounter"]
        payload = {
            **outcome["summary_payload"],
            "adventure_log_entry": outcome["adventure_log_entry"],
        }
        return self._success(
            tool_name="encounter.end",
            summary=outcome["summary"],
            payload=payload,
            event_type="encounter_ended",
            state_patch={
                "scene": state.scene,
                "campaign": {"phase": state.campaign.phase},
                "encounter": encounter.model_dump(mode="json"),
                "adventure_log": state.adventure_log,
            },
        )
