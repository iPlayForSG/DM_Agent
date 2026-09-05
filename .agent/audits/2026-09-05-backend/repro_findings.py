"""审计复现：断言当前缺陷确实出现，不是产品正确性通过门禁。"""
import asyncio
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import main as api
from action_service import GameActionService
from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import Character, ChatMessage, Combatant, EncounterState, GameState, InventoryItem, MonsterTemplate, SessionEvent, SpellSlot, ToolResult, TurnResult, TurnTrace
from rules_catalog import RuleCatalog
from storage import GameStorage, MonsterStorage
from test_dm_graph_workflow import DMGraphWorkflowTests, DummyRAGEngine, PlayerChoiceModel
from test_main_streaming import FakeStorage, patched_runtime


def record(issue, **values):
    print(json.dumps({"issue": issue, **values}, ensure_ascii=False), flush=True)


class CopyingStorage(FakeStorage):
    def load_game(self, game_id):
        return self.state.model_copy(deep=True) if self.state else None

    def save_game(self, game_id, state):
        super().save_game(game_id, state.model_copy(deep=True))


def combat_state():
    hero = Character(name="Audit Hero", class_name="Wizard", hp_current=20, hp_max=20,
                     inventory=[InventoryItem(name="Quarterstaff", type="weapon", damage_expression="1d6")])
    hero.spells.cantrips = ["Fire Bolt"]
    hero.spells.prepared = ["Shield"]
    hero.spells.slots = {"1": SpellSlot(total=2)}
    state = GameState(game_id="audit", characters={hero.character_id: hero}, scene="exploration")
    state.campaign.phase = "exploration"
    logic = GameLogic(state)
    encounter = logic.start_encounter(["Audit Enemy"], enemy_hp=20)
    enemy = next(c for c in encounter.combatants.values() if c.side == "enemy")
    logic.set_initiative(hero.character_id, 20)
    logic.set_initiative(enemy.combatant_id, 10)
    return state, hero.character_id, enemy.combatant_id


class AuditReproductions(unittest.TestCase):
    def test_f01_late_turn_overwrites_completed_settings_write(self):
        state = GameState(game_id="audit", scene="exploration")
        storage = CopyingStorage(state)
        started, release = threading.Event(), threading.Event()

        class Agent:
            async def run_turn(self, state, message):
                started.set()
                await asyncio.to_thread(release.wait, 5)
                state.turn_number += 1
                state.chat_history.extend([ChatMessage(role="user", content=message), ChatMessage(role="assistant", content="done")])
                return TurnResult(response="done", game_state=state)

        async def scenario():
            task = asyncio.create_task(api.run_turn("audit", api.ChatRequest(message="wait")))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                settings = await api.update_game_reply_length("audit", api.ReplyLengthSettingsRequest(min_chars=200, max_chars=400))
                self.assertEqual(settings["game_state"].campaign.reply_min_chars, 200)
            finally:
                release.set()
            await task

        with patched_runtime(Agent(), storage):
            asyncio.run(scenario())
        self.assertEqual(storage.state.campaign.reply_min_chars, 0)
        record("F01", settings_saved=200, after_turn=storage.state.campaign.reply_min_chars)

    def test_f02_serialization_failure_truncates_previous_save(self):
        storage = GameStorage()
        state = GameState(game_id="audit-write", title="previous valid save")
        storage.save_game(state.game_id, state)
        path = Path(storage._get_path(state.game_id))
        original_size = path.stat().st_size
        with patch.object(GameState, "model_dump_json", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                storage.save_game(state.game_id, state)
        self.assertEqual(path.read_bytes(), b"")
        record("F02", previous_bytes=original_size, remaining_bytes=path.stat().st_size)

    def test_f03_repeated_template_spawn_overwrites_injured_monster(self):
        state = GameState(game_id="audit-spawn")
        logic = GameLogic(state)
        template = MonsterTemplate(name="Audit Goblin", hp_max=10)
        first = logic.add_monster_from_template(template)[0]
        first.hp_current = 2
        second = logic.add_monster_from_template(template)[0]
        self.assertEqual(first.combatant_id, second.combatant_id)
        self.assertEqual(len(state.encounter.combatants), 1)
        self.assertEqual(state.encounter.combatants[first.combatant_id].hp_current, 10)
        record("F03", expected_count=2, actual_count=1, old_hp=2, overwritten_hp=10)

    def test_f04_spell_attack_cannot_follow_cast_spell(self):
        state, hero, enemy = combat_state()
        service = AgentToolService(DummyRAGEngine(), MonsterStorage(), RuleCatalog())
        runner = DMGraphRunner(rag_engine=DummyRAGEngine(), tool_service=service, enable_model=False)
        try:
            cast = runner._execute_single_tool(state, "cast_spell", {"caster_ref": hero, "spell_name": "Fire Bolt"}, ["cast_spell"])
            self.assertTrue(cast.ok, cast.error)
            attack = runner._execute_single_tool(state, "attack_target", {"attacker_ref": hero, "target_ref": enemy, "attack_name": "Fire Bolt", "attack_bonus": 5, "damage_expression": "1d10"}, ["attack_target"])
            self.assertFalse(attack.ok)
            self.assertIn("action already used", attack.error)
            # 即使人为释放槽位用于隔离第二个原因，攻击解析仍只接受角色卡武器。
            GameLogic(state)._reset_turn_action_state()
            with self.assertRaisesRegex(ValueError, "Weapon attack is not present"):
                service.rules_catalog.resolve_character_attack_profile(state.characters[hero], attack_name="Fire Bolt")
            record("F04", cast_ok=True, spell_attack_ok=False, target_hp=state.encounter.combatants[enemy].hp_current)
        finally:
            runner.close()

    def test_f05_hidden_roll_survives_public_turn_payload(self):
        hidden = ToolResult(tool_name="dice.roll", summary="Hidden roll 19", payload={"visibility":"hidden","total":19})
        state = GameState(game_id="audit-hidden", latest_tool_results=[hidden])
        trace = TurnTrace(tool_results=[hidden])
        state.turn_traces = [trace]
        result = TurnResult(response="public narration", game_state=state, tool_results=[hidden], turn_trace=trace)
        self.assertFalse(any(name == "tool.completed" for name,_ in api._turn_detail_event_payloads(result,"audit-hidden","start")))
        public = api._turn_result_payload(result)
        self.assertEqual(public["tool_results"][0]["payload"]["total"],19)
        self.assertEqual(public["game_state"]["turn_traces"][0]["tool_results"][0]["payload"]["total"],19)
        record("F05", filtered_detail_event=True, public_turn_contains_hidden_roll=True)

    def test_f06_damage_ignores_temporary_hit_points(self):
        state, hero, enemy = combat_state()
        character = state.characters[hero]
        character.hp_current = 10
        character.temp_hp = 5
        GameLogic(state).update_target_hp(hero, -3)
        self.assertEqual((character.hp_current,character.temp_hp),(7,5))
        record("F06", expected_hp=10,expected_temp_hp=2,actual_hp=7,actual_temp_hp=5)

    def test_f07_off_turn_reaction_is_rejected(self):
        state, hero, enemy = combat_state()
        GameLogic(state).advance_turn()
        self.assertEqual(state.encounter.current_combatant_id,enemy)
        with self.assertRaisesRegex(ValueError,"turn"):
            GameActionService().cast_spell(state,hero,"Shield",1)
        record("F07", enemy_turn=True,shield_rejected=True)

    def test_f08_zero_initiative_sorts_below_negative(self):
        state = GameState(game_id="audit-initiative")
        zero = Combatant(name="Zero",initiative=0)
        negative = Combatant(name="Negative",initiative=-1)
        state.encounter = EncounterState(combatants={zero.combatant_id:zero,negative.combatant_id:negative},initiative_order=[zero.combatant_id,negative.combatant_id])
        GameLogic(state)._refresh_initiative_order()
        actual = [state.encounter.combatants[key].initiative for key in state.encounter.initiative_order]
        self.assertEqual(actual,[-1,0])
        record("F08",expected_order=[0,-1],actual_order=actual)

    def test_f09_setting_initiative_resets_used_action_in_round_one(self):
        state, hero, enemy = combat_state()
        logic=GameLogic(state)
        logic.mark_current_action_used("attack_target")
        self.assertTrue(state.encounter.turn_action_used)
        logic.set_initiative(enemy,10)
        self.assertFalse(state.encounter.turn_action_used)
        record("F09", same_initiative_reapplied=True,action_used_after=False)

    def test_f10_incapacitated_status_does_not_stop_actions_or_concentration(self):
        state, hero, enemy = combat_state()
        character=state.characters[hero]
        character.concentration_spell="Bless"
        logic=GameLogic(state)
        logic.add_status(hero,"Incapacitated")
        logic.require_current_actor(hero)
        logic.require_turn_action_available("attack_target")
        with patch("game_logic.DiceRoller.roll_d20", return_value=(10,20,"synthetic hit")), patch("game_logic.DiceRoller.roll",return_value=(1,"synthetic damage")):
            GameActionService().attack_target(state,hero,enemy,attack_name="Quarterstaff")
        self.assertEqual(state.encounter.combatants[enemy].hp_current,19)
        self.assertEqual(character.concentration_spell,"Bless")
        self.assertTrue(logic._combatant_can_take_turn(logic.get_combatant(hero)))
        record("F10",incapacitated=True,concentration_retained=True,attack_succeeded=True)

    def test_f11_rewrite_failure_prunes_live_branch_snapshots(self):
        state=GameState(game_id="audit-rewrite",chat_history=[ChatMessage(role="user",content="old"),ChatMessage(role="assistant",content="old response")])
        storage=CopyingStorage(state)
        storage.save_rewind_snapshot(state.game_id,0,GameState(game_id=state.game_id))
        storage.save_rewind_snapshot(state.game_id,1,state)

        class Agent:
            async def run_turn(self,state,message):
                raise RuntimeError("synthetic transport failure")

        with patched_runtime(Agent(),storage):
            with self.assertRaises(api.HTTPException):
                asyncio.run(api.rewrite_game_message(state.game_id,0,api.RewriteMessageRequest(message="new")))
        self.assertEqual(storage.state.chat_history[1].content,"old response")
        self.assertIsNone(storage.load_rewind_snapshot(state.game_id,1))
        record("F11",old_branch_retained=True,old_assistant_snapshot_lost=True)

    def test_f12_local_item_use_during_interrupt_is_lost_on_resume(self):
        state=DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        hero=state.active_character_id
        state.characters[hero].inventory.append(InventoryItem(name="Audit token",quantity=2))
        runner=DMGraphRunner(rag_engine=DummyRAGEngine(),tool_service=object(),enable_model=True,api_key="synthetic-test-value",checkpoint_mode="memory")
        runner._model=PlayerChoiceModel()

        class Agent:
            async def resume_turn(self,state,message):
                return runner.resume_turn(state,message)

        try:
            paused=runner.run_turn(state,"我不知道该不该接过王冠。")
            self.assertEqual(paused.turn_status,"input_required")
            storage=CopyingStorage(paused.game_state)
            with patched_runtime(Agent(),storage):
                used=asyncio.run(api.use_item_action(state.game_id,api.UseItemActionRequest(user_ref=hero,item_name="Audit token",quantity=1)))
                quantity_after_use=next(i.quantity for i in used["game_state"].characters[hero].inventory if i.name=="Audit token")
                self.assertEqual(quantity_after_use,1)
                self.assertIsNotNone(used["game_state"].pending_turn)
                resumed=asyncio.run(api.run_turn(state.game_id,api.ChatRequest(message="交给自由议会")))
            self.assertEqual(resumed.turn_status,"completed")
            quantity_after_resume=next(i.quantity for i in storage.state.characters[hero].inventory if i.name=="Audit token")
            self.assertEqual(quantity_after_resume,2)
            record("F12",quantity_after_saved_use=1,quantity_after_resume=2)
        finally:
            runner.close()
