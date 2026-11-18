"""Validation nodes and deterministic repair constraints."""

import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import SystemMessage
from game_logic import GameLogic
from combat_flow import handoff_ready, needs_advance, finishing_tools
from models import Combatant, GameState, ToolResult, ValidationIssue
from dm_workflow.state import DMGraphState
from dm_workflow.policies import TOOL_RESULT_ALIASES


class TurnValidation:
    """Validation nodes and deterministic repair constraints."""

    @staticmethod
    def _hostile_intent(graph_state: DMGraphState) -> bool:
        turn_intent = dict(graph_state.get("turn_intent") or {})
        return "hostile_attack" in list(turn_intent.get("intent_tags") or [])

    def _hostile_action_resolved(self, state: GameState, graph_state: DMGraphState) -> bool:
        flow = graph_state.get("combat_flow", {})
        if flow.get("action_done") or flow.get("stop_at_player") or handoff_ready(state, flow):
            return True
        active = state.characters.get(flow.get("input_actor_id")) or state.get_active_char()
        initial = graph_state.get("initial_game_state") or {}
        if active and (initial.get("encounter") or {}).get("active") and any(
            item.get("actor_id") == active.character_id and item.get("action_spent")
            for item in self._tool_result_payloads(graph_state, "hide_actor")
        ):
            # 战斗中的躲藏已经使用动作；普通角色不能被强制再攻击，伏击意图留待后续行动。
            return True
        # 无法行动本身也是权威结果，不能继续向倒地角色索要一次不存在的攻击。
        if active and (active.hp_current <= 0 or str(active.defeat_state or "active") != "active" or GameLogic.is_incapacitated(active)):
            return True
        attack_payloads = self._tool_result_payloads(graph_state, "attack_target")
        if not attack_payloads:
            return False
        if not active:
            return True
        if any(str(payload.get("attacker_name") or "").strip() == active.name for payload in attack_payloads):
            return True
        # 若敌方先手已经让行动角色无法行动，这次攻击意图也已有权威失败结果，不能死循环索要攻击。
        return active.hp_current <= 0 or str(active.defeat_state or "active") != "active"

    def _unresolved_declared_spells(self, graph_state: DMGraphState) -> List[str]:
        from spell_rules import declared_spells
        declared = declared_spells(graph_state, self.library)
        resolved = {self.library.normalize_spell_name(payload.get("spell_name", ""))
                    for payload in self._tool_result_payloads(graph_state, "cast_spell")
                    if payload.get("effect_resolution") == "completed"}
        resolved.update(self.library.normalize_spell_name(payload.get("spell_name", ""))
                        for payload in self._tool_result_payloads(graph_state, "attack_target")
                        if payload.get("spell_name") and payload.get("attacks_remaining") == 0)
        return [name for name in declared if name not in resolved]

    def _managed_spell_pending(self, graph_state: DMGraphState) -> bool:
        return bool(self._unresolved_declared_spells(graph_state))

    def _authoritative_resolution_pending(self, graph_state: DMGraphState) -> bool:
        state = GameState.model_validate(graph_state["game_state"])
        if graph_state.get("unresolved_operations") or state.pending_spell_attacks or self._managed_spell_pending(graph_state):
            return True
        if not self._hostile_intent(graph_state):
            return False
        return not self._hostile_action_resolved(state, graph_state)

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
        if self._managed_spell_pending(graph_state) and tool_name in {"advance_turn", "add_status"}:
            return "Resolve the declared spell through its complete cast_spell contract first; do not skip required saves or apply its conditions manually."
        if tool_name == "cast_spell" and len(self._unresolved_declared_spells({**graph_state, "tool_results": []})) > 1:
            checks = self._tool_result_payloads(graph_state, "check_spell_sequence")
            if not checks:
                return "Check the complete multi-spell sequence with check_spell_sequence before casting."
            if not checks[-1].get("valid"):
                return "The intended spell sequence conflicts with rules; use report_rule_conflict and let the player revise."
            check = checks[-1]
            declared = self._unresolved_declared_spells({**graph_state, "tool_results": []})
            if not set(declared).issubset(set(check.get("spells", []))):
                return "The preflight omitted a declared spell; check the complete intended sequence."
            state = GameState.model_validate(graph_state["game_state"])
            logic = GameLogic(state)
            from spell_effects import actor_id
            try:
                source = actor_id(logic, args.get("caster_ref", ""))
                refs = [*args.get("target_refs", [])] + ([args["target_ref"]] if args.get("target_ref") else [])
                targets = sorted(actor_id(logic, ref) for ref in refs)
            except ValueError as exc:
                return str(exc)
            canonical = self.library.normalize_spell_name(args.get("spell_name", ""))
            next_index = sum('slot_level' in entry for entry in state.spell_cast_history) - check.get('cast_history_count', 0)
            sequence = check.get('sequence', [])
            expected = sequence[next_index:next_index + 1] if next_index >= 0 else []
            if source != check.get("caster_id") or not any(entry["spell_name"] == canonical
                    and sorted(entry["target_ids"]) == targets and (not args.get("slot_level") or entry["slot_level"] == args["slot_level"])
                    for entry in expected):
                return "This cast differs from the checked sequence; check the intended caster, targets and slot level first."
        if graph_state.get("combat_flow") and handoff_ready(GameState.model_validate(graph_state["game_state"]), graph_state["combat_flow"]) and tool_name not in {"end_encounter", "report_rule_conflict"}:
            return "Next player decision reached; stop tools and request a new player action."
        if tool_name == "start_encounter" and "stealth_approach" in (graph_state.get("turn_intent") or {}).get("intent_tags", []):
            from stealth_rules import is_invisible
            state = GameState.model_validate(graph_state["game_state"])
            active = state.get_active_char()
            hidden = is_invisible(active)
            attempted = any(item.get("actor_id") == active.character_id for item in self._tool_result_payloads(graph_state, "hide_actor")) if active else False
            if not hidden and args.get("surprised_refs") and args.get("surprise_basis", "hidden") != "other":
                return "An ambush cannot mark targets surprised after an unconfirmed or failed hide; resolve hide_actor first or start normally with approach_reason."
            if args.get("surprise_basis") == "other" and not str(args.get("approach_reason") or "").strip():
                return "Explain the independent, established reason for unawareness without hiding. Do not invent a successful Hide."
            if not hidden and not attempted and not str(args.get("approach_reason") or "").strip():
                return "Adjudicate the stealth approach BEFORE initiative: call hide_actor with real cover/sight conditions, or explain why hiding is impossible/enemies are alert in approach_reason."
        if tool_name == "adjust_hp" and int(args.get("amount") or 0) < 0:
            target_ref = str(args.get("target_ref") or "").strip().casefold()
            resolved_target_names = {target_ref}
            state_payload = graph_state.get("game_state")
            if state_payload:
                state = GameState.model_validate(state_payload)
                for character in state.characters.values():
                    if target_ref in {character.character_id.casefold(), character.name.casefold()}:
                        resolved_target_names.add(character.name.casefold())
                if state.encounter:
                    for combatant in state.encounter.combatants.values():
                        if target_ref in {combatant.combatant_id.casefold(), combatant.name.casefold()}:
                            resolved_target_names.add(combatant.name.casefold())
            requested_damage = abs(int(args.get("amount") or 0))
            if any(
                int(payload.get("damage_total") or 0) == requested_damage
                and str(payload.get("target_name") or "").strip().casefold() in resolved_target_names
                for payload in self._tool_result_payloads(graph_state, "attack_target")
            ):
                return (
                    "attack_target already applied this attack's damage to the target. "
                    "Do not call adjust_hp for the same damage again."
                )
        if tool_name in {"append_adventure_log", "record_evidence"}:
            indirect_signal_error = self._indirect_signal_record_error(
                str(graph_state.get("user_input") or ""),
                args,
            )
            if indirect_signal_error:
                return indirect_signal_error
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
    def _indirect_signal_record_error(user_input: str, args: Dict[str, Any]) -> str:
        payload_text = " ".join(
            str(value or "")
            for key, value in args.items()
            if key in {"entry", "title", "summary", "source_ref", "location", "tags"}
        )
        context = f"{user_input} {payload_text}"
        indirect_markers = ["敲击", "敲", "手势", "暗号", "编码", "信号", "剪影", "影子", "脚印", "足迹"]
        if not any(marker in context for marker in indirect_markers):
            return ""

        certainty_patterns = [
            r"(?:确认|证明|表明).{0,12}(?:身份|人数|存活|活着|神志|危险|威胁|就是)",
            r"(?:身份|人数|存活|活着|神志|危险|威胁).{0,8}(?:已确认|确定|属实)",
            r"(?:均|都)(?:存活|活着|能行动|神志清醒)",
            r"危险就在",
        ]
        uncertainty_markers = ["未核实", "无法确认", "不能确认", "尚不确定", "可能", "推测", "若约定", "身份不明"]
        if any(re.search(pattern, payload_text) for pattern in certainty_patterns) and not any(
            marker in payload_text for marker in uncertainty_markers
        ):
            return (
                "Indirect signals cannot authenticate identity, headcount, survival, mental state, source, or danger by themselves. "
                "Record the observed signal pattern as fact and mark every interpretation as unverified; one source may imitate multiple replies."
            )
        return ""

    @staticmethod
    def _chapter_completion_requested(user_input: str) -> bool:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return False
        explicit_values = re.findall(
            r"\bcompleted\b[\"']?\s*(?:=|:)\s*(true|false)\b",
            lowered,
        )
        if explicit_values:
            # 工具参数里的显式布尔值优先于附近自然语言中的“完成记录后”等流程措辞。
            return explicit_values[-1] == "true"
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
    def _indirect_signal_response_issue(user_input: str, response_text: str) -> str:
        context = f"{user_input or ''} {response_text or ''}"
        if not any(marker in context for marker in ["敲击", "敲", "手势", "暗号", "编码", "信号", "剪影", "影子", "脚印", "足迹"]):
            return ""
        overclaim_patterns = [
            r"(?:哈兰|艾拉|奥图).{0,10}(?:对应|就是|身份|确认)",
            r"(?:有|是|为|确认).{0,8}(?:三人|三名|三个|三位|三个人|三个能)",
            r"(?:三人|三名|三个|三位|三个人).{0,8}(?:敲击者|存在|人|幸存者)",
            r"那三个(?:敲击者|存在|人|幸存者)",
            r"(?:均|都)(?:存活|活着|能行动|神志清醒)",
            r"危险就在(?:他们|身边|这里)",
            r"威胁就在(?:他们|身边|这里)",
        ]
        if any(re.search(pattern, response_text or "") for pattern in overclaim_patterns):
            return (
                "The scene contains only indirect signals. Rewrite the player-facing narration so it states the observed signal pattern, "
                "but treats identity, headcount, survival, mental state, and danger as unverified interpretations. "
                "Do not say that coded replies prove named people or that danger is definitely present."
            )
        return ""

    @staticmethod
    def _is_player_controlled_combatant(state: GameState, combatant: Combatant) -> bool:
        linked_character_id = combatant.linked_character_id
        return bool(
            linked_character_id
            and linked_character_id in state.characters
            and state.is_player_controlled(linked_character_id)
            and combatant.side.strip().lower() == "party"
        )

    @classmethod
    def _dm_controlled_turn_pending(cls, graph_state: DMGraphState) -> bool:
        if str(graph_state.get("turn_status") or "") == "failed":
            return False
        # 私有图已装配权威状态；损坏的内部状态不能被当作“无需处理敌方回合”。
        state = GameState.model_validate(graph_state["game_state"])
        encounter = state.encounter
        if not encounter or not encounter.active or not encounter.turn_order_started:
            return False
        current = encounter.get_current_combatant()
        return bool((not current and state.active_spell_effects) or (current and not cls._is_player_controlled_combatant(state, current)
                    and not handoff_ready(state, graph_state.get("combat_flow", {}))))

    @staticmethod
    def _combat_turn_claim_error(state: GameState, response_text: str) -> str:
        encounter = state.encounter
        if not encounter or not encounter.active:
            return ""
        current = encounter.get_current_combatant()
        active_character = state.get_active_char()
        if not current or not active_character:
            return ""
        player_turn_markers = [
            "现在轮到你",
            "轮到你了",
            "你的回合开始",
            f"{active_character.name}的回合",
            f"{active_character.name}的回合开始",
            f"轮到{active_character.name}",
        ]
        claims_player_turn = any(marker in response_text for marker in player_turn_markers)
        if claims_player_turn and current.linked_character_id != active_character.character_id:
            return (
                f"The narration claims the player's turn has started, but authoritative combat state still names {current.name} "
                "as the current combatant. Resolve or explicitly forgo that combatant's action and call advance_turn before "
                "claiming the player can act. Otherwise narrate that the current combatant is still acting."
            )
        return ""

    @staticmethod
    def _build_validation_message(notes: List[str]) -> Optional[Any]:
        if not notes:
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
        if graph_state.get("rules_feedback"):
            return {"turn_status": "rules_feedback", "validation_status": "ok", "allowed_tools": [],
                    "final_response": str(graph_state["rules_feedback"]["message"]),
                    "rules_feedback": dict(graph_state["rules_feedback"])}
        state = GameState.model_validate(graph_state["game_state"])
        messages = list(graph_state.get("messages", []))
        timeline_append = list(graph_state.get("timeline_append", []))
        state_delta = dict(graph_state.get("state_delta", {}))
        validation_notes: List[str] = list(graph_state.get("validation_notes", []))
        validation_issues: List[Dict[str, Any]] = list(graph_state.get("validation_issues", []))
        current_notes_start = len(validation_notes)
        current_issues_start = len(validation_issues)
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
        if self._managed_spell_pending(graph_state):
            mark_repair(validator="spell_effect_resolution", tools=["register_scene_actor", "cast_spell", "report_rule_conflict", "request_player_choice", "check_spell_sequence"],
                        summary="Declared spells still lack completed resolution. Register missing established targets, resolve the spell through cast_spell, or report a concrete rule conflict without narration.",
                        metadata={"spells": self._unresolved_declared_spells(graph_state)})
        if graph_state.get("unresolved_operations"):
            mark_repair(validator="unresolved_operation", tools=["register_scene_actor", "report_rule_conflict", *[item["tool_name"] for item in graph_state["unresolved_operations"]]],
                        summary="A required rules operation failed and has not been resolved. Correct that operation or provide short rule feedback; unrelated successful tools do not complete it.",
                        metadata={"operations": [item["tool_name"] for item in graph_state["unresolved_operations"]]})
        if state.pending_spell_attacks:
            from spell_resolution import spell_turn_key
            active_casts = [cast for cast in state.pending_spell_attacks if cast.turn_key == spell_turn_key(state)]
            if active_casts:
                mark_repair(validator="spell_attack_resolution", tools=["attack_target"],
                            summary="Resolve pending spell attacks with attack_target using their cast_id before narration.",
                            metadata={"casts": [cast.model_dump(mode="json") for cast in active_casts]})
        hostile_resolution_pending = self._hostile_intent(graph_state) and not self._hostile_action_resolved(
            state,
            graph_state,
        )
        if hostile_resolution_pending and not (encounter and encounter.active):
            mark_repair(
                validator="hostile_action_resolution",
                summary=(
                    "Player declared a hostile action, but no active encounter or player attack result exists; "
                    "call start_encounter instead of completing the turn with suspense narration."
                ),
                tools=["start_encounter"],
                metadata={"intent_tags": list((graph_state.get("turn_intent") or {}).get("intent_tags") or [])},
            )
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
                        or combatant.temp_hp != character.temp_hp
                        or combatant.hp_max != character.hp_max
                        or combatant.ac != character.ac
                        or combatant.initiative_bonus != character.initiative_bonus
                        or combatant.status_effects != list(character.status_effects)
                        or combatant.hiding != character.hiding
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
                        -(combatant.initiative if combatant.initiative is not None else -999),
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
                if not current and state.active_spell_effects:
                    mark_repair(validator="spell_turn_events", tools=["advance_turn"], summary="No actor can act yet. Resolve the next turn events and repeat saves with advance_turn; do not invent recovery.")
                player_combatants = [combatant for combatant in encounter.combatants.values()
                                     if self._is_player_controlled_combatant(state, combatant)]
                party_defeated = bool(player_combatants) and all(
                    combatant.hp_current <= 0 or combatant.defeat_state != "active"
                    for combatant in encounter.combatants.values() if combatant.side in {"party", "ally"}
                )
                if party_defeated:
                    # 队伍全员倒地/被俘后，advance_turn 只会再次选中敌人；应通过显式工具收尾。
                    mark_repair(validator="party_defeat", tools=["end_encounter"],
                                summary="All player-controlled combatants are defeated. Call end_encounter and narrate the existing defeat states; do not keep advancing enemy turns or invent death/capture outcomes.")
                if (
                    hostile_resolution_pending
                    and current
                    and encounter.turn_order_started
                    and logic._combatant_can_take_turn(current)
                    and self._is_player_controlled_combatant(state, current)
                    and not encounter.turn_action_used
                    and not handoff_ready(state, graph_state.get("combat_flow", {}))
                ):
                    mark_repair(
                        validator="hostile_action_resolution",
                        summary=(
                            "The player can now act, but the declared hostile action has no authoritative attack result; "
                            "call attack_target before final narration."
                        ),
                        tools=["attack_target"],
                        metadata={"combatant_id": current.combatant_id, "combatant_name": current.name},
                    )
                if (
                    current
                    and not party_defeated
                    and not handoff_ready(state, graph_state.get("combat_flow", {}))
                    and encounter.turn_order_started
                    and logic._combatant_can_take_turn(current)
                    and not self._is_player_controlled_combatant(state, current)
                ):
                    if encounter.turn_action_used:
                        repair_summary = (
                            f"DM-controlled combatant {current.name} has completed its action but still owns the turn; "
                            "call advance_turn before returning control to the player."
                        )
                        dm_turn_tools = ["advance_turn"]
                    else:
                        repair_summary = (
                            f"DM-controlled combatant {current.name} still owns the current turn. Resolve its action with "
                            "an authoritative combat tool, or explicitly forgo it by calling advance_turn; do not finish "
                            "the DM response while this combatant remains current."
                        )
                        dm_turn_tools = [
                            "attack_target",
                            "cast_spell",
                            "use_feature",
                            "roll_skill_check",
                            "advance_turn",
                        ]
                    mark_repair(
                        validator="dm_controlled_turn",
                        summary=repair_summary,
                        tools=dm_turn_tools,
                        metadata={
                            "combatant_id": current.combatant_id,
                            "combatant_name": current.name,
                            "side": current.side,
                            "turn_action_used": encounter.turn_action_used,
                            "turn_action_tool": encounter.turn_action_tool,
                        },
                    )
                if (needs_advance(state, graph_state.get("combat_flow", {}))
                        and any(c.side == 'enemy' and c.hp_current > 0 and c.defeat_state == 'active' for c in encounter.combatants.values())):
                    mark_repair(validator="player_turn_handoff", tools=finishing_tools(state),
                                summary="The input player's primary action is spent. Resolve only an explicitly declared legal bonus action if needed, then call advance_turn, resolve subsequent DM actors, and stop BEFORE the next player-controlled actor acts. Do not replay the old action.")
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
                        summary="No active enemies remain. Resolve any explicitly declared legal bonus action first, then call end_encounter before final narration. The successful attack is complete; do not repeat it.",
                        tools=["end_encounter", *[name for name in finishing_tools(state) if name in {"use_feature", "cast_spell", "use_item"}]],
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
        turn_intent = self._refresh_turn_intent_for_state(
            state,
            graph_state.get("user_input", ""),
            phase,
            scene,
            existing_intent=dict(graph_state.get("turn_intent") or {}),
        ).model_dump(mode="json")
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
        if validation_status == "repair_required" and int(graph_state.get("tool_call_rounds", 0) or 0) >= max(24, self.max_tool_rounds * 2, min(48, 4 * len(state.encounter.combatants) + 4) if state.encounter else 0):
            # 修复可以补足必要动作，但不能每轮续期而绕过总工具预算。
            mark_failed(validator="repair_budget", summary="Required repairs exceeded the turn's tool budget; staged changes must roll back.")
        if validation_status == "repair_required":
            repair_requirements: List[str] = []
            if self._has_validation_issue({"validation_issues": validation_issues[current_issues_start:]}, "chapter_completion", "repair_required"):
                repair_requirements.append(
                    "For chapter_completion, call record_chapter_progress with completed=true. "
                    "Do not call it with completed omitted or false."
                )
            repair_text = (
                "State verification requires repair before any final narration.\n"
                f"Allowed repair tools: {' | '.join(repair_tools) if repair_tools else 'none'}.\n"
                f"Mandatory repair requirements: {' | '.join(repair_requirements) if repair_requirements else 'Use the exact repair requested by the issue.'}\n"
                "Call the necessary repair tool now. Do not narrate outcomes until the repair tool succeeds.\n"
                "Issues:\n- " + "\n- ".join(validation_notes[current_notes_start:])
            )
            messages.append(SystemMessage(content=repair_text, id="current-state-validation"))
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
            # add_messages按固定ID替换历史指令；审计历史仍保留，但不再反复命令DM重做。
            text = "当前状态校验已通过。此前的修复要求已解除；成功工具的结果继续有效，不要重复攻击或把内部修复报告为玩家规则冲突。"
            if validation_status != 'ok':
                text = "当前校验未通过：" + "；".join(validation_notes[current_notes_start:])
            messages.append(SystemMessage(content=text, id="current-state-validation"))

        if int(graph_state.get("repeated_tool_errors", 0)) >= 3:
            mark_failed(validator="repeated_tool_error", summary="The same tool failure repeated three times without progress; staged changes must roll back.")
        final_response = str(graph_state.get("final_response") or "")
        turn_status = str(graph_state.get("turn_status") or "running")
        if validation_status == "failed":
            final_response = "状态校验发现无法安全自动修复的问题；本回合未提交，请重试。"
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
