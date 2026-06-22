import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("RAG_AUTO_CONTEXT_RESULTS", "0")
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from action_service import GameActionService
from campaign_memory import compile_campaign_memory
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import AdventureHook, ChapterRecord, Character, EvidenceRecord, GameState, InventoryItem, MonsterTemplate, ResourcePool, SearchRecord, SpellSlot
from agent import DMAgent, normalize_openai_base_url
from agent_tools import AgentToolExecution, AgentToolService
from langchain_core.messages import AIMessage
from rules_catalog import RuleCatalog
from storage import MonsterStorage


class DummyRAGEngine:
    def is_ready(self) -> bool:
        return False


class EndEncounterModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tool_schemas):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-end-encounter",
                        "name": "end_encounter",
                        "args": {},
                    }
                ]
            )
        return AIMessage(content="遭遇已经结束。")


class EndEncounterToolService:
    def end_encounter(self, state: GameState) -> AgentToolExecution:
        outcome = GameLogic(state).finalize_encounter()
        if not outcome:
            return AgentToolExecution(ok=False, error="No encounter to end")
        return AgentToolExecution(
            ok=True,
            payload={"ended": True, "summary": outcome["summary"]},
            state_patch={
                "scene": state.scene,
                "campaign": {"phase": state.campaign.phase},
                "encounter": outcome["encounter"].model_dump(mode="json"),
                "adventure_log": list(state.adventure_log),
            },
        )


class DMGraphWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=object(),
            enable_model=False,
        )

    @staticmethod
    def _build_state(with_selected_adventure: bool = False) -> GameState:
        state = GameState(game_id="qa-workflow", title="QA Workflow")
        character = Character(name="凯德", class_name="Fighter")
        state.characters[character.character_id] = character
        state.active_character_id = character.character_id

        hook = AdventureHook(
            title="黑冢余烬",
            summary="矿村下方的封闭墓道重新冒出了烟。",
        )
        state.campaign.available_adventures = [hook]

        if with_selected_adventure:
            state.campaign.selected_adventure_id = hook.adventure_id
            state.campaign.setup_complete = True
            state.scene = "exploration"
            state.campaign.phase = "exploration"
        else:
            state.scene = "exploration"
            state.campaign.phase = "exploration"

        return state

    def test_route_phase_normalizes_to_adventure_selection_before_setup(self) -> None:
        state = self._build_state(with_selected_adventure=False)

        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )

        normalized = GameState.model_validate(routed["game_state"])
        self.assertEqual(routed["phase"], "adventure_selection")
        self.assertEqual(normalized.scene, "setup")
        self.assertEqual(normalized.campaign.phase, "adventure_selection")
        self.assertNotIn("start_encounter", routed["allowed_tools"])
        self.assertIn("No selected adventure is locked in yet.", routed["phase_blockers"])
        self.assertEqual(routed["state_delta"]["scene"], "setup")
        self.assertEqual(routed["state_delta"]["campaign"]["phase"], "adventure_selection")

    def test_prepare_context_includes_phase_guidance(self) -> None:
        state = self._build_state(with_selected_adventure=False)
        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )

        prepared = self.runner._prepare_context(
            {
                **routed,
                "game_state": routed["game_state"],
                "user_input": "给我介绍这几个冒险",
                "rag_context": "",
            }
        )

        instruction = prepared["instruction"]
        self.assertIn("Current workflow phase:", instruction)
        self.assertIn("adventure_selection", instruction)
        self.assertIn("Structured turn intent:", instruction)
        self.assertIn("setup_guidance", instruction)
        self.assertIn("Do not begin active exploration or combat until an adventure hook is selected.", instruction)

    def test_campaign_memory_compiler_summarizes_durable_state(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        state.campaign.current_chapter_number = 2
        state.campaign.current_chapter_title = "祭坛下的回声"
        state.campaign.current_chapter_summary = "队伍进入礼拜堂地下空间。"
        state.campaign.completed_chapters.append(
            ChapterRecord(
                chapter_number=1,
                title="钟声再起",
                summary="队伍发现仪式灰烬、单向脚印和碎铜片。",
            )
        )
        state.evidence_records.append(
            EvidenceRecord(
                title="碎铜片",
                summary="带弧线纹路的铜器碎片，疑似来自裂钟。",
                location="礼拜堂门口",
                tags=["bell", "ritual"],
            )
        )
        state.search_records.append(
            SearchRecord(
                searcher_character_id=state.active_character_id,
                target_ref="祭坛暗格",
                summary="发现文书、断裂铜钟舌和失踪者名单。",
                recovered_items=["断裂铜钟舌"],
                recovered_evidence_ids=["碎铜片"],
            )
        )
        state.get_active_char().major_experiences.append("第一章：制服钟楼暴徒。")
        state.adventure_log.append("村民确认无月之夜后会有人失踪。")

        memory = compile_campaign_memory(state)

        self.assertIn("Campaign arc:", memory)
        self.assertIn("Completed 1: 钟声再起", memory)
        self.assertIn("Durable evidence:", memory)
        self.assertIn("碎铜片", memory)
        self.assertIn("Search outcomes:", memory)
        self.assertIn("祭坛暗格", memory)
        self.assertIn("Character milestones:", memory)
        self.assertIn("制服钟楼暴徒", memory)

    def test_prepare_context_includes_campaign_memory(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        state.campaign.completed_chapters.append(
            ChapterRecord(chapter_number=1, title="钟声再起", summary="队伍发现碎铜片。")
        )
        state.evidence_records.append(EvidenceRecord(title="碎铜片", summary="裂钟残片。"))

        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )
        prepared = self.runner._prepare_context(
            {
                **routed,
                "game_state": routed["game_state"],
                "user_input": "继续推进",
                "rag_context": "",
            }
        )

        self.assertIn("Campaign memory:", prepared["instruction"])
        self.assertIn("Completed 1: 钟声再起", prepared["instruction"])
        self.assertIn("碎铜片", prepared["instruction"])
        self.assertGreater(prepared["node_traces"][-1]["metadata"]["campaign_memory_chars"], 0)

    def test_create_new_game_without_characters_does_not_create_fallback_character(self) -> None:
        agent = DMAgent()
        try:
            state = agent.create_new_game([], game_id="empty-party", title="Empty Party")
        finally:
            agent.close()

        self.assertEqual(state.characters, {})
        self.assertIsNone(state.active_character_id)

    def test_validate_state_requires_repair_for_combat_phase_drift(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["地精"], enemy_hp=7, enemy_ac=12)

        state.scene = "exploration"
        state.campaign.phase = "exploration"

        validated = self.runner._validate_state(
            {
                "game_state": state.model_dump(mode="json"),
                "messages": [],
                "timeline_append": [],
                "state_delta": {},
            }
        )

        checked = GameState.model_validate(validated["game_state"])
        self.assertEqual(checked.scene, "exploration")
        self.assertEqual(checked.campaign.phase, "exploration")
        self.assertEqual(validated["validation_status"], "repair_required")
        self.assertEqual(validated["allowed_tools"], ["set_scene"])
        self.assertEqual(validated["suggested_tools"], ["set_scene"])
        self.assertIn("call set_scene", validated["validation_notes"][0])
        issues = validated["validation_issues"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["validator"], "combat_phase")
        self.assertEqual(issues[0]["action"], "repair_required")
        self.assertEqual(issues[0]["severity"], "error")
        self.assertEqual(validated["state_delta"], {})
        self.assertEqual(validated["node_traces"][-1]["metadata"]["validation_issue_count"], len(issues))
        self.assertEqual(validated["node_traces"][-1]["metadata"]["validation_status"], "repair_required")

    def test_validate_state_fails_on_party_combatant_mirror_drift(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        party_combatant.hp_current = 1
        character_hp = state.characters[state.active_character_id].hp_current

        validated = self.runner._validate_state(
            {
                "game_state": state.model_dump(mode="json"),
                "messages": [],
                "timeline_append": [],
                "state_delta": {},
            }
        )
        checked = GameState.model_validate(validated["game_state"])
        checked_party = checked.encounter.combatants[party_combatant.combatant_id]

        self.assertEqual(validated["validation_status"], "failed")
        self.assertEqual(validated["turn_status"], "failed")
        self.assertEqual(checked_party.hp_current, 1)
        self.assertEqual(checked.characters[state.active_character_id].hp_current, character_hp)
        self.assertIn("Party combatant mirror differs", validated["validation_notes"][0])
        self.assertEqual(validated["validation_issues"][0]["action"], "failed_turn")

    def test_level_up_phase_disables_encounter_tools(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        state.scene = "level_up"
        state.campaign.phase = "level_up"

        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "state_delta": {},
            }
        )

        self.assertEqual(routed["phase"], "level_up")
        self.assertEqual(routed["scene"], "level_up")
        self.assertIn("record_major_experience", routed["allowed_tools"])
        self.assertNotIn("start_encounter", routed["allowed_tools"])
        self.assertNotIn("attack_target", routed["allowed_tools"])

    def test_social_question_stays_conversational(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "user_input": "What does the innkeeper know about the mine?",
                "state_delta": {},
            }
        )

        self.assertEqual(routed["turn_profile"], "conversation")
        self.assertEqual(routed["turn_intent"]["turn_type"], "conversation")
        self.assertFalse(routed["turn_intent"]["needs_rules"])
        self.assertEqual(routed["tool_round_limit"], 1)
        self.assertIn("Direct in-world reply first", routed["turn_expectation"])
        self.assertEqual(routed["suggested_tools"], [])
        self.assertNotIn("roll_skill_check", routed["allowed_tools"])
        self.assertNotIn("cast_spell", routed["allowed_tools"])
        self.assertEqual(
            self.runner._classify_rule_intent(state, "What does the innkeeper know about the mine?")["intent"],
            "none",
        )

    def test_rules_question_uses_lookup_only_profile(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "user_input": "How does concentration work?",
                "state_delta": {},
            }
        )

        self.assertEqual(routed["turn_profile"], "rules_reference")
        self.assertEqual(routed["turn_intent"]["turn_type"], "rules_reference")
        self.assertTrue(routed["turn_intent"]["needs_rules"])
        self.assertEqual(routed["turn_intent"]["rag_intent"], "spell_resolution")
        self.assertEqual(routed["allowed_tools"], ["lookup_rules"])
        self.assertEqual(routed["tool_round_limit"], 1)
        self.assertEqual(routed["suggested_tools"], ["lookup_rules"])
        self.assertIn("Answer the rules question in one pass", routed["turn_expectation"])

    def test_plan_turn_produces_action_intent_before_routing(self) -> None:
        state = self._build_state(with_selected_adventure=True)

        planned = self.runner._plan_turn(
            {
                "game_state": state.model_dump(mode="json"),
                "user_input": "I search the altar for clues.",
                "state_delta": {},
            }
        )

        self.assertEqual(planned["turn_intent"]["turn_type"], "action_resolution")
        self.assertIn("search", planned["turn_intent"]["action_terms"])
        self.assertEqual(planned["turn_intent"]["phase"], "exploration")
        self.assertEqual(planned["turn_intent"]["risk_level"], "low")

    def test_combat_action_uses_combat_resolution_profile(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)

        routed = self.runner._route_phase(
            {
                "game_state": state.model_dump(mode="json"),
                "user_input": "I attack the goblin with my sword.",
                "state_delta": {},
            }
        )

        self.assertEqual(routed["phase"], "combat")
        self.assertEqual(routed["turn_profile"], "combat_resolution")
        self.assertEqual(routed["turn_intent"]["turn_type"], "combat_resolution")
        self.assertEqual(routed["turn_intent"]["risk_level"], "medium")
        self.assertEqual(routed["suggested_tools"], ["attack_target"])
        self.assertEqual(routed["allowed_tools"][0], "attack_target")
        self.assertIn("attack_target", routed["allowed_tools"])
        self.assertEqual(routed["tool_round_limit"], 3)

    def test_tool_guardrail_rejects_missing_required_argument(self) -> None:
        state = self._build_state(with_selected_adventure=True)

        execution = self.runner._execute_single_tool(
            state=state,
            tool_name="adjust_hp",
            args={"target_ref": state.active_character_id},
            allowed_tools=["adjust_hp"],
        )

        self.assertFalse(execution.ok)
        response = execution.response()
        self.assertIn("Missing required tool argument `amount`", response["error"])
        self.assertEqual(response["guardrail"]["risk_level"], "medium")

    def test_tool_guardrail_rejects_invalid_argument_type(self) -> None:
        state = self._build_state(with_selected_adventure=True)

        execution = self.runner._execute_single_tool(
            state=state,
            tool_name="adjust_hp",
            args={"target_ref": state.active_character_id, "amount": "-5"},
            allowed_tools=["adjust_hp"],
        )

        self.assertFalse(execution.ok)
        self.assertIn("expected integer", execution.response()["error"])

    def test_tool_guardrail_rejects_combat_tool_without_active_encounter(self) -> None:
        state = self._build_state(with_selected_adventure=True)

        execution = self.runner._execute_single_tool(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": state.active_character_id,
                "target_ref": "Goblin",
                "attack_bonus": 5,
                "damage_expression": "1d8+3",
            },
            allowed_tools=["attack_target"],
        )

        self.assertFalse(execution.ok)
        self.assertIn("requires an active encounter", execution.response()["error"])

    def test_tool_guardrail_rejects_duplicate_start_encounter(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        GameLogic(state).start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)

        execution = self.runner._execute_single_tool(
            state=state,
            tool_name="start_encounter",
            args={"enemy_names": ["Orc"]},
            allowed_tools=["start_encounter"],
        )

        self.assertFalse(execution.ok)
        self.assertIn("cannot run while an encounter is already active", execution.response()["error"])

    def test_tool_guardrail_rejects_non_current_actor_action(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)

        execution = self.runner._execute_single_tool(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": enemy_combatant.combatant_id,
                "target_ref": party_combatant.combatant_id,
                "attack_bonus": 4,
                "damage_expression": "1d6+2",
            },
            allowed_tools=["attack_target"],
        )

        self.assertFalse(execution.ok)
        response = execution.response()
        self.assertIn("current combatant", response["error"])
        self.assertEqual(response["guardrail"]["current_actor_arg"], "attacker_ref")

    def test_tool_guardrail_accepts_current_actor_aliases(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        character = state.characters[state.active_character_id]
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)

        attack_guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": party_combatant.combatant_id,
                "target_ref": enemy_combatant.combatant_id,
                "attack_bonus": 5,
                "damage_expression": "1d8+3",
            },
            allowed_tools=["attack_target"],
        )
        skill_guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="roll_skill_check",
            args={"actor_ref": character.name, "skill_name": "Perception"},
            allowed_tools=["roll_skill_check"],
        )

        self.assertTrue(attack_guardrail.ok)
        self.assertTrue(skill_guardrail.ok)
        self.assertEqual(attack_guardrail.metadata["current_actor_arg"], "attacker_ref")
        self.assertEqual(skill_guardrail.metadata["current_actor_arg"], "actor_ref")

    def test_tool_guardrail_rejects_unavailable_inventory_use(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        character = state.characters[state.active_character_id]
        character.inventory.append(InventoryItem(name="Healing Potion", quantity=1))

        guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="use_item",
            args={
                "user_ref": character.name,
                "item_name": "Healing Potion",
                "quantity": 2,
            },
            allowed_tools=["use_item"],
        )
        negative_guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="use_item",
            args={
                "user_ref": character.character_id,
                "item_name": "Healing Potion",
                "quantity": 0,
            },
            allowed_tools=["use_item"],
        )

        self.assertFalse(guardrail.ok)
        self.assertIn("Not enough item quantity", guardrail.error)
        self.assertEqual(guardrail.metadata["inventory_quantity_arg"], "quantity")
        self.assertFalse(negative_guardrail.ok)
        self.assertIn("greater than zero", negative_guardrail.error)

    def test_use_item_guardrail_normalizes_and_agent_tool_consumes_inventory(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        character = state.characters[state.active_character_id]
        character.inventory.append(InventoryItem(name="Healing Potion", quantity=2))
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        execution = runner._execute_single_tool(
            state=state,
            tool_name="use_item",
            args={
                "user_ref": character.name.lower(),
                "item_name": "healing potion",
                "quantity": 2,
            },
            allowed_tools=["use_item"],
        )

        self.assertTrue(execution.ok, execution.response())
        self.assertEqual(character.inventory[0].quantity, 0)
        self.assertEqual(execution.payload["quantity_remaining"], 0)
        self.assertEqual(
            execution.state_patch["characters"][character.character_id]["inventory"][0]["quantity"],
            0,
        )

    def test_local_use_item_rejects_non_positive_quantity(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        character = state.characters[state.active_character_id]
        character.inventory.append(InventoryItem(name="Torch", quantity=1))

        with self.assertRaisesRegex(ValueError, "greater than zero"):
            GameActionService().use_item(
                state=state,
                user_ref=character.character_id,
                item_name="Torch",
                quantity=-1,
            )

        self.assertEqual(character.inventory[0].quantity, 1)

    def test_agent_action_consumes_turn_action_and_blocks_second_action(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        character = state.characters[state.active_character_id]
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        execution = runner._execute_single_tool(
            state=state,
            tool_name="roll_skill_check",
            args={"actor_ref": character.character_id, "skill_name": "Perception", "dc": 10},
            allowed_tools=["roll_skill_check"],
        )
        second_action = runner.tool_registry.validate_call(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": character.character_id,
                "target_ref": enemy_combatant.combatant_id,
                "attack_bonus": 5,
                "damage_expression": "1d8+3",
            },
            allowed_tools=["attack_target"],
        )

        self.assertTrue(execution.ok, execution.response())
        self.assertTrue(state.encounter.turn_action_used)
        self.assertEqual(state.encounter.turn_action_tool, "roll_skill_check")
        self.assertTrue(execution.state_patch["encounter"]["turn_action_used"])
        self.assertFalse(second_action.ok)
        self.assertIn("action already used", second_action.error)
        self.assertTrue(second_action.metadata["consumes_turn_action"])

    def test_advance_turn_resets_turn_action_ledger(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        logic.mark_current_action_used("attack_target")

        logic.advance_turn()
        enemy_action = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": enemy_combatant.combatant_id,
                "target_ref": party_combatant.combatant_id,
                "attack_bonus": 4,
                "damage_expression": "1d6+2",
            },
            allowed_tools=["attack_target"],
        )

        self.assertEqual(state.encounter.current_combatant_id, enemy_combatant.combatant_id)
        self.assertFalse(state.encounter.turn_action_used)
        self.assertTrue(enemy_action.ok)

    def test_spell_guardrail_rejects_unavailable_spell_slot(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        character = state.characters[state.active_character_id]
        character.spells.prepared = ["Healing Word"]
        character.spells.slots = {"1": SpellSlot(total=1, used=1)}

        guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="cast_spell",
            args={
                "caster_ref": character.name,
                "spell_name": "healing word",
                "slot_level": 1,
            },
            allowed_tools=["cast_spell"],
        )

        self.assertFalse(guardrail.ok)
        self.assertIn("No available spell slot", guardrail.error)
        self.assertEqual(guardrail.metadata["spell_name_arg"], "spell_name")

    def test_bonus_action_spell_uses_bonus_slot_without_blocking_action(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        character = state.characters[state.active_character_id]
        character.spells.prepared = ["Healing Word"]
        character.spells.slots = {"1": SpellSlot(total=2, used=0)}
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        execution = runner._execute_single_tool(
            state=state,
            tool_name="cast_spell",
            args={
                "caster_ref": character.character_id,
                "spell_name": "Healing Word",
                "slot_level": 1,
            },
            allowed_tools=["cast_spell"],
        )
        attack_guardrail = runner.tool_registry.validate_call(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": character.character_id,
                "target_ref": enemy_combatant.combatant_id,
                "attack_bonus": 5,
                "damage_expression": "1d8+3",
            },
            allowed_tools=["attack_target"],
        )
        second_bonus_guardrail = runner.tool_registry.validate_call(
            state=state,
            tool_name="cast_spell",
            args={
                "caster_ref": character.character_id,
                "spell_name": "Healing Word",
                "slot_level": 1,
            },
            allowed_tools=["cast_spell"],
        )

        self.assertTrue(execution.ok, execution.response())
        self.assertEqual(execution.payload["action_cost"], "bonus_action")
        self.assertFalse(state.encounter.turn_action_used)
        self.assertTrue(state.encounter.turn_bonus_action_used)
        self.assertEqual(character.spells.slots["1"].used, 1)
        self.assertTrue(attack_guardrail.ok)
        self.assertFalse(second_bonus_guardrail.ok)
        self.assertIn("bonus action already used", second_bonus_guardrail.error)

    def test_use_feature_bonus_action_consumes_bonus_slot_and_resource(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        character = state.characters[state.active_character_id]
        character.resources["Second Wind"] = ResourcePool(current_value=1, max_value=1)
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        execution = runner._execute_single_tool(
            state=state,
            tool_name="use_feature",
            args={
                "actor_ref": character.character_id,
                "feature_name": "Second Wind",
                "action_cost": "bonus_action",
                "resource_name": "second wind",
                "resource_cost": 1,
            },
            allowed_tools=["use_feature"],
        )
        attack_guardrail = runner.tool_registry.validate_call(
            state=state,
            tool_name="attack_target",
            args={
                "attacker_ref": character.character_id,
                "target_ref": enemy_combatant.combatant_id,
                "attack_bonus": 5,
                "damage_expression": "1d8+3",
            },
            allowed_tools=["attack_target"],
        )

        self.assertTrue(execution.ok, execution.response())
        self.assertEqual(execution.payload["action_cost"], "bonus_action")
        self.assertEqual(execution.payload["resource_before"], 1)
        self.assertEqual(execution.payload["resource_after"], 0)
        self.assertEqual(character.resources["Second Wind"].current_value, 0)
        self.assertFalse(state.encounter.turn_action_used)
        self.assertTrue(state.encounter.turn_bonus_action_used)
        self.assertEqual(state.encounter.turn_bonus_action_tool, "use_feature")
        self.assertTrue(attack_guardrail.ok)
        self.assertEqual(
            execution.state_patch["characters"][character.character_id]["resources"]["Second Wind"]["current_value"],
            0,
        )

    def test_use_feature_infers_known_feature_cost_and_resource(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        logic.mark_current_action_used("attack_target")
        character = state.characters[state.active_character_id]
        character.resources["Second Wind"] = ResourcePool(current_value=1, max_value=1)
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        execution = runner._execute_single_tool(
            state=state,
            tool_name="use_feature",
            args={
                "actor_ref": character.character_id,
                "feature_name": "Second Wind",
            },
            allowed_tools=["use_feature"],
        )

        self.assertTrue(execution.ok, execution.response())
        self.assertEqual(execution.payload["action_cost"], "bonus_action")
        self.assertEqual(execution.payload["resource_name"], "Second Wind")
        self.assertEqual(execution.payload["resource_after"], 0)
        self.assertTrue(state.encounter.turn_action_used)
        self.assertTrue(state.encounter.turn_bonus_action_used)

    def test_use_feature_reaction_guardrail_blocks_second_reaction(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        first_reaction = runner._execute_single_tool(
            state=state,
            tool_name="use_feature",
            args={
                "actor_ref": state.active_character_id,
                "feature_name": "Parry",
                "action_cost": "reaction",
            },
            allowed_tools=["use_feature"],
        )
        second_reaction = runner.tool_registry.validate_call(
            state=state,
            tool_name="use_feature",
            args={
                "actor_ref": state.active_character_id,
                "feature_name": "Parry",
                "action_cost": "reaction",
            },
            allowed_tools=["use_feature"],
        )

        self.assertTrue(first_reaction.ok, first_reaction.response())
        self.assertTrue(state.encounter.turn_reaction_used)
        self.assertFalse(second_reaction.ok)
        self.assertIn("reaction already used", second_reaction.error)
        self.assertEqual(second_reaction.metadata["turn_action_cost_arg"], "action_cost")

    def test_use_feature_free_action_does_not_require_open_action_slot(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        logic.mark_current_action_used("attack_target")

        guardrail = self.runner.tool_registry.validate_call(
            state=state,
            tool_name="use_feature",
            args={
                "actor_ref": state.active_character_id,
                "feature_name": "Danger Sense",
                "action_cost": "free",
            },
            allowed_tools=["use_feature"],
        )

        self.assertTrue(guardrail.ok, guardrail.error)
        self.assertEqual(guardrail.args["action_cost"], "free")

    def test_concentration_spell_updates_character_concentration(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        logic = GameLogic(state)
        logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        party_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.linked_character_id == state.active_character_id
        )
        enemy_combatant = next(
            combatant
            for combatant in state.encounter.combatants.values()
            if combatant.side == "enemy"
        )
        logic.set_initiative(party_combatant.combatant_id, 18)
        logic.set_initiative(enemy_combatant.combatant_id, 8)
        character = state.characters[state.active_character_id]
        character.spells.cantrips = ["Blade Ward"]
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=AgentToolService(
                rag_engine=DummyRAGEngine(),
                monster_storage=MonsterStorage(),
                rules_catalog=RuleCatalog(),
            ),
            enable_model=False,
        )

        execution = runner._execute_single_tool(
            state=state,
            tool_name="cast_spell",
            args={
                "caster_ref": character.character_id,
                "spell_name": "Blade Ward",
            },
            allowed_tools=["cast_spell"],
        )

        self.assertTrue(execution.ok, execution.response())
        self.assertEqual(execution.payload["action_cost"], "action")
        self.assertTrue(execution.payload["concentration"])
        self.assertEqual(character.concentration_spell, "剑刃防护")
        self.assertEqual(
            execution.state_patch["characters"][character.character_id]["concentration_spell"],
            "剑刃防护",
        )

    def test_damage_triggers_concentration_save_and_breaks_on_failure(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        character = state.get_active_char()
        character.concentration_spell = "祝福术"
        character.concentration_spell_level = 1

        with patch("game_logic.random.randint", return_value=1):
            result = GameLogic(state).update_target_hp(character.character_id, -8)

        check = result["concentration_check"]
        self.assertEqual(check["dc"], 10)
        self.assertFalse(check["save"]["success"])
        self.assertTrue(check["broken"])
        self.assertEqual(check["previous_spell"], "祝福术")
        self.assertEqual(character.concentration_spell, "")
        self.assertEqual(
            result["patch"]["characters"][character.character_id]["concentration_spell"],
            "",
        )

    def test_agent_adjust_hp_reports_successful_concentration_save(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        character = state.get_active_char()
        character.concentration_spell = "祝福术"
        character.concentration_spell_level = 1
        service = AgentToolService(
            rag_engine=DummyRAGEngine(),
            monster_storage=MonsterStorage(),
            rules_catalog=RuleCatalog(),
        )

        with patch("game_logic.random.randint", return_value=20):
            execution = service.adjust_hp(
                state,
                target_ref=character.character_id,
                amount=-4,
                reason="测试专注豁免",
            )

        self.assertTrue(execution.ok, execution.response())
        self.assertEqual(character.concentration_spell, "祝福术")
        self.assertIn("concentration_check", execution.payload)
        self.assertFalse(execution.payload["concentration_check"]["broken"])
        self.assertIn("专注豁免", execution.tool_result.summary)
        self.assertIn("维持专注", execution.tool_result.summary)

    def test_save_monster_template_stores_template_in_game_state(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        service = AgentToolService(
            rag_engine=DummyRAGEngine(),
            monster_storage=MonsterStorage(),
            rules_catalog=RuleCatalog(),
        )

        with patch.object(service.monster_storage, "save_monster") as save_monster:
            execution = service.save_monster_template(
                state,
                name="影沼猎手",
                creature_type="怪兽",
                challenge_rating="2",
                hp_max=45,
                ac=14,
                actions=["近战攻击检定：+5，触及5尺。命中：8（1d8+4）穿刺伤害。"],
            )

        self.assertTrue(execution.ok, execution.response())
        save_monster.assert_not_called()
        monster_id = execution.payload["monster_id"]
        self.assertIn(monster_id, state.monster_templates)
        self.assertEqual(state.monster_templates[monster_id].source, "game-authored")
        self.assertIn(monster_id, execution.state_patch["monster_templates"])

    def test_spawn_monster_from_game_scoped_template(self) -> None:
        state = self._build_state(with_selected_adventure=True)
        state.monster_templates["mon-shadow-marsh-stalker"] = MonsterTemplate(
            monster_id="mon-shadow-marsh-stalker",
            name="影沼猎手",
            creature_type="怪兽",
            hp_max=45,
            ac=14,
            initiative_bonus=2,
            source="game-authored",
        )
        service = AgentToolService(
            rag_engine=DummyRAGEngine(),
            monster_storage=MonsterStorage(),
            rules_catalog=RuleCatalog(),
        )

        execution = service.spawn_monster_from_template(
            state,
            monster_ref="影沼猎手",
            auto_roll_initiative=False,
        )

        self.assertTrue(execution.ok, execution.response())
        combatant_id = execution.payload["combatant_ids"][0]
        combatant = state.encounter.combatants[combatant_id]
        self.assertEqual(combatant.name, "影沼猎手")
        self.assertEqual(combatant.monster_template_id, "mon-shadow-marsh-stalker")
        self.assertEqual(combatant.hp_max, 45)

    def test_completed_turn_records_node_traces(self) -> None:
        if not self.runner.is_available:
            self.skipTest("LangGraph is unavailable in this runtime.")
        state = self._build_state(with_selected_adventure=True)

        result = self.runner.run_turn(state, "I search the altar for clues.")

        self.assertEqual(result.turn_status, "completed")
        self.assertIsNotNone(result.turn_trace)
        node_names = [node.node_name for node in result.turn_trace.node_traces]
        self.assertIn("plan_turn", node_names)
        self.assertIn("route_phase", node_names)
        self.assertIn("retrieve_rules", node_names)
        self.assertIn("prepare_context", node_names)
        self.assertIn("draft_response", node_names)
        self.assertIn("finalize_turn", node_names)

    def test_high_risk_tool_requires_confirmation_before_execution(self) -> None:
        if not self.runner.is_available:
            self.skipTest("LangGraph is unavailable in this runtime.")
        state = self._build_state(with_selected_adventure=True)
        GameLogic(state).start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=EndEncounterToolService(),
            enable_model=True,
            api_key="test-key",
        )
        runner._model = EndEncounterModel()
        try:
            paused = runner.run_turn(state, "End the encounter.")

            self.assertEqual(paused.turn_status, "input_required")
            self.assertIsNotNone(paused.game_state.pending_turn)
            self.assertEqual(paused.pending_input["kind"], "tool_confirmation")
            self.assertEqual(paused.pending_input["details"]["tool_name"], "end_encounter")
            self.assertTrue(paused.pending_input["details"]["guardrail"]["requires_confirmation"])
            self.assertTrue(paused.game_state.encounter.active)

            resumed = runner.resume_turn(paused.game_state, "确认")

            self.assertEqual(resumed.turn_status, "completed")
            self.assertIsNone(resumed.game_state.pending_turn)
            self.assertFalse(resumed.game_state.encounter.active)
            execute_trace = next(
                node for node in resumed.turn_trace.node_traces if node.node_name == "execute_tools"
            )
            tool_trace = execute_trace.metadata["tools"][0]
            self.assertEqual(tool_trace["tool_name"], "end_encounter")
            self.assertEqual(tool_trace["confirmation_status"], "confirmed")
            self.assertEqual(tool_trace["guardrail"]["risk_level"], "high")
        finally:
            runner.close()

    def test_empty_turn_requests_more_input_without_advancing_turn(self) -> None:
        if not self.runner.is_available:
            self.skipTest("LangGraph is unavailable in this runtime.")
        state = self._build_state(with_selected_adventure=True)

        result = self.runner.run_turn(state, "")

        self.assertEqual(result.turn_status, "input_required")
        self.assertEqual(result.game_state.turn_number, 0)
        self.assertIsNotNone(result.game_state.pending_turn)
        self.assertEqual(result.game_state.pending_turn.details.get("reason"), "empty_input")
        self.assertEqual(len(result.timeline_append), 1)
        self.assertIsNotNone(result.turn_trace)
        self.assertEqual(result.turn_trace.turn_status, "input_required")
        self.assertEqual(len(result.game_state.turn_traces), 1)

    def test_resume_turn_completes_after_pending_input(self) -> None:
        if not self.runner.is_available:
            self.skipTest("LangGraph is unavailable in this runtime.")
        state = self._build_state(with_selected_adventure=True)
        paused = self.runner.run_turn(state, "")

        resumed = self.runner.resume_turn(paused.game_state, "I check the room carefully.")

        self.assertEqual(resumed.turn_status, "completed")
        self.assertIsNone(resumed.game_state.pending_turn)
        self.assertEqual(resumed.game_state.turn_number, 1)
        self.assertIn("LangGraph turn workflow is prepared", resumed.response)
        self.assertIsNotNone(resumed.turn_trace)
        self.assertEqual(resumed.turn_trace.mode, "resume")
        self.assertIsNotNone(resumed.turn_trace.turn_intent)
        self.assertEqual(resumed.turn_trace.turn_intent.turn_type, "action_resolution")
        self.assertEqual(len(resumed.game_state.turn_traces), 2)

    def test_sqlite_checkpoint_survives_new_runner_instance(self) -> None:
        if not self.runner.is_available:
            self.skipTest("LangGraph is unavailable in this runtime.")
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = os.path.join(tmpdir, "checkpoints.sqlite")
            runner_a = DMGraphRunner(
                rag_engine=DummyRAGEngine(),
                tool_service=object(),
                enable_model=False,
                checkpoint_mode="sqlite",
                checkpoint_db_path=checkpoint_path,
            )
            try:
                state = self._build_state(with_selected_adventure=True)
                paused = runner_a.run_turn(state, "")
            finally:
                runner_a.close()

            self.assertEqual(paused.turn_status, "input_required")
            self.assertTrue(os.path.exists(checkpoint_path))

            runner_b = DMGraphRunner(
                rag_engine=DummyRAGEngine(),
                tool_service=object(),
                enable_model=False,
                checkpoint_mode="sqlite",
                checkpoint_db_path=checkpoint_path,
            )
            try:
                resumed = runner_b.resume_turn(paused.game_state, "I search the altar for clues.")
            finally:
                runner_b.close()

            self.assertEqual(resumed.turn_status, "completed")
            self.assertIsNone(resumed.game_state.pending_turn)
            self.assertEqual(resumed.game_state.turn_number, 1)
            self.assertEqual(runner_b.checkpoint_backend, "sqlite")
            self.assertEqual(len(resumed.game_state.turn_traces), 2)

    def test_model_error_is_reported_without_crashing_turn(self) -> None:
        class ExplodingModel:
            def bind_tools(self, tool_schemas):
                return self

            def invoke(self, messages):
                raise RuntimeError("Quota exhausted at provider")

        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=object(),
            enable_model=True,
            **{"api_key": "test-key"},
        )
        runner._model = ExplodingModel()
        state = self._build_state(with_selected_adventure=True)

        result = runner.run_turn(state, "I inspect the chapel.")

        self.assertEqual(result.turn_status, "failed")
        self.assertEqual(result.game_state.turn_number, 0)
        self.assertIn("当前模型服务不可用", result.response)
        self.assertIn("Quota exhausted at provider", result.response)
        self.assertIn("model_error", result.rag_metadata)
        self.assertIn("Model invocation failed:", result.turn_trace.validation_notes[-1])
        self.assertEqual(result.validation_issues[-1].validator, "model_call")
        self.assertEqual(result.validation_issues[-1].severity, "error")
        self.assertEqual(result.turn_trace.validation_issues[-1].action, "failed_turn")
        runner.close()

    def test_repair_required_model_response_without_tool_fails_turn(self) -> None:
        class NoToolModel:
            def bind_tools(self, tool_schemas):
                return self

            def invoke(self, messages):
                return AIMessage(content="我会直接说明状态已经修好了。")

        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=object(),
            enable_model=True,
            **{"api_key": "test-key"},
        )
        runner._model = NoToolModel()

        result = runner._call_model(
            {
                "messages": [AIMessage(content="previous")],
                "allowed_tools": ["set_scene"],
                "suggested_tools": ["set_scene"],
                "validation_status": "repair_required",
                "validation_notes": ["Encounter is active but scene/campaign phase is not combat."],
                "validation_issues": [],
                "node_traces": [],
            }
        )

        self.assertEqual(result["turn_status"], "failed")
        self.assertIn("没有发起必要工具调用", result["final_response"])
        self.assertEqual(result["validation_issues"][-1]["validator"], "turn_repair")
        self.assertEqual(result["validation_issues"][-1]["action"], "failed_turn")

    def test_missing_required_tool_after_retry_fails_turn(self) -> None:
        class NoToolModel:
            def __init__(self):
                self.calls = 0

            def bind_tools(self, tool_schemas):
                return self

            def invoke(self, messages):
                self.calls += 1
                return AIMessage(content="我掷骰并告诉你结果。")

        model = NoToolModel()
        runner = DMGraphRunner(
            rag_engine=DummyRAGEngine(),
            tool_service=object(),
            enable_model=True,
            **{"api_key": "test-key"},
        )
        runner._model = model

        result = runner._call_model(
            {
                "messages": [AIMessage(content="previous")],
                "user_input": "请调用 roll_dice 掷 1d20",
                "allowed_tools": ["roll_dice"],
                "suggested_tools": ["roll_dice"],
                "validation_notes": [],
                "validation_issues": [],
                "node_traces": [],
            }
        )

        self.assertEqual(model.calls, 2)
        self.assertEqual(result["turn_status"], "failed")
        self.assertEqual(result["validation_issues"][-1]["validator"], "tool_required")

    def test_normalize_openai_base_url_only_appends_v1_for_root_paths(self) -> None:
        self.assertEqual(normalize_openai_base_url("https://api.example.com"), "https://api.example.com/v1")
        self.assertEqual(
            normalize_openai_base_url("https://open.bigmodel.cn/api/coding/paas/v4"),
            "https://open.bigmodel.cn/api/coding/paas/v4",
        )


if __name__ == "__main__":
    unittest.main()
