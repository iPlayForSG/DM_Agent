"""后端审计修复：验证期望行为，所有存储用临时目录。"""
import asyncio
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DM_AGENT_SKIP_DOTENV", "1")
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
import main as api
import storage as storage_module
from action_service import GameActionService
from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import Character, ChatMessage, Combatant, EncounterState, GameState, InventoryItem, MonsterTemplate, SessionEvent, SpellSlot, Stats, ToolResult, TurnResult, TurnTrace
from player_projection import player_payload
from rules_catalog import RuleCatalog
from storage import GameStorage, MonsterStorage, StateConflictError
from test_dm_graph_workflow import DummyRAGEngine
import test_dm_graph_workflow as workflow_fixtures
from test_main_streaming import FakeAgent, patched_runtime


def combat_fixture(level=1):
    hero = Character(name="Test Wizard", class_name="Wizard", level=level, hp_current=20, hp_max=20,
                     stats=Stats(intelligence=16), inventory=[InventoryItem(name="Quarterstaff", type="weapon")])
    hero.spells.cantrips = ["Fire Bolt", "Eldritch Blast"]
    hero.spells.prepared = ["Shield"]
    hero.spells.slots = {"1": SpellSlot(total=3)}
    state = GameState(game_id="test", characters={hero.character_id: hero}, scene="exploration")
    logic = GameLogic(state)
    encounter = logic.start_encounter(["Test Enemy"], enemy_hp=40)
    enemy = next(item for item in encounter.combatants.values() if item.side == "enemy")
    logic.set_initiative(hero.character_id, 20)
    logic.set_initiative(enemy.combatant_id, 10)
    return state, hero.character_id, enemy.combatant_id


class PersistenceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="dm-storage-regression-")
        self.addCleanup(self.directory.cleanup)
        for name, path in (("GAME_DIR", "games"), ("REWIND_DIR", "rewind"), ("CHAR_DIR", "characters")):
            mocker = patch.object(storage_module, name, str(Path(self.directory.name) / path))
            mocker.start()
            self.addCleanup(mocker.stop)
        self.storage = GameStorage()
        self.state = GameState(game_id="test", scene="exploration")
        self.storage.save_game("test", self.state)

    def test_serialization_failure_preserves_previous_game(self):
        path = Path(self.storage._get_path("test"))
        before = path.read_bytes()
        version = self.state.state_version
        with patch.object(GameState, "model_dump_json", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                self.storage.save_game("test", self.state)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.state.state_version, version)

    def test_replace_failure_preserves_previous_game_and_cleans_temp(self):
        path = Path(self.storage._get_path("test"))
        before = path.read_bytes()
        with patch("storage.os.replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.storage.save_game("test", self.state)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".save-*")), [])

    def test_stale_snapshot_cannot_overwrite_a_later_save(self):
        stale = self.storage.load_game("test")
        self.state.title = "new title"
        self.storage.save_game("test", self.state)
        with self.assertRaises(StateConflictError):
            self.storage.save_game("test", stale)
        self.assertEqual(self.storage.load_game("test").title, "new title")

    def test_late_turn_rejects_instead_of_overwriting_saved_settings(self):
        started, release = threading.Event(), threading.Event()

        class Agent:
            async def run_turn(self, state, message):
                started.set()
                await asyncio.to_thread(release.wait, 5)
                state.turn_number += 1
                return TurnResult(response="done", game_state=state)

        async def scenario():
            task = asyncio.create_task(api.run_turn("test", api.ChatRequest(message="wait")))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                await api.update_game_reply_length("test", api.ReplyLengthSettingsRequest(min_chars=200, max_chars=400))
            finally:
                release.set()
            with self.assertRaises(StateConflictError):
                await task

        with patched_runtime(Agent(), self.storage):
            asyncio.run(scenario())
        actual = self.storage.load_game("test")
        self.assertEqual((actual.campaign.reply_min_chars, actual.turn_number), (200, 0))
        self.assertIsNone(self.storage.load_rewind_snapshot("test", 0))

    def test_deleted_or_recreated_game_rejects_old_turn(self):
        expected = self.state.state_version
        self.storage.delete_game("test")
        with self.assertRaises(StateConflictError):
            self.storage.save_turn("test", self.state, expected_version=expected, snapshots={}, prune_from=0)
        replacement = GameState(game_id="test", title="replacement")
        self.storage.save_game("test", replacement)
        with self.assertRaises(StateConflictError):
            self.storage.save_turn("test", self.state, expected_version=expected, snapshots={}, prune_from=0)
        self.assertEqual(self.storage.load_game("test").title, "replacement")

    def test_projection_cache_does_not_invalidate_business_version(self):
        self.state.chat_history.append(ChatMessage(role="assistant", content="cached"))
        self.storage.save_game("test", self.state)
        version = self.state.state_version
        projected = self.storage.load_game("test")
        projected.chat_history[0].action_suggestions_generated = True
        self.storage.save_game("test", projected, projection_only=True)
        self.assertEqual(self.storage.load_game("test").state_version, version)

    def test_projection_mode_cannot_bypass_business_versioning(self):
        changed = self.storage.load_game("test")
        changed.title = "unauthorized projection change"
        with self.assertRaises(ValueError):
            self.storage.save_game("test", changed, projection_only=True)

    def test_separate_processes_cannot_both_commit_the_same_version(self):
        gate = Path(self.directory.name) / "go"
        code = """
import pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import storage
storage.GAME_DIR, storage.REWIND_DIR = sys.argv[2:4]
repo = storage.GameStorage()
state = repo.load_game('test')
pathlib.Path(sys.argv[4]).touch()
deadline = time.monotonic() + 10
while not pathlib.Path(sys.argv[5]).exists():
    if time.monotonic() > deadline: raise RuntimeError('barrier timeout')
    time.sleep(.01)
state.title = sys.argv[4]
try:
    repo.save_game('test', state)
    print('saved')
except storage.StateConflictError:
    print('conflict')
"""
        children, ready = [], []
        try:
            for index in range(2):
                marker = Path(self.directory.name) / f"ready-{index}"
                ready.append(marker)
                children.append(subprocess.Popen(
                    [sys.executable, "-c", code, str(ROOT / "backend"), storage_module.GAME_DIR,
                     storage_module.REWIND_DIR, str(marker), str(gate)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ))
            deadline = time.monotonic() + 10
            while not all(marker.exists() for marker in ready) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(all(marker.exists() for marker in ready))
            gate.touch()
            outcomes = []
            for child in children:
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                outcomes.append(stdout.strip())
            self.assertCountEqual(outcomes, ["saved", "conflict"])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()

    def test_rewrite_exception_preserves_live_branch_and_all_snapshots(self):
        self.state.chat_history = [ChatMessage(role="user", content="old"), ChatMessage(role="assistant", content="reply")]
        self.storage.save_game("test", self.state)
        self.storage.save_rewind_snapshot("test", 0, GameState(game_id="test"))
        self.storage.save_rewind_snapshot("test", 1, self.state)
        paths = [Path(self.storage._get_path("test")), Path(self.storage._get_rewind_path("test", 0)), Path(self.storage._get_rewind_path("test", 1))]
        before = [path.read_bytes() for path in paths]

        class Agent:
            async def run_turn(self, state, message):
                raise RuntimeError("synthetic transport failure")

        with patched_runtime(Agent(), self.storage), self.assertRaises(api.HTTPException):
            asyncio.run(api.rewrite_game_message("test", 0, api.RewriteMessageRequest(message="new")))
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_failed_turn_file_publish_restores_replaced_snapshots(self):
        self.storage.save_rewind_snapshot("test", 0, self.state)
        self.storage.save_rewind_snapshot("test", 1, self.state)
        paths = [Path(self.storage._get_rewind_path("test", index)) for index in (0, 1)]
        before = [path.read_bytes() for path in paths]
        replace = os.replace
        def fail_game(source, target):
            if target == self.storage._get_path("test"):
                raise OSError("synthetic game publish failure")
            return replace(source, target)
        with patch("storage.os.replace", side_effect=fail_game), self.assertRaises(OSError):
            self.storage.save_turn("test", self.state, expected_version=self.state.state_version,
                                   snapshots={0: GameState(title="new"), 1: GameState(title="new")}, prune_from=0)
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_failed_result_from_rewrite_keeps_original_branch(self):
        self.state.chat_history = [ChatMessage(role="user", content="old"), ChatMessage(role="assistant", content="old reply")]
        self.storage.save_game("test", self.state)
        self.storage.save_rewind_snapshot("test", 0, GameState(game_id="test"))
        self.storage.save_rewind_snapshot("test", 1, self.state)
        before = self.storage.load_game("test").model_dump(mode="json")
        failed = TurnResult(response="synthetic failure", turn_status="failed", game_state=GameState(game_id="test"))
        with patched_runtime(FakeAgent(failed), self.storage), self.assertRaises(api.HTTPException):
            asyncio.run(api.rewrite_game_message("test", 0, api.RewriteMessageRequest(message="new")))
        self.assertEqual(self.storage.load_game("test").model_dump(mode="json"), before)
        self.assertIsNotNone(self.storage.load_rewind_snapshot("test", 1))

    def test_explicit_rewind_restores_historical_inventory(self):
        hero = Character(name="Hero", inventory=[InventoryItem(name="Token", quantity=2)])
        snapshot = GameState(game_id="test", characters={hero.character_id: hero})
        self.state.characters = {hero.character_id: hero.model_copy(deep=True)}
        self.state.characters[hero.character_id].inventory[0].quantity = 1
        self.state.chat_history = [ChatMessage(role="user", content="use token"), ChatMessage(role="assistant", content="done")]
        self.storage.save_game("test", self.state)
        self.storage.save_rewind_snapshot("test", 0, snapshot)
        with patch.object(api, "game_storage", self.storage):
            asyncio.run(api.delete_game_message("test", 0))
        self.assertEqual(self.storage.load_game("test").characters[hero.character_id].inventory[0].quantity, 2)


class CombatRegressionTests(unittest.TestCase):
    def test_legacy_combatant_inherits_missing_temp_hp_only(self):
        state, hero, _ = combat_fixture()
        raw = state.model_dump(mode="json")
        raw["characters"][hero]["temp_hp"] = 5
        combatant_id = GameLogic(state).get_combatant(hero).combatant_id
        del raw["encounter"]["combatants"][combatant_id]["temp_hp"]
        migrated = GameState.model_validate(raw)
        self.assertEqual(migrated.encounter.combatants[combatant_id].temp_hp, 5)
        raw["encounter"]["combatants"][combatant_id]["temp_hp"] = 0
        self.assertEqual(GameState.model_validate(raw).encounter.combatants[combatant_id].temp_hp, 0)

    def test_actor_actions_wait_for_initial_initiative(self):
        state, hero, enemy = combat_fixture()
        state.encounter.turn_order_started = False
        state.encounter.current_combatant_id = None
        state.encounter.combatants[enemy].initiative = None
        with self.assertRaisesRegex(ValueError, "initiative"):
            GameActionService().attack_target(state, hero, enemy)

    def test_repeated_template_spawns_preserve_injured_instances(self):
        state = GameState()
        logic = GameLogic(state)
        template = MonsterTemplate(name="Goblin", hp_max=10)
        first = logic.add_monster_from_template(template, quantity=2)
        first[0].hp_current = 2
        second = logic.add_monster_from_template(template)[0]
        self.assertEqual(len(state.encounter.combatants), 3)
        self.assertNotIn(second.combatant_id, {entry.combatant_id for entry in first})
        self.assertEqual(state.encounter.combatants[first[0].combatant_id].hp_current, 2)

    def test_temporary_hp_absorbs_damage_for_both_character_references(self):
        for by_combatant in (False, True):
            state, hero, _ = combat_fixture()
            logic = GameLogic(state)
            character = state.characters[hero]
            character.temp_hp = 5
            combatant = logic._sync_combatant_from_character(character)
            ref = combatant.combatant_id if by_combatant else hero
            logic.update_target_hp(ref, -3)
            self.assertEqual((character.hp_current, character.temp_hp, combatant.hp_current, combatant.temp_hp), (20, 2, 20, 2))
            logic.update_target_hp(ref, -4)
            self.assertEqual((character.hp_current, character.temp_hp, combatant.hp_current, combatant.temp_hp), (18, 0, 18, 0))

    def test_temp_hp_damage_still_checks_concentration(self):
        state, hero, _ = combat_fixture()
        character = state.characters[hero]
        character.temp_hp = 5
        character.concentration_spell = "Bless"
        with patch("game_logic.DiceRoller.roll_d20", return_value=(1, 1, "synthetic")):
            result = GameLogic(state).update_target_hp(hero, -3)
        self.assertEqual((character.hp_current, character.temp_hp, character.concentration_spell), (20, 2, ""))
        self.assertEqual(result["concentration_check"]["damage_amount"], 3)

    def test_zero_initiative_sorts_above_negative(self):
        zero, negative = Combatant(name="Zero", initiative=0), Combatant(name="Negative", initiative=-1)
        state = GameState(encounter=EncounterState(combatants={zero.combatant_id: zero, negative.combatant_id: negative}))
        GameLogic(state)._refresh_initiative_order()
        self.assertEqual(state.encounter.initiative_order, [zero.combatant_id, negative.combatant_id])

    def test_editing_or_rerolling_initiative_keeps_actor_and_used_action(self):
        state, hero, enemy = combat_fixture()
        logic = GameLogic(state)
        current = state.encounter.current_combatant_id
        logic.mark_current_action_used("attack_target")
        logic.set_initiative(enemy, 30)
        with patch("game_logic.DiceRoller.roll", return_value=(40, "synthetic")):
            logic.roll_initiative(enemy)
        self.assertEqual(state.encounter.current_combatant_id, current)
        self.assertTrue(state.encounter.turn_action_used)

    def test_conditions_block_actual_actions_and_break_concentration(self):
        for status in ("Incapacitated", "Stunned", "Paralyzed", "Unconscious", "失能", "震慑"):
            with self.subTest(status=status):
                state, hero, enemy = combat_fixture()
                state.characters[hero].concentration_spell = "Bless"
                GameLogic(state).add_status(hero, status)
                self.assertEqual(state.characters[hero].concentration_spell, "")
                with self.assertRaisesRegex(ValueError, "incapacitated"):
                    GameActionService().attack_target(state, hero, enemy)
                self.assertFalse(GameLogic._combatant_can_take_turn(GameLogic(state).get_combatant(hero)))

    def test_off_turn_reaction_belongs_to_actor_until_their_next_turn(self):
        state, hero, enemy = combat_fixture()
        logic = GameLogic(state)
        another = logic.add_enemy("Another")
        logic.set_initiative(another.combatant_id, 5)
        logic.advance_turn()
        actions = GameActionService()
        actions.cast_spell(state, hero, "Shield", 1)
        self.assertEqual(state.encounter.current_combatant_id, enemy)
        self.assertFalse(state.encounter.turn_action_used)
        logic.advance_turn()
        with self.assertRaisesRegex(ValueError, "reaction already used"):
            actions.cast_spell(state, hero, "Shield", 1)
        restored = GameState.model_validate(state.model_dump(mode="json"))
        GameLogic(restored).advance_turn()
        actions.cast_spell(restored, hero, "Shield", 1)
        self.assertEqual(restored.characters[hero].spells.slots["1"].used, 2)


class SpellRegressionTests(unittest.TestCase):
    def setUp(self):
        self.state, self.hero, self.enemy = combat_fixture()
        self.service = AgentToolService(DummyRAGEngine(), MonsterStorage(), RuleCatalog())
        self.runner = DMGraphRunner(rag_engine=DummyRAGEngine(), tool_service=self.service, enable_model=False)
        self.addCleanup(self.runner.close)

    def cast(self, spell="Fire Bolt"):
        result = self.runner._execute_single_tool(self.state, "cast_spell", {"caster_ref": self.hero, "spell_name": spell}, ["cast_spell"])
        self.assertTrue(result.ok, result.error)
        return result.payload["cast_id"]

    def attack(self, cast_id, **args):
        return self.runner._execute_single_tool(self.state, "attack_target", {
            "attacker_ref": self.hero, "target_ref": self.enemy, "cast_id": cast_id, **args,
        }, ["attack_target"])

    def test_cast_then_attack_uses_spell_math_and_spends_action_once(self):
        cast_id = self.cast()
        with patch("game_logic.DiceRoller.roll_d20", return_value=(10, 15, "synthetic")) as d20, patch("game_logic.DiceRoller.roll", return_value=(4, "[4]")) as damage:
            result = self.attack(cast_id, attack_bonus=999, damage_expression="99d99")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(d20.call_args.args[0], 5)
        self.assertEqual(damage.call_args.args[0], "1d10")
        self.assertEqual(self.state.encounter.combatants[self.enemy].hp_current, 36)
        self.assertTrue(self.state.encounter.turn_action_used)
        before = self.state.model_dump(mode="json")
        self.assertFalse(self.attack(cast_id).ok)
        self.assertEqual(self.state.model_dump(mode="json"), before)

    def test_foreign_or_expired_cast_ids_are_rejected(self):
        cast_id = self.cast()
        foreign = self.runner._execute_single_tool(self.state, "attack_target", {
            "attacker_ref": self.enemy, "target_ref": self.hero, "cast_id": cast_id,
        }, ["attack_target"])
        self.assertFalse(foreign.ok)
        GameLogic(self.state).advance_turn()
        self.assertFalse(self.attack(cast_id).ok)

    def test_invalid_target_does_not_consume_cast(self):
        cast_id = self.cast()
        before = self.state.model_dump(mode="json")
        result = self.attack(cast_id, target_ref="missing")
        self.assertFalse(result.ok)
        self.assertEqual(self.state.model_dump(mode="json"), before)

    def test_cantrip_scaling_and_multiple_beams(self):
        character = self.state.characters[self.hero]
        character.level = 5
        profile = RuleCatalog().get_spell_attack_profile(character, "Fire Bolt")
        self.assertEqual(profile["damage_expression"], "2d10")
        character.class_name = "Warlock"
        cast_id = self.cast("Eldritch Blast")
        for remaining in (1, 0):
            with patch("game_logic.DiceRoller.roll_d20", return_value=(1, 1, "miss")):
                result = self.attack(cast_id)
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.payload["attacks_remaining"], remaining)
        self.assertFalse(self.attack(cast_id).ok)

    def test_local_cast_resolves_target_and_invalid_target_spends_nothing(self):
        actions = GameActionService()
        before = self.state.model_dump(mode="json")
        with self.assertRaises(ValueError):
            actions.cast_spell(self.state, self.hero, "Fire Bolt", target_ref="missing")
        self.assertEqual(self.state.model_dump(mode="json"), before)
        with patch("game_logic.DiceRoller.roll_d20", return_value=(10, 15, "hit")), patch("game_logic.DiceRoller.roll", return_value=(4, "[4]")):
            result = actions.cast_spell(self.state, self.hero, "Fire Bolt", target_ref=self.enemy)
        self.assertEqual(result["game_state"].encounter.combatants[self.enemy].hp_current, 36)
        self.assertEqual(self.state.pending_spell_attacks, [])

    def test_agent_guardrail_allows_off_turn_reaction_and_blocks_reuse(self):
        GameLogic(self.state).advance_turn()
        args = {"caster_ref": self.hero, "spell_name": "Shield", "slot_level": 1}
        self.assertTrue(self.runner._execute_single_tool(self.state, "cast_spell", args, ["cast_spell"]).ok)
        again = self.runner._execute_single_tool(self.state, "cast_spell", args, ["cast_spell"])
        self.assertFalse(again.ok)
        self.assertIn("reaction already used", again.error)

    def test_unresolved_spell_cannot_finalize_as_success(self):
        self.cast()
        initial = self.state.model_copy(deep=True)
        result = self.runner._finalize_turn({"game_state": self.state.model_dump(mode="json"),
                                            "initial_game_state": initial.model_dump(mode="json"),
                                            "user_input": "spell", "turn_status": "completed", "final_response": "done"})
        self.assertEqual(result["turn_status"], "failed")

    def test_real_graph_cast_attack_and_finalize(self):
        state = workflow_fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        hero = state.active_character_id
        state.characters[hero].class_name = "Wizard"
        state.characters[hero].spells.cantrips = ["Fire Bolt"]
        logic = GameLogic(state)
        encounter = logic.start_encounter(["Test Enemy"], enemy_hp=40)
        enemy = next(item.combatant_id for item in encounter.combatants.values() if item.side == "enemy")
        logic.set_initiative(hero, 20)
        logic.set_initiative(enemy, 10)

        class Model:
            def bind_tools(self, _tools):
                return self
            def invoke(self, messages):
                tools = [message for message in messages if isinstance(message, ToolMessage)]
                if not tools:
                    return AIMessage(content="", tool_calls=[{"id": "cast", "name": "cast_spell", "args": {"caster_ref": hero, "spell_name": "Fire Bolt"}}])
                if tools[-1].name == "cast_spell":
                    cast_id = json.loads(tools[-1].content)["cast_id"]
                    return AIMessage(content="", tool_calls=[{"id": "attack", "name": "attack_target", "args": {"attacker_ref": hero, "target_ref": enemy, "cast_id": cast_id}}])
                return AIMessage(content="火焰击中了敌人。")

        runner = DMGraphRunner(rag_engine=DummyRAGEngine(), tool_service=self.service, enable_model=True, api_key="synthetic", checkpoint_mode="memory")
        runner._model = Model()
        try:
            with patch("game_logic.DiceRoller.roll_d20", return_value=(10, 15, "hit")), patch("game_logic.DiceRoller.roll", return_value=(4, "[4]")):
                result = runner.run_turn(state, "我施放火焰箭攻击敌人。")
            self.assertEqual(result.turn_status, "completed", result.response)
            self.assertEqual(result.game_state.encounter.combatants[enemy].hp_current, 36)
            self.assertEqual(result.game_state.pending_spell_attacks, [])
        finally:
            runner.close()


class PublicProjectionTests(unittest.TestCase):
    def fixture(self):
        hidden = ToolResult(tool_name="dice.roll", summary="SECRET_ROLL_19", payload={"visibility": "hidden", "total": 19})
        public = ToolResult(tool_name="dice.roll", summary="public roll", payload={"visibility": "public", "total": 3})
        trace = TurnTrace(tool_results=[hidden, public])
        state = GameState(game_id="public-test", latest_tool_results=[hidden, public], turn_traces=[trace],
                          timeline=[SessionEvent(type="dice_rolled", summary=hidden.summary, payload=hidden.payload)],
                          chat_history=[ChatMessage(role="system", kind="tool_result", content=hidden.summary)])
        return state, TurnResult(response="narration", game_state=state, tool_results=[hidden, public], turn_trace=trace, history=state.chat_history)

    def test_public_turn_projection_removes_hidden_values_and_tool_history(self):
        state, result = self.fixture()
        original = state.model_dump(mode="json")
        payload = api._turn_result_payload(result)
        self.assertNotIn("SECRET_ROLL_19", json.dumps(payload))
        self.assertEqual([entry["payload"]["total"] for entry in payload["tool_results"]], [3])
        self.assertEqual(payload["history"], [])
        self.assertEqual(state.model_dump(mode="json"), original)

    def test_rest_game_and_traces_use_the_same_projection(self):
        from test_main_streaming import FakeStorage
        state, result = self.fixture()
        with patched_runtime(FakeAgent(result), FakeStorage(state)):
            client = TestClient(api.app)
            for path in ("/api/v1/games/public-test", "/api/v1/games/public-test/traces"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("SECRET_ROLL_19", response.text)

    def test_sse_serialization_and_optional_none_are_safe(self):
        _, result = self.fixture()
        event = api._sse_event("turn.completed", result.model_dump(mode="json"))
        self.assertNotIn("SECRET_ROLL_19", event)
        self.assertEqual(player_payload({"encounter": None, "values": [None]}), {"encounter": None, "values": [None]})


if __name__ == "__main__":
    unittest.main()
