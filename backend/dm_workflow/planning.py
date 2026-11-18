"""Turn intent, phase routing and input decisions."""

import json
from typing import Any, Dict, List, Optional

from langgraph.types import interrupt
from agent_tools import merge_patch
from models import GameState, TurnIntent
from dm_workflow.state import DMGraphState
from dm_workflow.tool_schemas import LANGGRAPH_TOOL_SCHEMAS
from dm_workflow.policies import (
    PHASE_POLICIES,
    ACTION_RESOLUTION_TERMS,
    HOSTILE_ACTION_TERMS,
    INTENT_FALLBACK_TYPES,
    INTENT_FALLBACK_TAGS,
    INTENT_FALLBACK_TOOLS,
    TURN_PROFILE_POLICIES,
)


class TurnPlanning:
    """Turn intent, phase routing and input decisions."""

    @staticmethod
    def _phase_policy(phase: str) -> Dict[str, Any]:
        normalized = str(phase or "").strip().lower()
        return dict(PHASE_POLICIES.get(normalized, PHASE_POLICIES["exploration"]))

    @classmethod
    def _derive_phase(cls, state: GameState) -> str:
        current_phase = str(state.campaign.phase or "").strip().lower()
        current_scene = str(state.scene or "").strip().lower()
        selected_adventure = state.campaign.selected_adventure()

        if state.encounter and state.encounter.active:
            return "combat"
        if not state.characters:
            return "party_creation"
        if current_phase == "character_creation":
            return "character_creation"
        if current_phase in {"level_up", "downtime"}:
            return current_phase
        if current_scene in {"level_up", "downtime"}:
            return current_scene
        if (
            not state.campaign.setup_complete
            or not state.campaign.selected_adventure_id
            or selected_adventure is None
        ):
            return "adventure_selection"
        return "exploration"

    @staticmethod
    def _expected_scene_for_phase(phase: str, fallback_scene: str) -> str:
        policy = PHASE_POLICIES.get(phase, {})
        expected = str(policy.get("scene") or "").strip().lower()
        return expected or str(fallback_scene or "setup").strip().lower() or "setup"

    @classmethod
    def _phase_blockers(cls, state: GameState, phase: str) -> List[str]:
        blockers = list(cls._phase_policy(phase).get("blockers", []))
        if phase == "adventure_selection" and not state.campaign.available_adventures:
            blockers.append("No adventure hooks are currently loaded.")
        if phase == "combat":
            encounter = state.encounter
            if not encounter or not encounter.active:
                blockers.append("No active encounter is available.")
            elif encounter.turn_order_started and not encounter.current_combatant_id:
                blockers.append("Initiative exists but there is no current combatant.")
            elif not encounter.turn_order_started:
                blockers.append("Initiative order is not fully ready yet.")
        return cls._unique_texts(blockers, limit=6)

    @classmethod
    def _normalize_phase_state(
        cls, state: GameState
    ) -> tuple[str, str, List[str], Dict[str, Any], Dict[str, Any]]:
        phase = cls._derive_phase(state)
        expected_scene = cls._expected_scene_for_phase(phase, state.scene)
        notes: List[str] = []
        patch: Dict[str, Any] = {}

        if state.campaign.phase != phase:
            state.campaign.phase = phase
            patch.setdefault("campaign", {})["phase"] = phase
            notes.append(f"Normalized campaign phase to {phase}.")
        if state.scene != expected_scene:
            state.scene = expected_scene
            patch["scene"] = expected_scene
            notes.append(f"Normalized scene to {expected_scene} for phase {phase}.")

        policy = cls._phase_policy(phase)
        return phase, expected_scene, notes, patch, policy

    @classmethod
    def _allowed_tool_names(cls, state: GameState, phase: str = "") -> List[str]:
        resolved_phase = str(phase or "").strip().lower() or cls._derive_phase(state)
        policy = cls._phase_policy(resolved_phase)
        return list(policy.get("tools", []))

    @staticmethod
    def _is_generic_followup(text: str) -> bool:
        normalized = " ".join((text or "").split()).strip().lower()
        if not normalized:
            return True
        generic_inputs = {
            "continue",
            "go on",
            "next",
            "ok",
            "okay",
            "sure",
            "start",
            "begin",
            "do it",
            "continue on",
            "继续",
            "继续吧",
            "开始",
            "下一步",
            "下一个",
            "就这样",
            "那就这样",
            "好的",
            "好",
            "行",
            "嗯",
        }
        return normalized in generic_inputs

    @classmethod
    def _build_required_input_request(cls, state: GameState, user_input: str, phase: str) -> Optional[Dict[str, Any]]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return {
                "kind": "clarification",
                "phase": phase,
                "prompt": "请明确说明你希望 DM 现在处理什么，或直接描述角色动作。",
                "details": {"reason": "empty_input"},
            }

        if phase == "adventure_selection" and cls._is_generic_followup(normalized_input):
            options = [
                {"adventure_id": hook.adventure_id, "title": hook.title}
                for hook in (state.campaign.available_adventures or [])[:4]
            ]
            return {
                "kind": "choice",
                "phase": phase,
                "prompt": "请先明确选择本章要跑的冒险。你可以回复冒险标题，或直接说“选第 2 个”。",
                "details": {"reason": "adventure_choice_required", "options": options},
            }

        if phase == "combat" and cls._is_generic_followup(normalized_input):
            current = state.encounter.get_current_combatant() if state.encounter else None
            return {
                "kind": "clarification",
                "phase": phase,
                "prompt": "请明确说明这回合要执行的动作，例如攻击哪个目标、施放什么法术，或声明闪避/脱离/准备动作。",
                "details": {
                    "reason": "combat_action_required",
                    "current_combatant": current.name if current else "",
                },
            }

        return None

    @staticmethod
    def _coerce_resume_input(value: Any) -> str:
        if isinstance(value, dict):
            text = value.get("message") or value.get("input") or value.get("content")
            return str(text).strip() if text else ""
        return str(value or "").strip()

    @staticmethod
    def _turn_profile_policy(profile: str) -> Dict[str, Any]:
        normalized = str(profile or "").strip().lower()
        return dict(TURN_PROFILE_POLICIES.get(normalized, TURN_PROFILE_POLICIES["action_resolution"]))

    @classmethod
    def _profile_allowed_tools(cls, base_tools: List[str], turn_profile: str) -> List[str]:
        policy = cls._turn_profile_policy(turn_profile)
        subset = list(policy.get("tool_subset", []))
        if not subset:
            return list(base_tools)
        base_lookup = set(base_tools)
        return [tool_name for tool_name in subset if tool_name in base_lookup]

    @staticmethod
    def _prioritize_tools(allowed_tools: List[str], suggested_tools: List[str]) -> List[str]:
        if not suggested_tools:
            return list(allowed_tools)
        ordered: List[str] = []
        seen = set()
        for tool_name in [*suggested_tools, *allowed_tools]:
            if tool_name in seen or tool_name not in allowed_tools:
                continue
            seen.add(tool_name)
            ordered.append(tool_name)
        return ordered

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        normalized = " ".join((text or "").split()).strip()
        if not normalized:
            return False
        lowered = normalized.casefold()
        question_markers = [
            "?",
            "\uff1f",
            "how",
            "what",
            "when",
            "why",
            "can i",
            "can we",
            "do i",
            "do we",
            "does",
            "\u5982\u4f55",
            "\u600e\u4e48",
            "\u600e\u6837",
            "\u662f\u5426",
            "\u80fd\u4e0d\u80fd",
            "\u53ef\u4ee5\u5417",
            "\u4e3a\u4ec0\u4e48",
            "\u662f\u4ec0\u4e48",
            "该不该",
            "要不要",
            "会不会",
            "能否",
            "询问",
            "追问",
            "打听",
        ]
        return any(marker in lowered for marker in question_markers)

    @classmethod
    def _action_terms_for_input(cls, user_input: str) -> List[str]:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return []
        return cls._unique_texts(
            [
                marker
                for marker in ACTION_RESOLUTION_TERMS
                if str(marker or "").strip() and str(marker).casefold() in lowered
            ],
            limit=6,
        )

    @staticmethod
    def _hostile_action_terms_for_input(user_input: str) -> List[str]:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return []
        return [term for term in HOSTILE_ACTION_TERMS if term.casefold() in lowered]

    def _agent_intent_fallback(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        scene: str,
    ) -> Optional[Dict[str, Any]]:
        """Ask the configured DM model for a bounded intent label when lexical routing has no signal."""

        if not self.enable_model or not str(user_input or "").strip():
            return None
        model = self._create_model()
        bind_model = getattr(model, "bind", None)
        if callable(bind_model):
            model = bind_model(
                max_tokens=280,
                response_format={"type": "json_object"},
                timeout=45,
            )
        active = state.get_active_char()
        classifier_context = {
            "phase": phase,
            "scene": scene,
            "encounter_active": bool(state.encounter and state.encounter.active),
            "active_character": active.name if active else "",
            "player_input": str(user_input or "").strip(),
        }
        messages = [
            self._system_prompt_message(
                "你是 D&D 回合意图路由器，不继续剧情、不判断行动结果。只输出一个 JSON 对象。"
                "turn_type 只能是 conversation、rules_reference、action_resolution、combat_resolution；"
                "intent_tags 只能从 hostile_attack、skill_action、spell_action、item_action、feature_action、"
                "stateful_action 中选择；suggested_tools 只能从 lookup_rules、roll_skill_check、"
                "roll_saving_throw、cast_spell、end_concentration、advance_time、use_item、use_feature、start_encounter、attack_target、"
                "adjust_currency、set_scene、append_adventure_log、record_evidence、record_search_outcome 中选择。"
                "玩家用武器、徒手、射击、伏击、偷袭或刺杀直接攻击生物时必须标记 hostile_attack；"
                "施放法术但没有直接武器攻击时使用 spell_action，不要附加 hostile_attack；"
                "等待、维持或结束已存在的法术不是重新施法；不要仅因出现法术名称建议cast_spell，实际游戏内等待可建议advance_time；"
                "若尚无遭遇，同时建议 start_encounter 和 attack_target。不要把明确行动降级为 conversation。"
            ),
            self._human_prompt_message(
                "请返回："
                '{"turn_type":"...","intent_tags":["..."],"suggested_tools":["..."],"reason":"..."}\n'
                + json.dumps(classifier_context, ensure_ascii=False)
            ),
        ]
        try:
            response = model.invoke(messages)
            raw_text = self._extract_message_content(response)
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start < 0 or end <= start:
                return None
            payload = json.loads(raw_text[start : end + 1])
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        turn_type = str(payload.get("turn_type") or "").strip().lower()
        if turn_type not in INTENT_FALLBACK_TYPES:
            return None
        tags = self._unique_texts(
            [
                str(item).strip().lower()
                for item in payload.get("intent_tags", [])
                if str(item).strip().lower() in INTENT_FALLBACK_TAGS
            ],
            limit=4,
        )
        suggested_tools = self._unique_texts(
            [
                str(item).strip()
                for item in payload.get("suggested_tools", [])
                if str(item).strip() in INTENT_FALLBACK_TOOLS
            ],
            limit=6,
        )
        if "hostile_attack" in tags:
            turn_type = "combat_resolution" if state.encounter and state.encounter.active else "action_resolution"
            hostile_tools = ["attack_target", *suggested_tools]
            if not (state.encounter and state.encounter.active):
                hostile_tools.insert(0, "start_encounter")
            suggested_tools = self._unique_texts(hostile_tools, limit=6)
        elif turn_type == "combat_resolution" and not (state.encounter and state.encounter.active):
            turn_type = "action_resolution"
        elif turn_type == "rules_reference" and "lookup_rules" not in suggested_tools:
            suggested_tools.insert(0, "lookup_rules")

        return {
            "turn_type": turn_type,
            "intent_tags": tags,
            "suggested_tools": suggested_tools,
            "reason": str(payload.get("reason") or "Agent classified an intent not covered by lexical routing.").strip()[:240],
        }

    def _suggested_resolution_tools(self, state: GameState, user_input: str, phase: str) -> List[str]:
        normalized = " ".join((user_input or "").split()).strip()
        if not normalized:
            return []

        lowered = normalized.casefold()
        suggestions: List[str] = self._explicit_tool_names_in_input(normalized)
        matched_spells = self._matched_spell_names(state, normalized)

        active = state.get_active_char()
        if active and active.hiding and any(term in lowered for term in ("大喊", "高声", "喊叫", "现身", "走出掩体", "离开掩体", "停止躲藏", "shout", "yell", "stop hiding")):
            suggestions.append("end_hiding")
        elif any(term in lowered for term in ("寻找躲藏", "找出躲藏", "搜索躲藏", "发现躲藏", "search hidden", "find hidden")):
            suggestions.append("search_hidden")
        elif any(term in lowered for term in ("躲藏", "潜行", "隐匿", "偷袭", "突袭", "伏击", "hide", "sneak", "ambush")):
            suggestions.append("hide_actor")

        if matched_spells or any(term in lowered for term in ["cast", "\u65bd\u6cd5", "\u6cd5\u672f"]):
            suggestions.append("cast_spell")
        if any(term.casefold() in lowered for term in HOSTILE_ACTION_TERMS):
            if phase in {"exploration", "downtime"} and not (state.encounter and state.encounter.active):
                suggestions.append("start_encounter")
            suggestions.append("attack_target")
        if any(
            term in lowered
            for term in [
                "save",
                "saving throw",
                "\u8c41\u514d",
            ]
        ):
            suggestions.append("roll_saving_throw")
        if any(
            term in lowered
            for term in [
                "perception",
                "investigation",
                "stealth",
                "listen",
                "sneak",
                "pick lock",
                "lockpick",
                "insight",
                "persuasion",
                "deception",
                "\u611f\u77e5",
                "\u8c03\u67e5",
                "\u6f5c\u884c",
                "\u503e\u542c",
                "\u5077\u542c",
                "\u6f5c\u5165",
                "\u64ac",
                "\u5f00\u9501",
                "\u65e0\u58f0",
                "\u6d1e\u6089",
                "\u8bf4\u670d",
                "\u6b3a\u7792",
                "\u68c0\u5b9a",
            ]
        ):
            suggestions.append("roll_skill_check")
        if any(
            term in lowered
            for term in [
                "use",
                "drink",
                "consume",
                "heal",
                "healing",
                "potion",
                "item",
                "\u4f7f\u7528",
                "\u6d88\u8017",
                "\u559d",
                "\u559d\u836f",
                "\u836f\u6c34",
                "\u7269\u54c1",
            ]
        ):
            suggestions.append("use_item")
        if any(
            term in lowered
            for term in [
                "feature",
                "ability",
                "trait",
                "class feature",
                "monster feature",
                "bonus action",
                "reaction",
                "second wind",
                "\u7279\u6027",
                "\u80fd\u529b",
                "\u804c\u4e1a\u7279\u6027",
                "\u602a\u7269\u7279\u6027",
                "\u9644\u8d60\u52a8\u4f5c",
                "\u9644\u52a0\u52a8\u4f5c",
                "\u53cd\u5e94",
                "\u52a8\u4f5c\u6fc0\u6d8c",
                "\u56de\u6c14",
            ]
        ):
            suggestions.append("use_feature")
        if any(
            term in lowered
            for term in [
                "heal",
                "healing",
                "damage",
                "hurt",
                "potion",
                "\u6cbb\u7597",
                "\u4f24\u5bb3",
                "\u559d\u836f",
                "\u836f\u6c34",
            ]
        ):
            suggestions.append("adjust_hp")
        if phase == "combat" and any(
            term in lowered
            for term in [
                "end turn",
                "next turn",
                "\u7ed3\u675f\u56de\u5408",
                "\u4e0b\u4e00\u56de\u5408",
                "\u8f6e\u5230",
            ]
        ):
            suggestions.append("advance_turn")
        acquisition_terms = [
            "take",
            "keep",
            "accept",
            "pick up",
            "接过",
            "收好",
            "拾起",
            "捡起",
            "拿起",
            "保管",
        ]
        evidence_artifact_terms = [
            "clue",
            "evidence",
            "fragment",
            "document",
            "letter",
            "token",
            "线索",
            "证据",
            "封片",
            "碎片",
            "残片",
            "文书",
            "信件",
            "残页",
            "令牌",
            "徽记",
        ]
        if any(term in lowered for term in acquisition_terms) and any(
            term in lowered for term in evidence_artifact_terms
        ):
            # 这里只提示模型检查是否应落库；玩家文本仍不是事实源，实际调用必须由权威上下文支持。
            suggestions.append("record_evidence")
        if self._chapter_completion_requested(normalized) or any(
            term in lowered
            for term in [
                "record chapter",
                "chapter progress",
                "\u8bb0\u5f55\u7ae0\u8282",
                "\u7ae0\u8282\u8fdb\u5ea6",
                "\u7ae0\u8282\u5df2\u8bb0\u5f55",
            ]
        ):
            suggestions.append("record_chapter_progress")

        return self._unique_texts(suggestions, limit=4)

    @classmethod
    def _explicit_tool_names_in_input(cls, user_input: str) -> List[str]:
        lowered = " ".join((user_input or "").split()).strip().casefold()
        if not lowered:
            return []

        matches: List[str] = []
        for schema in LANGGRAPH_TOOL_SCHEMAS:
            tool_name = str(schema.get("name") or "").strip()
            if tool_name and tool_name.casefold() in lowered:
                matches.append(tool_name)
        return cls._unique_texts(matches, limit=6)

    @staticmethod
    def _intent_risk_level(phase: str, turn_type: str, suggested_tools: List[str]) -> str:
        high_risk_tools = {"end_encounter", "set_defeat_state", "record_chapter_progress"}
        medium_risk_tools = {
            "adjust_hp",
            "add_status",
            "remove_status",
            "add_inventory_item",
            "adjust_currency",
            "use_item",
            "record_evidence",
            "record_search_outcome",
            "record_major_experience",
            "start_encounter",
            "attack_target",
            "cast_spell",
            "roll_saving_throw",
        }
        tool_set = set(suggested_tools or [])
        if tool_set & high_risk_tools:
            return "high"
        if phase == "combat" or turn_type == "combat_resolution" or tool_set & medium_risk_tools:
            return "medium"
        return "low"

    def _plan_turn_intent(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        scene: str = "",
        *,
        allow_agent_fallback: bool = False,
    ) -> TurnIntent:
        normalized_input = " ".join((user_input or "").split()).strip()
        phase_name = str(phase or "").strip().lower() or self._derive_phase(state)
        scene_name = str(scene or state.scene or "").strip().lower()
        rule_intent = self._classify_rule_intent(state, normalized_input)
        action_terms = self._action_terms_for_input(normalized_input)
        hostile_terms = self._hostile_action_terms_for_input(normalized_input)
        question_shape = self._looks_like_question(normalized_input)
        suggested_tools = self._suggested_resolution_tools(state, normalized_input, phase_name)
        intent_source = "deterministic"
        intent_tags = ["hostile_attack"] if hostile_terms else []
        if any(term in normalized_input.casefold() for term in ("躲藏", "潜行", "隐匿", "偷袭", "突袭", "伏击", "hide", "sneak", "ambush")):
            intent_tags.append("stealth_approach")
        agent_fallback = None
        preset_signal = bool(action_terms or suggested_tools or rule_intent.get("should_retrieve") or question_shape)
        if (
            allow_agent_fallback
            and normalized_input
            and not preset_signal
            and phase_name in {"exploration", "downtime"}
        ):
            agent_fallback = self._agent_intent_fallback(
                state,
                normalized_input,
                phase_name,
                scene_name,
            )
            if agent_fallback:
                intent_source = "agent_fallback"
                intent_tags = list(agent_fallback.get("intent_tags", []))
                suggested_tools = list(agent_fallback.get("suggested_tools", []))
                if agent_fallback.get("turn_type") == "rules_reference":
                    rule_intent = {
                        **rule_intent,
                        "intent": "rules_question",
                        "should_retrieve": True,
                        "reason": str(agent_fallback.get("reason") or "Agent classified a rules reference."),
                    }
        # 明示或可确定映射到写工具的玩家指令本身就是行动信号；不能因为措辞里同时出现“解释/规则”
        # 就降级成只允许 lookup_rules 的问答回合。
        has_resolution_action = bool(
            action_terms or [tool_name for tool_name in suggested_tools if tool_name != "lookup_rules"]
        )

        if phase_name in {"party_creation", "character_creation", "adventure_selection", "level_up"}:
            turn_type = "setup_guidance"
            reason = f"phase {phase_name} is setup-heavy and benefits from short decision-oriented replies"
        elif not normalized_input and phase_name == "combat":
            turn_type = "combat_resolution"
            reason = "empty input during an active encounter should still preserve combat-focused tool access"
        elif not normalized_input:
            turn_type = "conversation"
            reason = "empty or whitespace-only player input"
        elif agent_fallback:
            turn_type = str(agent_fallback.get("turn_type") or "conversation")
            reason = str(agent_fallback.get("reason") or "Agent classified an intent not covered by lexical routing.")
        elif phase_name == "combat" and has_resolution_action and not question_shape:
            turn_type = "combat_resolution"
            reason = "active encounter action should resolve directly instead of detouring into a rules-only turn"
        elif (
            rule_intent.get("should_retrieve")
            and has_resolution_action
            and not self._looks_like_rule_question(normalized_input)
        ):
            turn_type = "action_resolution"
            reason = "the turn references rules-sensitive mechanics, but the player is attempting a concrete action"
        elif phase_name == "combat" and not rule_intent.get("should_retrieve"):
            turn_type = "combat_resolution"
            reason = "active encounter turn should stay focused on concrete combat resolution"
        elif rule_intent.get("should_retrieve"):
            turn_type = "rules_reference"
            reason = str(rule_intent.get("reason", "rules-sensitive question or resolution"))
        elif phase_name == "combat":
            turn_type = "combat_resolution"
            reason = "active encounter turn should stay focused on concrete combat resolution"
        elif has_resolution_action:
            turn_type = "action_resolution"
            reason = "player attempted an action that likely needs adjudication or tracked consequences"
        elif question_shape:
            turn_type = "conversation"
            reason = "player asked an in-world or social question without obvious rules load"
        else:
            turn_type = "conversation"
            reason = "player input reads like low-friction narrative conversation"

        if turn_type == "rules_reference":
            suggested_tools = ["lookup_rules"]
        suggested_tools = self._unique_texts(suggested_tools, limit=4)
        risk_level = self._intent_risk_level(phase_name, turn_type, suggested_tools)

        return TurnIntent(
            turn_type=turn_type,
            reason=reason,
            phase=phase_name,
            scene=scene_name,
            risk_level=risk_level,
            needs_rules=bool(rule_intent.get("should_retrieve")),
            rag_intent=str(rule_intent.get("intent") or "none"),
            rag_reason=str(rule_intent.get("reason") or ""),
            focus_terms=list(rule_intent.get("focus_terms", [])),
            action_terms=action_terms,
            matched_spells=list(rule_intent.get("matched_spells", [])),
            suggested_tools=suggested_tools,
            # 风险等级只服务内部 guardrail/trace，不能推导玩家是否还欠一个决定。
            requires_confirmation=False,
            intent_source=intent_source,
            intent_tags=intent_tags,
        )

    def _refresh_turn_intent_for_state(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        scene: str,
        existing_intent: Optional[Dict[str, Any]] = None,
    ) -> TurnIntent:
        """Re-scope a classified intent after tools change the authoritative phase."""

        refreshed = self._plan_turn_intent(state, user_input, phase, scene)
        existing = dict(existing_intent or {})
        existing_tags = self._unique_texts(list(existing.get("intent_tags") or []), limit=4)
        if not existing_tags:
            return refreshed

        intent_tags = self._unique_texts([*existing_tags, *refreshed.intent_tags], limit=4)
        suggested_tools = self._unique_texts(
            [*list(existing.get("suggested_tools") or []), *refreshed.suggested_tools],
            limit=6,
        )
        turn_type = refreshed.turn_type
        if "hostile_attack" in intent_tags:
            if phase == "combat":
                turn_type = "combat_resolution"
                suggested_tools = self._unique_texts(
                    ["attack_target", *[item for item in suggested_tools if item != "start_encounter"]],
                    limit=6,
                )
            else:
                turn_type = "action_resolution"
                suggested_tools = self._unique_texts(["start_encounter", "attack_target", *suggested_tools], limit=6)

        return refreshed.model_copy(
            update={
                "turn_type": turn_type,
                "reason": str(existing.get("reason") or refreshed.reason),
                "risk_level": self._intent_risk_level(phase, turn_type, suggested_tools),
                "needs_rules": bool(existing.get("needs_rules") or refreshed.needs_rules),
                "rag_intent": str(existing.get("rag_intent") or refreshed.rag_intent),
                "rag_reason": str(existing.get("rag_reason") or refreshed.rag_reason),
                "focus_terms": self._unique_texts(
                    [*list(existing.get("focus_terms") or []), *refreshed.focus_terms],
                    limit=8,
                ),
                "action_terms": self._unique_texts(
                    [*list(existing.get("action_terms") or []), *refreshed.action_terms],
                    limit=8,
                ),
                "suggested_tools": suggested_tools,
                "intent_source": str(existing.get("intent_source") or refreshed.intent_source),
                "intent_tags": intent_tags,
            }
        )

    def _build_turn_advice(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        turn_profile: str,
        allowed_tools: List[str],
        turn_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile_name = str(turn_profile or "").strip().lower()
        raw_suggested_tools = list(
            (turn_intent or {}).get("suggested_tools")
            or self._suggested_resolution_tools(state, user_input, phase)
        )
        suggested_tools = [
            tool_name
            for tool_name in raw_suggested_tools
            if tool_name in allowed_tools
        ]

        expectation = "Respond naturally and only escalate into tools when needed."
        checklist: List[str] = []
        if profile_name == "conversation":
            expectation = "Direct in-world reply first; skip tools unless something durable or stateful is actually created."
            checklist = [
                "Do not turn a simple social beat into a mechanical resolution unless the player clearly pushes for one.",
                "When the conversation itself confirms an important clue, persist it proactively; never promote a player's unsupported assertion into world fact.",
            ]
        elif profile_name == "rules_reference":
            expectation = "Answer the rules question in one pass, ideally with a single lookup if needed."
            checklist = [
                "Keep the answer scoped to the asked rule.",
                "Avoid unrelated state mutation tools.",
            ]
            suggested_tools = ["lookup_rules"] if "lookup_rules" in allowed_tools else []
        elif profile_name == "action_resolution":
            expectation = "Resolve the attempted action with the minimum necessary tool chain, then narrate once."
            checklist = [
                "Prefer one core resolution tool before considering persistence tools.",
                "If the uncertain action needs a check and roll_skill_check is available, call it now; never merely say that a check is needed or unavailable.",
                "Only persist evidence, loot, or chapter progress if the fiction actually establishes it.",
            ]
            if "hostile_attack" in list((turn_intent or {}).get("intent_tags", [])):
                expectation = (
                    "Resolve the declared hostile action authoritatively. If no encounter exists, call start_encounter first; "
                    "the combat tool scope will refresh in this same player turn."
                )
                checklist = [
                    "Do not replace the declared attack with suspense narration.",
                    "Start the encounter when needed, follow initiative, and use attack_target when the player can act.",
                    "Narrate only after the hostile action has a tool-backed outcome.",
                ]
        elif profile_name == "combat_resolution":
            expectation = "Resolve one combat turn cleanly and avoid extra side actions or tool loops."
            checklist = [
                "Only resolve the current acting creature unless the turn is explicitly advanced.",
                "Advance the turn only after the acting creature has actually finished.",
            ]
        elif profile_name == "setup_guidance":
            expectation = "Keep the setup reply short and decision-oriented."
            checklist = [
                "Avoid dragging setup into freeform scene narration.",
            ]

        return {
            "turn_expectation": expectation,
            "suggested_tools": suggested_tools,
            "turn_checklist": checklist,
            "allowed_tools": self._prioritize_tools(allowed_tools, suggested_tools),
        }

    @staticmethod
    def _contains_any(text: str, terms: List[str]) -> bool:
        lowered = (text or "").casefold()
        return any(term.casefold() in lowered for term in terms if term)

    @staticmethod
    def _detect_input_warnings(text: str) -> List[str]:
        warnings: List[str] = []
        if not text:
            return warnings

        if "\ufffd" in text:
            warnings.append(
                "Input contains Unicode replacement characters; check client or shell text encoding."
            )

        # This catches the common Windows/stdin failure mode where CJK text arrives as question marks.
        question_count = text.count("?")
        if "???" in text or (question_count >= 6 and question_count / max(len(text), 1) > 0.2):
            warnings.append(
                "Input contains dense question-mark placeholders; non-ASCII text may have been corrupted before reaching the API."
            )

        return warnings

    @staticmethod
    def _unique_texts(values: List[str], limit: int = 4) -> List[str]:
        unique: List[str] = []
        seen = set()
        for raw in values:
            text = " ".join(str(raw or "").split()).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(text)
            if len(unique) >= limit:
                break
        return unique

    def _classify_turn_profile(
        self,
        state: GameState,
        user_input: str,
        phase: str,
        turn_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        phase_name = str(phase or "").strip().lower() or self._derive_phase(state)
        base_tools = self._allowed_tool_names(state, phase=phase_name)
        default_guidance = self._turn_profile_policy("action_resolution").get("guidance", "")
        intent_payload = dict(turn_intent or {})
        if not intent_payload:
            intent_payload = self._plan_turn_intent(state, user_input, phase_name).model_dump(mode="json")

        profile_name = str(intent_payload.get("turn_type") or "conversation").strip().lower()
        if profile_name not in TURN_PROFILE_POLICIES:
            profile_name = "conversation"
        reason = str(intent_payload.get("reason") or "structured turn intent selected this profile")

        policy = self._turn_profile_policy(profile_name)
        from spell_rules import declared_spells
        declared = declared_spells({"user_input": user_input, "turn_intent": intent_payload}, self.library)
        budget = int(policy.get("tool_round_limit") or self.max_tool_rounds)
        if profile_name in {"action_resolution", "combat_resolution"}:
            budget = min(24, max(budget, 4 + len(declared) * 4))
        return {
            "turn_profile": profile_name,
            "turn_profile_reason": reason,
            "turn_guidance": str(policy.get("guidance") or default_guidance),
            "tool_round_limit": budget,
            "allowed_tools": self._profile_allowed_tools(base_tools, profile_name),
        }

    def _input_gate(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = str(graph_state.get("user_input", ""))
        state_delta = dict(graph_state.get("state_delta", {}))
        phase, _, _, patch, _ = self._normalize_phase_state(state)
        if patch:
            state_delta = merge_patch(state_delta, patch)

        request = self._build_required_input_request(state, user_input, phase)
        if not request:
            return {
                "game_state": state.model_dump(mode="json"),
                "state_delta": state_delta,
                "turn_status": "running",
                "pending_input": {},
                "node_traces": self._append_node_trace(
                    graph_state,
                    "input_gate",
                    "Input accepted without clarification.",
                    {"phase": phase},
                ),
            }

        resumed_input = self._coerce_resume_input(interrupt(request))
        if not resumed_input:
            resumed_input = user_input
        return {
            "game_state": state.model_dump(mode="json"),
            "user_input": resumed_input,
            "state_delta": state_delta,
            "input_warnings": self._detect_input_warnings(resumed_input),
            "turn_status": "running",
            "pending_input": {},
            "node_traces": self._append_node_trace(
                graph_state,
                "input_gate",
                "Input resumed after clarification.",
                {"phase": phase},
            ),
        }

    def _plan_turn(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = str(graph_state.get("user_input", ""))
        state_delta = dict(graph_state.get("state_delta", {}))
        phase, scene, notes, patch, _ = self._normalize_phase_state(state)
        if patch:
            state_delta = merge_patch(state_delta, patch)
        turn_intent = self._plan_turn_intent(
            state,
            user_input,
            phase,
            scene,
            allow_agent_fallback=True,
        )
        return {
            "game_state": state.model_dump(mode="json"),
            "phase": phase,
            "scene": scene,
            "turn_intent": turn_intent.model_dump(mode="json"),
            "state_delta": state_delta,
            "validation_notes": notes,
            "node_traces": self._append_node_trace(
                graph_state,
                "plan_turn",
                "Structured turn intent planned.",
                {
                    "turn_type": turn_intent.turn_type,
                    "risk_level": turn_intent.risk_level,
                    "needs_rules": turn_intent.needs_rules,
                    "rag_intent": turn_intent.rag_intent,
                    "intent_source": turn_intent.intent_source,
                    "intent_tags": list(turn_intent.intent_tags),
                },
            ),
        }

    def _route_phase(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        user_input = str(graph_state.get("user_input", ""))
        state_delta = dict(graph_state.get("state_delta", {}))
        phase, scene, notes, patch, policy = self._normalize_phase_state(state)
        turn_intent = dict(graph_state.get("turn_intent") or {})
        if not turn_intent:
            turn_intent = self._plan_turn_intent(state, user_input, phase, scene).model_dump(mode="json")
        if patch:
            state_delta = merge_patch(state_delta, patch)
            turn_intent = self._refresh_turn_intent_for_state(
                state,
                user_input,
                phase,
                scene,
                existing_intent=turn_intent,
            ).model_dump(mode="json")
        turn_profile = self._classify_turn_profile(state, user_input, phase, turn_intent)
        turn_advice = self._build_turn_advice(
            state,
            user_input,
            phase,
            turn_profile["turn_profile"],
            list(turn_profile["allowed_tools"]),
            turn_intent=turn_intent,
        )
        return {
            "game_state": state.model_dump(mode="json"),
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
            "turn_status": str(graph_state.get("turn_status") or "running"),
            "pending_input": dict(graph_state.get("pending_input", {})),
            "state_delta": state_delta,
            "validation_notes": notes,
            "node_traces": self._append_node_trace(
                graph_state,
                "route_phase",
                "Phase policy, profile, and allowed tools selected.",
                {
                    "phase": phase,
                    "scene": scene,
                    "turn_profile": turn_profile["turn_profile"],
                    "turn_intent": {
                        "turn_type": str(turn_intent.get("turn_type") or ""),
                        "reason": str(turn_intent.get("reason") or ""),
                        "needs_rules": bool(turn_intent.get("needs_rules")),
                        "rag_intent": str(turn_intent.get("rag_intent") or "none"),
                        "suggested_tools": list(turn_intent.get("suggested_tools") or []),
                    },
                    "allowed_tool_count": len(turn_advice["allowed_tools"]),
                },
            ),
        }
