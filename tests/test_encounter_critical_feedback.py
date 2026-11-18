import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from action_service import GameActionService
from agent_tools import AgentToolService
from game_logic import GameLogic
from models import Character, ChatMessage, GameState, HidingState, InventoryItem, Spellbook, Stats
from roll_capture import capture_rolls, settle_rolls
from rules_catalog import RuleCatalog


class EncounterCriticalFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.rules = RuleCatalog()
        self.service = AgentToolService(None, None, self.rules)

    def state(self, npc_turn=False):
        hero = Character(name="测试角色", class_name="Wizard", hp_max=30, hp_current=30,
                         stats=Stats(dexterity=14, intelligence=14),
                         inventory=[InventoryItem(name="Dagger", type="weapon")],
                         spells=Spellbook(cantrips=["Fire Bolt"]))
        state = GameState(game_id="critical-fixture", characters={hero.character_id: hero})
        logic = GameLogic(state)
        encounter = logic.start_encounter(["持刀地精"], enemy_hp=10, enemy_ac=10)
        enemy = next(c for c in encounter.combatants.values() if c.side == "enemy")
        party = next(c for c in encounter.combatants.values() if c.side == "party")
        logic.set_initiative(party.combatant_id, 10 if npc_turn else 20)
        logic.set_initiative(enemy.combatant_id, 20 if npc_turn else 10)
        return state, hero.character_id, enemy.combatant_id

    def test_solo_level_one_can_start_with_both_enemies_and_surprise_only_affects_initiative(self):
        hero = Character(name="测试角色", level=1, hp_max=9, hp_current=9,
                         hiding=HidingState(stealth_total=15, cover="total", reason="已确认的遮蔽"))
        state = GameState(characters={hero.character_id: hero})
        with capture_rolls() as rolls, patch("game_logic.random.randint", side_effect=[18, 12, 16, 4, 10]):
            result = self.service.start_encounter(state, ["持刀地精", "持弓地精"], enemy_hp=7, enemy_ac=12,
                surprised_refs=["持刀地精"], surprise_reason="持刀地精尚未察觉伏击者")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.payload["combatant_count"], 3)
        self.assertEqual(set(result.payload["enemy_names"]), {"持刀地精", "持弓地精"})
        self.assertTrue(result.payload["balance_advice"])
        modes = {record.actor: record.roll_mode for record in rolls.records}
        self.assertEqual(modes, {"测试角色": "advantage", "持刀地精": "disadvantage", "持弓地精": "normal"})
        logic = GameLogic(state)
        visited = []
        for _ in range(3):
            current = state.encounter.get_current_combatant()
            visited.append(current.name)
            logic.require_current_actor(current.combatant_id)
            self.assertFalse(state.encounter.turn_action_used)
            logic.advance_turn()
        self.assertEqual(set(visited), {"测试角色", "持刀地精", "持弓地精"})
        self.assertEqual(state.encounter.round_number, 2)

    def test_invalid_surprise_participant_still_fails_without_mutation(self):
        hero = Character(name="测试角色")
        state = GameState(characters={hero.character_id: hero})
        before = state.model_dump(mode="json")
        with patch("game_logic.random.randint") as rng:
            result = self.service.start_encounter(state, ["持刀地精", "持弓地精"], enemy_hp=7, enemy_ac=12,
                surprised_refs=["不存在的敌人"], surprise_reason="合成测试")
        self.assertFalse(result.ok)
        self.assertEqual(state.model_dump(mode="json"), before)
        rng.assert_not_called()

    def test_long_names_and_reinforcements_have_distinct_persistent_instance_ids(self):
        hero = Character(name="测试角色")
        state = GameState(characters={hero.character_id: hero})
        logic = GameLogic(state)
        encounter = logic.start_encounter(["持刀地精", "持弓地精"], enemy_hp=7)
        knife = next(c for c in encounter.combatants.values() if c.name == "持刀地精")
        knife.hp_current = 3
        left = logic.add_enemy("SharedVeryLongGuardName" * 4 + "A")
        right = logic.add_enemy("SharedVeryLongGuardName" * 4 + "B")
        self.assertNotEqual(left.combatant_id, right.combatant_id)
        self.assertEqual(len(encounter.combatants), 5)
        self.assertEqual(encounter.combatants[knife.combatant_id].hp_current, 3)
        old_id = left.combatant_id
        logic.remove_combatant(old_id)
        replacement = logic.add_enemy(left.name)
        self.assertNotEqual(replacement.combatant_id, old_id)
        restored = GameState.model_validate_json(state.model_dump_json())
        self.assertEqual(set(restored.encounter.combatants), set(encounter.combatants))
        self.assertEqual(restored.encounter.combatants[knife.combatant_id].hp_current, 3)

    def test_npc_natural_twenty_keeps_one_damage_application_and_publishes_critical(self):
        state, hero, enemy = self.state(npc_turn=True)
        with capture_rolls() as rolls, patch("game_logic.random.randint", side_effect=[20, 4, 1]), patch("roll_capture.emit_turn_stream_event") as stream:
            result = self.service.attack_target(state, enemy, hero, attack_bonus=4, damage_expression="1d4+2", damage_type="piercing")
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.payload["critical"])
        self.assertEqual(result.payload["natural"], 20)
        self.assertEqual(result.payload["damage_roll"], "2d4+2")
        self.assertEqual(result.payload["damage_total"], 7)
        self.assertEqual(state.characters[hero].hp_current, 23)
        self.assertIn("自然20 · 重击", result.tool_result.summary)
        self.assertIn("伤害 7（2d4+2）", result.tool_result.summary)
        self.assertEqual(rolls.records[0].natural, 20)
        self.assertTrue(rolls.records[0].critical)
        self.assertTrue(rolls.records[1].critical)
        self.assertEqual(rolls.records[1].dice, [4, 1])
        self.assertEqual(rolls.records[1].modifier, 2)
        events = [call.args[1]["roll_records"][0] for call in stream.call_args_list]
        self.assertTrue(any(event["kind"] == "attack" and event.get("critical") and event.get("natural") == 20 for event in events))
        saved = ChatMessage(role="assistant", content=result.tool_result.summary,
                            roll_records=settle_rolls(rolls.records, "completed"), roll_records_recorded=True)
        restored = ChatMessage.model_validate_json(saved.model_dump_json())
        self.assertTrue(restored.roll_records[0].critical)
        self.assertEqual(restored.roll_records[0].settlement, "committed")

    def test_local_weapon_and_spell_attack_summaries_show_critical(self):
        for spell_attack in (False, True):
            for use_local in (False, True):
                with self.subTest(spell_attack=spell_attack, use_local=use_local):
                    state, hero, enemy = self.state()
                    cast_id = ""
                    if spell_attack:
                        from spell_resolution import cast_spell
                        payload, _ = cast_spell(state, self.rules, hero, "Fire Bolt")
                        cast_id = payload["cast_id"]
                    with capture_rolls() as rolls, patch("game_logic.random.randint", side_effect=[20, 3, 4]):
                        if use_local:
                            result = GameActionService().attack_target(state, hero, enemy, attack_name="Dagger", cast_id=cast_id)
                            summary = result["summary"]
                        else:
                            result = self.service.attack_target(state, hero, enemy, attack_name="Dagger", cast_id=cast_id)
                            self.assertTrue(result.ok, result.error)
                            summary = result.tool_result.summary
                    self.assertIn("自然20 · 重击", summary)
                    self.assertTrue(rolls.records[0].critical)
                    self.assertEqual(rolls.records[1].expression, "2d10" if spell_attack else "2d4+2")

    def test_natural_one_auto_misses_and_skill_twenty_is_not_critical(self):
        state, hero, enemy = self.state()
        with capture_rolls() as rolls, patch("game_logic.random.randint", return_value=1):
            result = GameLogic(state).resolve_attack(hero, enemy, 100, "1d4+2")
        self.assertFalse(result["hit"])
        self.assertFalse(rolls.records[0].critical)
        self.assertEqual(rolls.records[0].natural, 1)
        self.assertEqual(len(rolls.records), 1)
        with capture_rolls() as rolls, patch("game_logic.random.randint", return_value=20):
            GameLogic(state).roll_skill_check(hero, "Arcana", dc=30, modifier=0)
        self.assertFalse(rolls.records[0].success)
        self.assertIsNone(rolls.records[0].critical)


if __name__ == "__main__":
    unittest.main()
