import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")
os.environ.setdefault("RAG_AUTO_CONTEXT_RESULTS", "0")
from agent_tools import AgentToolService
from game_logic import GameLogic
from models import Character, GameState, HidingState, InventoryItem, Spellbook
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from roll_capture import capture_rolls
from stealth_rules import combine_roll_mode
from dm_graph import DMGraphRunner
from langchain_core.messages import AIMessage
import test_dm_graph_workflow as fixtures


class SurpriseRulesTests(unittest.TestCase):
    def setUp(self):
        self.state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        self.actor = self.state.get_active_char()
        self.actor.stats.dexterity = 14
        self.actor.initiative_bonus = 2
        self.actor.inventory = [InventoryItem(name="Dagger", type="weapon")]
        self.rules = RuleCatalog()
        self.service = AgentToolService(fixtures.DummyRAGEngine(), MonsterStorage(), self.rules)

    def hide(self, roll=15, **kwargs):
        with patch("game_logic.random.randint", return_value=roll):
            return self.service.hide_actor(self.state, self.actor.character_id,
                kwargs.get("cover", "total"), kwargs.get("observed", False), "Behind an established wall")

    def start(self, surprise=True):
        with patch("game_logic.random.randint", side_effect=[12, 19, 18, 4] if surprise else [12, 19, 18]):
            result = self.service.start_encounter(self.state, ["Goblin"], 7, 12,
                surprised_refs=["Goblin"] if surprise else [], surprise_reason="Unaware of the ambush" if surprise else "")
        self.assertTrue(result.ok, result.error)
        return next(c for c in self.state.encounter.combatants.values() if c.side == "enemy")

    def test_hide_validates_cover_and_sight_before_roll_without_mutation(self):
        for cover, observed in (("none", False), ("total", True)):
            before = self.state.model_dump(mode="json")
            with patch("game_logic.random.randint") as rng:
                result = self.service.hide_actor(self.state, self.actor.character_id, cover, observed, "Established scene")
            self.assertFalse(result.ok)
            self.assertEqual(self.state.model_dump(mode="json"), before)
            rng.assert_not_called()

    def test_hide_derives_modifier_and_survives_serialization(self):
        result = self.hide()
        self.assertTrue(result.ok)
        self.assertEqual(result.payload["total"], 17)
        self.assertFalse(result.payload["action_spent"])
        restored = GameState.model_validate(self.state.model_dump(mode="json"))
        self.assertEqual(restored.get_active_char().hiding.stealth_total, 17)
        self.assertNotIn("invisible", restored.get_active_char().status_effects)

    def test_surprise_and_hide_roll_two_dice_and_do_not_skip_turn(self):
        self.hide()
        with capture_rolls() as capture:
            enemy = self.start()
        rolls = [r for r in capture.records if r.kind == "initiative"]
        self.assertEqual([r.roll_mode for r in rolls], ["advantage", "disadvantage"])
        self.assertEqual([r.kept for r in rolls], [[19], [4]])
        logic = GameLogic(self.state)
        logic.advance_turn()
        self.assertEqual(self.state.encounter.current_combatant_id, enemy.combatant_id)
        logic.require_current_actor(enemy.combatant_id)
        self.assertFalse(self.state.encounter.turn_action_used)

    def test_surprised_and_invisible_initiative_cancel(self):
        self.hide()
        with patch("game_logic.random.randint", side_effect=[12, 8]):
            result = self.service.start_encounter(self.state, ["Goblin"], 7, 12,
                surprised_refs=[self.actor.character_id], surprise_reason="A second ambusher")
        self.assertTrue(result.ok)
        party = next(c for c in self.state.encounter.combatants.values() if c.side == "party")
        self.assertEqual(party.initiative_roll_mode, "normal")

    def test_active_encounter_cannot_be_restarted_for_surprise(self):
        self.hide()
        self.start()
        before = self.state.model_dump(mode="json")
        result = self.service.start_encounter(self.state, ["Another"], surprised_refs=["Another"], surprise_reason="Again")
        self.assertFalse(result.ok)
        self.assertEqual(self.state.model_dump(mode="json"), before)

    def test_unknown_surprise_participant_does_not_start_encounter(self):
        before = self.state.model_dump(mode="json")
        result = self.service.start_encounter(self.state, ["Goblin"], surprised_refs=["Unknown"], surprise_reason="Unaware")
        self.assertFalse(result.ok)
        self.assertEqual(self.state.model_dump(mode="json"), before)

    def test_missed_attack_uses_advantage_then_ends_only_hide(self):
        self.hide()
        enemy = self.start()
        self.state.get_active_char().status_effects.append("Invisible")
        GameLogic(self.state)._sync_combatant_from_character(self.state.get_active_char())
        with capture_rolls() as capture, patch("game_logic.random.randint", side_effect=[1, 2]):
            result = self.service.attack_target(self.state, self.actor.character_id, enemy.combatant_id, attack_name="Dagger")
        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.payload["hit"])
        self.assertEqual(result.payload["roll_mode"], "advantage")
        self.assertEqual(capture.records[0].dice, [1, 2])
        self.assertIsNone(self.state.get_active_char().hiding)
        self.assertIn("Invisible", self.state.get_active_char().status_effects)
        self.assertIsNone(GameLogic(self.state).get_combatant(self.actor.character_id).hiding)

    def test_visibility_exception_and_advantage_cancellation(self):
        self.hide()
        enemy = self.start()
        with capture_rolls() as capture, patch("game_logic.random.randint", return_value=1):
            result = self.service.attack_target(self.state, self.actor.character_id, enemy.combatant_id,
                attack_name="Dagger", target_sees_invisible=True, reason="Established special sense sees attacker")
        self.assertTrue(result.ok)
        self.assertEqual(capture.records[0].roll_mode, "normal")
        self.assertEqual(len(capture.records[0].dice), 1)
        self.assertEqual(combine_roll_mode("disadvantage", advantage=True), "normal")
        self.assertEqual(self.service._roll_mode_error("优势和劣势相互抵消", "normal"), "")

    def test_hidden_target_applies_disadvantage_with_english_reason(self):
        logic = GameLogic(self.state)
        encounter = logic.start_encounter(["Goblin"], enemy_hp=7, enemy_ac=12)
        for c in encounter.combatants.values(): logic.set_initiative(c.combatant_id, 20 if c.side == "party" else 1)
        enemy = next(c for c in encounter.combatants.values() if c.side == "enemy")
        enemy.hiding = HidingState(stealth_total=17, cover="total")
        with capture_rolls() as capture, patch("game_logic.random.randint", side_effect=[15,3]):
            result = self.service.attack_target(self.state, self.actor.character_id, enemy.combatant_id,
                                                attack_name="Dagger", reason="Unseen target imposes disadvantage")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(capture.records[0].roll_mode, "disadvantage")
        self.assertEqual(capture.records[0].kept, [3])

    def test_failed_hide_in_combat_spends_action_and_has_no_hidden_state(self):
        logic = GameLogic(self.state)
        encounter = logic.start_encounter(["Goblin"])
        for c in encounter.combatants.values():
            logic.set_initiative(c.combatant_id, 20 if c.side == "party" else 1)
        result = self.hide(roll=1)
        self.assertTrue(result.ok)
        self.assertFalse(result.payload["success"])
        self.assertTrue(self.state.encounter.turn_action_used)
        self.assertIsNone(self.state.get_active_char().hiding)
        before = self.state.model_dump(mode="json")
        second = self.hide()
        self.assertFalse(second.ok)
        self.assertEqual(before, self.state.model_dump(mode="json"))

    def test_active_and_passive_detection_use_stored_dc(self):
        self.hide()
        enemy = self.start()
        enemy.skills["察觉"] = 8
        before_action = self.state.encounter.turn_action_used
        result = self.service.search_hidden(self.state, enemy.combatant_id, self.actor.character_id, passive=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.payload["total"], 18)
        self.assertEqual(result.payload["dc"], 17)
        self.assertTrue(result.payload["hiding_ended"])
        self.assertEqual(self.state.encounter.turn_action_used, before_action)
        self.assertIsNone(self.state.get_active_char().hiding)

    def test_failed_cast_preserves_hide_but_verbal_cast_ends_it(self):
        self.actor.class_name = "Bard"
        self.actor.spells = Spellbook(prepared=["Charm Person"], slots={"1": {"total": 1}})
        self.hide()
        failed = self.service.cast_spell(self.state, self.actor.character_id, "Unknown spell")
        self.assertFalse(failed.ok)
        self.assertIsNotNone(self.state.get_active_char().hiding)
        success = self.service.cast_spell(self.state, self.actor.character_id, "Charm Person", 1)
        self.assertTrue(success.ok, success.error)
        self.assertIsNone(self.state.get_active_char().hiding)

    def test_noise_ends_hide_and_legacy_saves_default_to_no_hide(self):
        self.hide()
        result = self.service.end_hiding(self.state, self.actor.character_id, "Actor shouts above a whisper")
        self.assertTrue(result.ok)
        self.assertIsNone(self.state.get_active_char().hiding)
        self.assertIsNone(Character.model_validate({"name":"Legacy"}).hiding)

    def test_ambush_guard_requires_hide_or_explicit_impossibility(self):
        runner = DMGraphRunner(fixtures.DummyRAGEngine(), tool_service=self.service, checkpoint_mode="memory")
        try:
            graph = {"game_state": self.state.model_dump(mode="json"), "turn_intent":{"intent_tags":["hostile_attack","stealth_approach"]}}
            self.assertTrue(runner._repair_tool_call_error(graph, "start_encounter", {"enemy_names":["Goblin"]}))
            self.assertEqual(runner._repair_tool_call_error(graph, "start_encounter", {"enemy_names":["Goblin"],"approach_reason":"No cover and enemy already alert"}), "")
            self.assertEqual(runner._repair_tool_call_error(graph, "start_encounter", {"enemy_names":["Goblin"],"surprised_refs":["Goblin"],"surprise_basis":"other","approach_reason":"An established unsuspecting betrayal"}), "")
        finally:
            runner.close()

    def test_other_surprise_requires_explicit_scene_basis_without_granting_hide(self):
        before = self.state.model_dump(mode="json")
        invalid = self.service.start_encounter(self.state, ["Goblin"], surprised_refs=["Goblin"], surprise_reason="Unaware", surprise_basis="other")
        self.assertFalse(invalid.ok)
        self.assertEqual(before, self.state.model_dump(mode="json"))
        with patch("game_logic.random.randint", side_effect=[12, 18, 4]), capture_rolls() as capture:
            valid = self.service.start_encounter(self.state, ["Goblin"], surprised_refs=["Goblin"], surprise_reason="Unaware of sudden hostility",
                                                  surprise_basis="other", approach_reason="An established unsuspecting betrayal")
        self.assertTrue(valid.ok)
        self.assertEqual([r.roll_mode for r in capture.records], ["normal", "disadvantage"])
        self.assertIsNone(self.state.get_active_char().hiding)

    def test_noise_and_search_intents_route_to_the_correct_stealth_tools(self):
        self.hide()
        runner = DMGraphRunner(fixtures.DummyRAGEngine(), tool_service=self.service, checkpoint_mode="memory")
        try:
            noise = runner._plan_turn_intent(self.state, "我从墙后现身并大喊。", "exploration", "exploration")
            self.assertIn("end_hiding", noise.suggested_tools)
            self.assertEqual(noise.turn_type, "action_resolution")
            search = runner._suggested_resolution_tools(self.state, "我要找出躲藏的地精。", "exploration")
            self.assertIn("search_hidden", search)
            self.assertNotIn("hide_actor", search)
        finally:
            runner.close()

    def test_active_search_costs_action_and_ends_hide_on_success(self):
        self.hide()
        enemy = self.start()
        before = self.state.model_dump(mode="json")
        blocked = self.service.search_hidden(self.state, enemy.combatant_id, self.actor.character_id)
        self.assertFalse(blocked.ok)
        self.assertEqual(before, self.state.model_dump(mode="json"))
        GameLogic(self.state).advance_turn()
        with patch("game_logic.random.randint", return_value=20):
            found = self.service.search_hidden(self.state, enemy.combatant_id, self.actor.character_id)
        self.assertTrue(found.ok)
        self.assertTrue(found.payload["hiding_ended"])
        self.assertTrue(self.state.encounter.turn_action_used)

    def test_nonverbal_spell_keeps_hide(self):
        self.actor.class_name = "Bard"
        self.actor.spells = Spellbook(cantrips=["Friends"])
        self.hide()
        result = self.service.cast_spell(self.state, self.actor.character_id, "Friends")
        self.assertTrue(result.ok, result.error)
        self.assertIsNotNone(self.state.get_active_char().hiding)

    def run_scripted_turn(self, responses, text, dice):
        class Model:
            def __init__(self): self.calls = 0
            def bind_tools(self, _tools): return self
            def bind(self, **_kwargs): return self
            def invoke(self, _messages):
                value = responses[self.calls]
                self.calls += 1
                if isinstance(value, Exception): raise value
                return value
        model = Model()
        runner = DMGraphRunner(fixtures.DummyRAGEngine(), tool_service=self.service, enable_model=True, checkpoint_mode="memory")
        runner._model = model
        try:
            with patch("game_logic.random.randint", side_effect=dice), capture_rolls() as capture:
                result = runner.run_turn(self.state, text)
            return result, capture.records, model.calls
        finally:
            runner.close()

    def hide_message(self):
        return AIMessage(content="先借断墙遮蔽身形。", tool_calls=[{"id":"hide","name":"hide_actor","args":{
            "actor_ref":self.actor.character_id,"cover":"total","observed":False,"reason":"An established wall blocks enemy sight"}}])

    def test_exploration_ambush_runs_hide_initiative_and_attack_in_one_transaction(self):
        result, rolls, calls = self.run_scripted_turn([
            self.hide_message(),
            AIMessage(content="", tool_calls=[{"id":"start","name":"start_encounter","args":{
                "enemy_names":["Goblin"],"enemy_hp":7,"enemy_ac":12,
                "surprised_refs":["Goblin"],"surprise_reason":"The guard has not noticed the hidden attacker"}}]),
            AIMessage(content="", tool_calls=[{"id":"attack","name":"attack_target","args":{
                "attacker_ref":self.actor.character_id,"target_ref":"Goblin","attack_name":"Dagger"}}]),
            AIMessage(content="你从断墙后出手，匕首击中了地精，随后暴露了位置。"),
        ], "我借墙躲藏后偷袭地精。", [15, 12, 19, 18, 4, 15, 16, 2])
        self.assertEqual(result.turn_status, "completed", result.response)
        self.assertEqual(calls, 4)
        self.assertEqual([r.roll_mode for r in rolls if r.kind == "initiative"], ["advantage", "disadvantage"])
        self.assertEqual(next(r for r in rolls if r.kind == "attack").roll_mode, "advantage")
        self.assertIsNone(result.game_state.get_active_char().hiding)
        self.assertEqual([r.tool_name for r in result.tool_results], ["hide_actor","encounter.start","combat.attack_target"])

    def test_combat_hide_can_finish_without_forced_second_action(self):
        logic = GameLogic(self.state)
        encounter = logic.start_encounter(["Goblin"])
        for c in encounter.combatants.values(): logic.set_initiative(c.combatant_id, 20 if c.side == "party" else 1)
        result, _, calls = self.run_scripted_turn([self.hide_message(), AIMessage(content="你藏在断墙后。本回合的动作已用于躲藏，等待之后再出手。")],
                                                 "我躲藏后准备偷袭。", [15])
        self.assertEqual(result.turn_status, "completed", result.response)
        self.assertEqual(calls, 2)
        self.assertTrue(result.game_state.encounter.turn_action_used)
        self.assertIsNotNone(result.game_state.get_active_char().hiding)

    def test_failed_turn_rolls_back_hide_state(self):
        result, _, _ = self.run_scripted_turn([self.hide_message(), RuntimeError("synthetic outage")], "我躲藏准备偷袭。", [15])
        self.assertEqual(result.turn_status, "failed")
        self.assertIsNone(result.game_state.get_active_char().hiding)
        self.assertEqual(result.tool_results, [])

    def test_local_api_start_and_attack_share_surprise_and_hide_rules(self):
        from fastapi.testclient import TestClient
        import main as api
        from test_main_streaming import FakeStorage
        self.hide()
        fake = FakeStorage(self.state)
        with patch.object(api, "game_storage", fake), TestClient(api.app) as client:
            with patch("game_logic.random.randint", side_effect=[12, 19, 18, 4]):
                response = client.post(f"/api/v1/games/{self.state.game_id}/encounters/start", json={
                    "enemy_names":["Goblin"], "enemy_hp":7, "enemy_ac":12,
                    "surprised_refs":["Goblin"], "surprise_reason":"Unaware of the hidden attacker"})
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()["game_state"]
            enemy = next(c for c in payload["encounter"]["combatants"].values() if c["side"] == "enemy")
            self.assertTrue(enemy["surprised_at_start"])
            self.assertEqual(enemy["initiative_roll_mode"], "disadvantage")
            with patch("game_logic.random.randint", side_effect=[1,2]):
                attack = client.post(f"/api/v1/games/{self.state.game_id}/actions/attack", json={
                    "attacker_ref":self.actor.character_id,"target_ref":enemy["combatant_id"],"attack_name":"Dagger"})
            self.assertEqual(attack.status_code, 200, attack.text)
            self.assertIsNone(attack.json()["game_state"]["characters"][self.actor.character_id]["hiding"])

    def test_sse_transmits_hide_roll_before_final_state(self):
        import asyncio, json
        import main as api
        from test_main_streaming import FakeStorage
        from models import TurnResult, ChatMessage
        async def turn(state, message):
            self.service.hide_actor(state, state.active_character_id, "total", False, "Established wall")
            state.chat_history.extend([ChatMessage(role="user", content=message), ChatMessage(role="assistant", content="你成功藏好。")])
            return TurnResult(response="你成功藏好。", game_state=state, turn_status="completed", history=state.chat_history)
        async def collect():
            response = api._stream_turn_response(self.state.game_id, self.state, "躲藏")
            return "".join([chunk async for chunk in response.body_iterator])
        with patch.object(api, "game_storage", FakeStorage(self.state)), patch.object(api.agent, "run_turn", side_effect=turn), patch("game_logic.random.randint", return_value=15):
            events = asyncio.run(collect())
        self.assertLess(events.index("event: roll.recorded"), events.index("event: turn.completed"))
        block = next(block for block in events.split("\n\n") if block.startswith("event: turn.completed"))
        payload = json.loads(next(line[6:] for line in block.splitlines() if line.startswith("data: ")))
        self.assertEqual(payload["roll_records"][0]["total"], 17)
        self.assertEqual(payload["game_state"]["characters"][self.actor.character_id]["hiding"]["stealth_total"], 17)
