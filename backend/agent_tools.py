"""Framework-neutral DM tool implementations for agent runtimes."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from game_logic import DiceRoller, GameLogic
from library import Library
from models import GameState, MonsterTemplate, MonsterTextEntry, SessionEvent, ToolResult
from rag import RAGEngine
from rules_catalog import ABILITY_ALIAS, SKILL_TO_ABILITY, RuleCatalog
from storage import MonsterStorage


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

    def roll_dice(self, state: GameState, expression: str, reason: str = "") -> AgentToolExecution:
        total, detail = DiceRoller.roll(expression)
        payload = {
            "expression": expression,
            "reason": reason,
            "total": total,
            "detail": detail,
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
    ) -> AgentToolExecution:
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
        dc: int,
        modifier: Optional[int] = None,
        reason: str = "",
        roll_mode: str = "normal",
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        roll_mode_error = self._roll_mode_error(reason, roll_mode)
        if roll_mode_error:
            return self._error(roll_mode_error)
        requested_save_name = save_name
        canonical_save_name = self.rules_catalog.normalize_save_name(save_name)
        target = self._linked_character(state, logic, target_ref)
        combatant = logic.get_combatant(target_ref)
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
        else:
            resolved_modifier = 0
            modifier_source = "missing_target"
        result = logic.roll_saving_throw(
            target_ref=target_ref,
            save_name=canonical_save_name,
            modifier=int(resolved_modifier or 0),
            dc=dc,
            roll_mode=roll_mode,
        )
        save_display = self.library.localize_game_terms(canonical_save_name.title())
        payload = {
            **result,
            "requested_save_name": requested_save_name,
            "save_name_display": save_display,
            "modifier_source": modifier_source,
            "reason": reason,
        }
        summary = f"{result['target_name']} {save_display}豁免{self._roll_mode_summary(roll_mode)} {result['total']} vs DC {dc} -> {'成功' if result['success'] else '失败'}"
        if reason:
            summary += f" | {self.library.localize_game_terms(reason)}"
        return self._success(
            tool_name="check.saving_throw",
            summary=summary,
            payload=payload,
            event_type="saving_throw",
            content=reason,
        )

    def cast_spell(
        self,
        state: GameState,
        caster_ref: str,
        spell_name: str,
        slot_level: int = 0,
        reason: str = "",
    ) -> AgentToolExecution:
        logic = GameLogic(state)
        try:
            logic.require_current_actor(caster_ref)
        except ValueError as exc:
            return self._error(str(exc))

        caster = logic.get_character(caster_ref)
        if not caster:
            return self._error(f"Spell caster not found: {caster_ref}")

        validation = self.rules_catalog.can_cast_spell(
            character=caster,
            spell_name=spell_name,
            slot_level=slot_level or None,
        )
        if not validation["ok"]:
            return self._error(validation.get("error", "Spell validation failed"), validation)

        resolved_slot = int(validation["resolved_slot_level"])
        canonical_spell_name = str(validation.get("spell_name") or validation["spell"].get("name") or spell_name)
        action_cost = self.rules_catalog.spell_action_cost(validation["spell"])
        try:
            logic.require_turn_slot_available(action_cost, "cast_spell")
        except ValueError as exc:
            return self._error(str(exc))
        previous_concentration = caster.concentration_spell
        self.rules_catalog.consume_spell_slot(caster, resolved_slot)
        if bool(validation["spell"].get("concentration")):
            caster.concentration_spell = canonical_spell_name
            caster.concentration_spell_level = int(validation["spell"].get("level", 0))
        payload = {
            "caster_id": caster.character_id,
            "caster_name": caster.name,
            "spell_name": canonical_spell_name,
            "requested_spell_name": spell_name,
            "spell_level": int(validation["spell"].get("level", 0)),
            "resolved_slot_level": resolved_slot,
            "action_cost": action_cost,
            "concentration": bool(validation["spell"].get("concentration")),
            "previous_concentration_spell": previous_concentration,
            "current_concentration_spell": caster.concentration_spell,
            "reason": reason,
            "remaining_slots": {
                level: {
                    "total": slot.total,
                    "used": slot.used,
                }
                for level, slot in caster.spells.slots.items()
            },
        }
        summary = f"{caster.name} 施放 {canonical_spell_name}"
        if resolved_slot > 0:
            summary += f"，消耗 {resolved_slot} 环法术位"
        if reason:
            summary += f" | {reason}"
        try:
            action_patch = logic.mark_current_turn_slot_used(action_cost, "cast_spell")
        except ValueError as exc:
            return self._error(str(exc))
        return self._success(
            tool_name="magic.cast_spell",
            summary=summary,
            payload=payload,
            event_type="spell_cast",
            content=reason,
            state_patch=GameLogic._merge_patches(
                {
                    "characters": {
                        caster.character_id: {
                            "spells": caster.spells.model_dump(mode="json"),
                            "concentration_spell": caster.concentration_spell,
                            "concentration_spell_level": caster.concentration_spell_level,
                        }
                    }
                },
                action_patch,
            ),
        )

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
