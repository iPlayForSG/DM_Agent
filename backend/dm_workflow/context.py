"""Rule retrieval and bounded DM prompt assembly."""

import os
from typing import Any, Dict, List, Optional

from campaign_memory import compile_campaign_memory
from game_logic import GameLogic
from combat_flow import narrative_scope
from models import GameState
from prompts import build_dm_instruction
from dm_workflow.state import DMGraphState
from dm_workflow.policies import RULE_TRIGGER_TERMS, SCENE_LABELS, PROMPT_CONTEXT_MAX_CHARS


class TurnContext:
    """Rule retrieval and bounded DM prompt assembly."""

    @staticmethod
    def _scene_label(scene: str) -> str:
        return SCENE_LABELS.get((scene or "").strip().lower(), scene or "当前场景")

    def _matched_spell_names(self, state: GameState, user_input: str) -> List[str]:
        active = state.get_active_char()
        if not active:
            return []

        lowered = (user_input or "").casefold()
        matched: List[str] = []
        for spell_name in [*active.spells.cantrips, *active.spells.prepared]:
            normalized = str(spell_name or "").strip()
            if not normalized:
                continue
            details = self.library.get_spell_details(normalized)
            canonical = str(details.get("name") or normalized).strip()
            aliases = self._unique_texts(
                [
                    normalized,
                    str(details.get("name") or "").strip(),
                    str(details.get("nameEN") or "").strip(),
                ],
                limit=3,
            )
            for alias in aliases:
                if alias and alias.casefold() in lowered:
                    matched.append(canonical)
                    break
        return self._unique_texts(matched, limit=2)

    def _should_auto_retrieve_rules(self, state: GameState, user_input: str) -> tuple[bool, str]:
        intent_payload = self._classify_rule_intent(state, user_input)
        return bool(intent_payload.get("should_retrieve")), str(
            intent_payload.get("reason", "no automatic rules trigger matched")
        )

    def _build_rag_queries(self, state: GameState, user_input: str) -> List[str]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return []

        active = state.get_active_char()
        matched_spells = self._matched_spell_names(state, normalized_input)
        lowered = normalized_input.casefold()
        matched_terms = [
            term
            for term in RULE_TRIGGER_TERMS
            if term and term.casefold() in lowered and len(term.strip()) > 1
        ]
        matched_terms = self._unique_texts(matched_terms, limit=6)

        contextual_terms: List[str] = [self._scene_label(state.scene), self._scene_label(state.campaign.phase)]
        if active:
            contextual_terms.extend([active.class_name, active.species, active.background_name])
        contextual_terms.extend(matched_terms[:4])
        contextual_query = "D&D 2024 " + " ".join(term for term in contextual_terms if term)

        queries = [normalized_input, contextual_query]
        for spell_name in matched_spells:
            queries.append(f"D&D 2024 法术 规则 {spell_name}")
        if matched_terms:
            queries.append(f"D&D 2024 规则 {' '.join(matched_terms[:4])}")

        return self._unique_texts(queries, limit=4)

    @staticmethod
    def _query_phrase(*parts: str) -> str:
        return " ".join(part.strip() for part in parts if str(part or "").strip()).strip()

    @classmethod
    def _intent_term_matches(cls, text: str, terms: List[str], limit: int = 6) -> List[str]:
        lowered = (text or "").casefold()
        matches = [
            str(term).strip()
            for term in terms
            if str(term or "").strip() and str(term).casefold() in lowered
        ]
        return cls._unique_texts(matches, limit=limit)

    @staticmethod
    def _rule_intent_terms() -> Dict[str, List[str]]:
        return {
            "general_rules": [
                "rule",
                "rules",
                "ruling",
                "\u89c4\u5219",
                "\u89e3\u91ca",
                "\u5224\u5b9a",
            ],
            "combat_resolution": [
                "attack",
                "damage",
                "initiative",
                "turn",
                "reaction",
                "bonus action",
                "opportunity attack",
                "grapple",
                "shove",
                "advantage",
                "disadvantage",
                "save",
                "check",
                "\u653b\u51fb",
                "\u4f24\u5bb3",
                "\u5148\u653b",
                "\u56de\u5408",
                "\u53cd\u5e94",
                "\u9644\u8d60\u52a8\u4f5c",
                "\u501f\u673a\u653b\u51fb",
                "\u64d2\u62b1",
                "\u63a8\u649e",
                "\u4f18\u52bf",
                "\u52a3\u52bf",
                "\u8c41\u514d",
                "\u68c0\u5b9a",
            ],
            "spell_resolution": [
                "spell",
                "slot",
                "concentration",
                "ritual",
                "counterspell",
                "\u6cd5\u672f",
                "\u6cd5\u672f\u4f4d",
                "\u4e13\u6ce8",
                "\u65bd\u6cd5",
                "\u4eea\u5f0f",
            ],
            "condition_resolution": [
                "condition",
                "prone",
                "poisoned",
                "grappled",
                "restrained",
                "invisible",
                "\u72b6\u6001",
                "\u5012\u5730",
                "\u4e2d\u6bd2",
                "\u88ab\u64d2\u62b1",
                "\u675f\u7f1a",
                "\u9690\u5f62",
            ],
            "skill_resolution": [
                "skill",
                "ability check",
                "perception",
                "investigation",
                "stealth",
                "persuasion",
                "proficiency",
                "\u6280\u80fd",
                "\u5c5e\u6027\u68c0\u5b9a",
                "\u611f\u77e5",
                "\u8c03\u67e5",
                "\u6f5c\u884c",
                "\u8bf4\u670d",
                "\u719f\u7ec3",
            ],
            "rest_recovery": [
                "short rest",
                "long rest",
                "recover",
                "recovery",
                "\u77ed\u4f11",
                "\u957f\u4f11",
                "\u6062\u590d",
                "\u4f11\u606f",
            ],
        }

    @staticmethod
    def _rule_query_hints() -> Dict[str, str]:
        return {
            "rules_question": "\u89c4\u5219 \u89e3\u91ca",
            "general_rules": "\u89c4\u5219 \u8bf4\u660e",
            "combat_resolution": "\u6218\u6597 \u89c4\u5219",
            "spell_resolution": "\u6cd5\u672f \u65bd\u6cd5 \u6cd5\u672f\u4f4d",
            "condition_resolution": "\u72b6\u6001 \u6548\u679c \u89c4\u5219",
            "skill_resolution": "\u68c0\u5b9a \u6280\u80fd \u89c4\u5219",
            "rest_recovery": "\u4f11\u606f \u6062\u590d \u89c4\u5219",
        }

    @staticmethod
    def _looks_like_rule_question(text: str) -> bool:
        normalized = " ".join((text or "").split()).strip()
        if not normalized:
            return False
        lowered = normalized.casefold()
        markers = [
            "\u89c4\u5219",
            "\u5224\u5b9a",
            "\u89e3\u91ca",
            "rule",
            "rules",
            "ruling",
        ]
        if any(marker in lowered for marker in markers):
            return True

        has_question_shape = "?" in normalized or "\uff1f" in normalized
        if not has_question_shape:
            return False

        rule_markers = [
            *RULE_TRIGGER_TERMS,
            "rule",
            "rules",
            "ruling",
            "\u89c4\u5219",
            "\u89e3\u91ca",
            "\u5224\u5b9a",
            "\u6cd5\u672f",
            "\u4e13\u6ce8",
            "\u8c41\u514d",
            "\u68c0\u5b9a",
        ]
        return any(str(marker or "").casefold() in lowered for marker in rule_markers if str(marker or "").strip())

    def _classify_rule_intent(self, state: GameState, user_input: str) -> Dict[str, Any]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return {
                "intent": "none",
                "should_retrieve": False,
                "reason": "empty user input",
                "focus_terms": [],
                "matched_spells": [],
            }

        question_shape = self._looks_like_rule_question(normalized_input)
        matched_spells = self._matched_spell_names(state, normalized_input)
        category_matches = {
            name: self._intent_term_matches(normalized_input, terms)
            for name, terms in self._rule_intent_terms().items()
        }

        intent = "none"
        reason = "no automatic rules trigger matched"
        if matched_spells:
            intent = "spell_resolution"
            reason = "player referenced a prepared or known spell"
        elif category_matches["spell_resolution"] and (question_shape or state.scene == "combat"):
            intent = "spell_resolution"
            reason = "spell-related turn needs rules support"
        elif category_matches["condition_resolution"] and (question_shape or state.scene == "combat"):
            intent = "condition_resolution"
            reason = "condition-heavy turn needs rules support"
        elif category_matches["combat_resolution"] and (question_shape or state.scene == "combat"):
            intent = "combat_resolution"
            reason = "combat turn mentioned rules-sensitive actions"
        elif category_matches["rest_recovery"]:
            intent = "rest_recovery"
            reason = "player asked about recovery timing or rest rules"
        elif category_matches["skill_resolution"] and (question_shape or state.scene in {"exploration", "combat"}):
            intent = "skill_resolution"
            reason = "player asked for a skill or ability ruling"
        elif question_shape:
            intent = "rules_question"
            reason = "player asked an explicit rules question"
        elif category_matches["general_rules"]:
            intent = "general_rules"
            reason = "player referenced general rules language"

        focus_terms = self._unique_texts(
            [
                *matched_spells,
                *category_matches["combat_resolution"],
                *category_matches["spell_resolution"],
                *category_matches["condition_resolution"],
                *category_matches["skill_resolution"],
                *category_matches["rest_recovery"],
                *category_matches["general_rules"],
            ],
            limit=6,
        )
        return {
            "intent": intent,
            "should_retrieve": intent != "none",
            "reason": reason,
            "focus_terms": focus_terms,
            "matched_spells": matched_spells,
        }

    @staticmethod
    def _rule_intent_payload_from_turn_intent(turn_intent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intent": str(turn_intent.get("rag_intent") or "none"),
            "should_retrieve": bool(turn_intent.get("needs_rules")),
            "reason": str(turn_intent.get("rag_reason") or "no automatic rules trigger matched"),
            "focus_terms": list(turn_intent.get("focus_terms") or turn_intent.get("action_terms") or []),
            "matched_spells": list(turn_intent.get("matched_spells") or []),
        }

    def _build_intent_rag_queries(
        self,
        state: GameState,
        user_input: str,
        intent_payload: Dict[str, Any],
    ) -> List[str]:
        normalized_input = " ".join((user_input or "").split()).strip()
        if not normalized_input:
            return []

        active = state.get_active_char()
        intent = str(intent_payload.get("intent") or "rules_question")
        matched_spells = list(intent_payload.get("matched_spells", []))
        matched_terms = list(intent_payload.get("focus_terms", []))

        contextual_terms: List[str] = [self._scene_label(state.scene), self._scene_label(state.campaign.phase)]
        if active:
            contextual_terms.extend([active.class_name, active.species, active.background_name])
        contextual_terms.extend(matched_terms[:4])
        contextual_query = self._query_phrase("D&D 2024", *[term for term in contextual_terms if term])
        intent_hint = self._rule_query_hints().get(intent, "\u89c4\u5219")

        queries = [normalized_input]
        if contextual_query:
            queries.append(self._query_phrase(contextual_query, intent_hint))
        for spell_name in matched_spells:
            queries.append(self._query_phrase("D&D 2024", "\u6cd5\u672f", "\u89c4\u5219", spell_name))
        if matched_terms:
            queries.append(self._query_phrase("D&D 2024", intent_hint, *matched_terms[:4]))
        if active and intent in {"spell_resolution", "rest_recovery"}:
            queries.append(self._query_phrase("D&D 2024", active.class_name, intent_hint, *matched_terms[:3]))

        return self._unique_texts(queries, limit=4)

    @staticmethod
    def _truncate_context_block(value: str, max_chars: int, *, keep: str = "middle") -> str:
        text = str(value or "")
        limit = max(0, int(max_chars or 0))
        if not limit or len(text) <= limit:
            return text
        marker = "\n…[context truncated]…\n"
        if limit <= len(marker):
            return text[-limit:] if keep == "tail" else text[:limit]
        available = limit - len(marker)
        if keep == "tail":
            return marker + text[-available:]
        if keep == "head":
            return text[:available] + marker
        head_chars = available // 2
        tail_chars = available - head_chars
        return text[:head_chars] + marker + text[-tail_chars:]

    def _prepare_context(self, graph_state: DMGraphState) -> DMGraphState:
        state = GameState.model_validate(graph_state["game_state"])
        logic = GameLogic(state)
        raw_state_summary = logic.get_state_summary()
        raw_recent_history = logic.get_recent_history()
        raw_rag_context = str(graph_state.get("rag_context", "") or "")
        # 单一 DM 会长期积累上下文；每类信息独立限额，避免旧历史挤掉当前状态和工具契约。
        state_summary = self._truncate_context_block(
            raw_state_summary,
            PROMPT_CONTEXT_MAX_CHARS["state_summary"],
        )
        recent_history = self._truncate_context_block(
            raw_recent_history,
            PROMPT_CONTEXT_MAX_CHARS["recent_history"],
            keep="tail",
        )
        campaign_memory = compile_campaign_memory(
            state,
            max_chars=PROMPT_CONTEXT_MAX_CHARS["campaign_memory"],
        )
        rag_context = self._truncate_context_block(
            raw_rag_context,
            PROMPT_CONTEXT_MAX_CHARS["rag_context"],
            keep="head",
        )
        instruction = build_dm_instruction(
            state_summary=state_summary,
            recent_history=recent_history,
            campaign_memory=campaign_memory,
            rag_enabled=bool(self.rag_engine and self.rag_engine.is_ready()),
            retrieved_context=rag_context,
            phase_name=graph_state.get("phase", ""),
            phase_objective=graph_state.get("phase_objective", ""),
            phase_constraints=list(graph_state.get("phase_constraints", [])),
            phase_blockers=list(graph_state.get("phase_blockers", [])),
            turn_profile=graph_state.get("turn_profile", ""),
            turn_profile_reason=graph_state.get("turn_profile_reason", ""),
            turn_guidance=graph_state.get("turn_guidance", ""),
            tool_round_limit=int(graph_state.get("tool_round_limit", 0) or 0),
            turn_expectation=graph_state.get("turn_expectation", ""),
            suggested_tools=list(graph_state.get("suggested_tools", [])),
            turn_checklist=list(graph_state.get("turn_checklist", [])),
            turn_intent=dict(graph_state.get("turn_intent", {})),
            reply_min_chars=int(state.campaign.reply_min_chars or 0),
            reply_max_chars=int(state.campaign.reply_max_chars or 0),
            pacing_scope=narrative_scope(state, graph_state.get("combat_flow", {}), graph_state.get("initial_game_state")),
        )
        return {
            "state_summary": state_summary,
            "recent_history": recent_history,
            "campaign_memory": campaign_memory,
            "instruction": instruction,
            "messages": [
                self._system_prompt_message(instruction),
                self._human_prompt_message(graph_state.get("user_input", "")),
            ],
            "node_traces": self._append_node_trace(
                graph_state,
                "prepare_context",
                "Prompt context prepared.",
                {
                    "state_summary_chars": len(state_summary),
                    "recent_history_chars": len(recent_history),
                    "rag_context_chars": len(rag_context),
                    "campaign_memory_chars": len(campaign_memory),
                    "instruction_chars": len(instruction),
                    "truncated_contexts": [
                        name
                        for name, raw_value, bounded_value in (
                            ("state_summary", raw_state_summary, state_summary),
                            ("recent_history", raw_recent_history, recent_history),
                            ("rag_context", raw_rag_context, rag_context),
                        )
                        if len(raw_value) > len(bounded_value)
                    ],
                    "suggested_tool_count": len(graph_state.get("suggested_tools", [])),
                    "reply_min_chars": int(state.campaign.reply_min_chars or 0),
                    "reply_max_chars": int(state.campaign.reply_max_chars or 0),
                },
            ),
        }

    @staticmethod
    def _format_rag_context(
        snippets: List[Dict[str, str]],
        queries: Optional[List[str]] = None,
        intent: str = "",
    ) -> str:
        formatted: List[str] = []
        if intent:
            formatted.append(f"Retrieval intent: {intent}")
        if queries:
            formatted.append(f"Retrieval focus: {' | '.join(queries[:3])}")
        for snippet in snippets:
            heading = f" | {snippet.get('heading', '')}" if snippet.get("heading") else ""
            lines = ""
            if snippet.get("start_line") and snippet.get("end_line"):
                lines = f":L{snippet.get('start_line')}-L{snippet.get('end_line')}"
            formatted.append(
                f"--- Rule Snippet ({snippet.get('source', 'unknown')}#{snippet.get('chunk_index', '')}{lines}{heading}) ---\n"
                f"{snippet.get('content', '')}"
            )
        return "\n\n".join(formatted).strip()

    def _retrieve_rules(self, graph_state: DMGraphState) -> DMGraphState:
        n_results = int(os.getenv("RAG_AUTO_CONTEXT_RESULTS", "3") or 0)
        if n_results <= 0 or not self.rag_engine.is_ready():
            reason = "automatic retrieval disabled" if n_results <= 0 else "RAG engine is not ready"
            return {
                "rag_snippets": [],
                "rag_context": "",
                "rag_queries": [],
                "rag_intent": "none",
                "rag_reason": reason,
                "rag_metadata": {
                    "enabled": n_results > 0,
                    "ready": self.rag_engine.is_ready(),
                    "auto_context_results": n_results,
                    "intent": "none",
                    "reason": reason,
                    "queries": [],
                    "snippet_count": 0,
                    "sources": [],
                },
                "node_traces": self._append_node_trace(
                    graph_state,
                    "retrieve_rules",
                    "Automatic rules retrieval skipped.",
                    {"reason": reason, "ready": self.rag_engine.is_ready()},
                ),
            }

        state = GameState.model_validate(graph_state["game_state"])
        turn_intent = dict(graph_state.get("turn_intent") or {})
        intent_payload = (
            self._rule_intent_payload_from_turn_intent(turn_intent)
            if turn_intent
            else self._classify_rule_intent(state, graph_state.get("user_input", ""))
        )
        if not intent_payload.get("should_retrieve"):
            intent = str(intent_payload.get("intent", "none"))
            reason = str(intent_payload.get("reason", "no automatic rules trigger matched"))
            return {
                "rag_snippets": [],
                "rag_context": "",
                "rag_queries": [],
                "rag_intent": intent,
                "rag_reason": reason,
                "rag_metadata": {
                    "enabled": True,
                    "ready": True,
                    "auto_context_results": n_results,
                    "intent": intent,
                    "reason": reason,
                    "queries": [],
                    "snippet_count": 0,
                    "sources": [],
                },
                "node_traces": self._append_node_trace(
                    graph_state,
                    "retrieve_rules",
                    "Turn intent did not require automatic rules retrieval.",
                    {"intent": intent, "reason": reason},
                ),
            }

        queries = self._build_intent_rag_queries(state, graph_state.get("user_input", ""), intent_payload)
        snippets = self.library.localize_rag_snippets(
            self.rag_engine.search_many(queries, n_results=n_results)
        )
        intent = str(intent_payload.get("intent", "none"))
        reason = str(intent_payload.get("reason", ""))
        sources = self._unique_texts(
            [str(snippet.get("source", "")) for snippet in snippets],
            limit=8,
        )
        return {
            "rag_snippets": snippets,
            "rag_context": self._format_rag_context(
                snippets,
                queries=queries,
                intent=intent,
            ),
            "rag_queries": queries,
            "rag_intent": intent,
            "rag_reason": reason,
            "rag_metadata": {
                "enabled": True,
                "ready": True,
                "auto_context_results": n_results,
                "intent": intent,
                "reason": reason,
                "queries": queries,
                "snippet_count": len(snippets),
                "sources": sources,
            },
            "node_traces": self._append_node_trace(
                graph_state,
                "retrieve_rules",
                "Automatic rules retrieval completed.",
                {"intent": intent, "query_count": len(queries), "snippet_count": len(snippets)},
            ),
        }
