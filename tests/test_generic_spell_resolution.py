"""共享法术协议：战斗外目标、数据驱动效果、失败待办与短规则反馈。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV', '1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE', 'memory')
from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from game_logic import GameLogic
from models import GameState, SpellSlot
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from roll_capture import capture_rolls
from scene_actors import register_actor
from resolution_protocol import update_failures
from spell_effects import apply_rule, end_concentration, advance_time
from spell_rules import declared_spells, rule_for
from test_combat_control import Script, call
from langchain_core.messages import AIMessage
import test_dm_graph_workflow as fixtures


class GenericSpellTests(unittest.TestCase):
    def setUp(self):
        self.state = fixtures.DMGraphWorkflowTests()._build_state(True)
        hero = self.state.get_active_char()
        hero.class_name = 'Bard'
        hero.stats.charisma = 16
        hero.spells.cantrips = ['交友术']
        hero.spells.prepared = ['魅惑人类', '塔莎狂笑术', '治愈真言']
        hero.spells.slots = {'1': SpellSlot(total=4)}
        self.hero = hero.character_id
        self.service = AgentToolService(fixtures.DummyRAGEngine(), MonsterStorage(), RuleCatalog())
        self.ids = []
        for name in ['持刀地精', '持弓地精']:
            result = self.service.register_scene_actor(self.state, name, '合成场景中的已知类人守卫',
                creature_type='humanoid', ability_scores=dict(strength=10, dexterity=14,
                    constitution=10, intelligence=10, wisdom=10, charisma=10), hp_max=20, ac=14)
            self.assertTrue(result.ok, result.error)
            self.ids.append(result.payload['actor']['combatant_id'])

    def cast(self, name, target, die=1):
        with patch('game_logic.random.randint', return_value=die), capture_rolls() as rolls:
            result = self.service.cast_spell(self.state, self.hero, name, target_ref=target)
        self.assertTrue(result.ok, result.error)
        return result, rolls.records

    def runner(self):
        runner = DMGraphRunner(fixtures.DummyRAGEngine(), tool_service=self.service,
            enable_model=True, checkpoint_mode='memory')
        self.addCleanup(runner.close)
        return runner

    def test_social_spells_roll_without_starting_combat_and_share_end_events(self):
        result, rolls = self.cast('交友术', self.ids[0])
        self.assertEqual(len(rolls), 1)
        self.assertEqual(rolls[0].dc, 13)
        self.assertEqual(self.state.scene_actors[self.ids[0]].status_effects, ['Charmed'])
        self.assertFalse(self.state.encounter and self.state.encounter.active)
        result, rolls = self.cast('魅惑人类', self.ids[1])
        self.assertEqual(len(rolls), 1)
        self.assertEqual(self.state.scene_actors[self.ids[0]].status_effects, [])
        self.assertEqual([effect.rule_id for effect in self.state.active_spell_effects], ['charm_person'])
        end_concentration(GameLogic(self.state), self.hero)
        self.assertEqual(len(self.state.active_spell_effects), 1)
        self.assertTrue(any(e['type'] == 'effect_ended' for e in result.payload['effect_events']))

    def test_npc_promotion_preserves_identity_hp_and_effects(self):
        self.cast('魅惑人类', self.ids[0])
        GameLogic(self.state).update_target_hp(self.ids[0], -3)
        encounter = GameLogic(self.state).start_encounter(['持刀地精', '持弓地精'])
        self.assertEqual(encounter.combatants[self.ids[0]].hp_current, 17)
        self.assertIn('Charmed', encounter.combatants[self.ids[0]].status_effects)
        self.assertNotIn(self.ids[0], self.state.scene_actors)

    def test_preflight_reports_sequence_conflict_without_any_state_or_roll_change(self):
        casts = [{'spell_name':'交友术', 'target_refs':[self.ids[0]]},
                 {'spell_name':'魅惑人类', 'target_refs':[self.ids[1]]}]
        before = self.state.model_dump(mode='json')
        with capture_rolls() as rolls:
            result = self.service.check_spell_sequence(self.state, self.hero, casts)
        self.assertTrue(result.ok)
        self.assertFalse(result.payload['valid'])
        self.assertIn('结束', result.payload['conflicts'][0])
        self.assertEqual(rolls.records, [])
        self.assertEqual(self.state.model_dump(mode='json'), before)
        reverse = self.service.check_spell_sequence(self.state, self.hero, list(reversed(casts)))
        self.assertTrue(reverse.payload['valid'])

    def test_unknown_targets_and_unsupported_effects_do_not_spend_resources(self):
        for name, target in [('魅惑人类', '未登记人物'), ('魅惑人类', '')]:
            before = self.state.model_dump(mode='json')
            result = self.service.cast_spell(self.state, self.hero, name, target_ref=target)
            self.assertFalse(result.ok)
            self.assertEqual(self.state.model_dump(mode='json'), before)
        self.state.get_active_char().spells.prepared.append('命令术')
        before = self.state.model_dump(mode='json')
        result = self.service.cast_spell(self.state, self.hero, '命令术', target_ref=self.ids[0])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_response['code'], 'rules_unavailable')
        self.assertEqual(self.state.model_dump(mode='json'), before)

    def test_arbitrary_rule_name_uses_same_save_condition_and_expiration_engine(self):
        rule = rule_for({'name':'合成霜印', 'mechanics':{'id':'synthetic_frost', 'save':'constitution',
            'duration':12, 'concentration':False, 'target_base':1,
            'effects':[{'kind':'conditions', 'values':['Restrained']}], 'repeat_saves':{}}})
        logic = GameLogic(self.state)
        with patch('game_logic.random.randint', return_value=1), capture_rolls() as rolls:
            apply_rule(logic, self.state.get_active_char(), '合成霜印', [self.ids[0]], 1, rule, 13, 3)
        self.assertEqual(len(rolls.records), 1)
        self.assertEqual(rolls.records[0].kind, 'save')
        self.assertEqual(self.state.scene_actors[self.ids[0]].status_effects, ['Restrained'])
        advance_time(logic, 12)
        self.assertEqual(self.state.scene_actors[self.ids[0]].status_effects, [])

    def test_automatic_success_has_explanation_without_fake_dice(self):
        self.cast('交友术', self.ids[0])
        result, rolls = self.cast('交友术', self.ids[0])
        self.assertEqual(rolls, [])
        self.assertTrue(any(e.get('automatic') and e.get('success') for e in result.payload['effect_events']))

    def test_charmed_actor_cannot_harm_source_and_failed_attack_is_atomic(self):
        self.cast('魅惑人类', self.ids[0])
        before = self.state.model_dump(mode='json')
        with self.assertRaises(ValueError):
            GameLogic(self.state).resolve_attack(self.ids[0], self.hero, 4, '1d4')
        self.assertEqual(self.state.model_dump(mode='json'), before)

    def test_unrelated_success_does_not_clear_failed_operation(self):
        args = {'caster_ref':self.hero, 'spell_name':'魅惑人类', 'target_ref':self.ids[0]}
        failures = update_failures(self.state, [], 'cast_spell', args, False, 'missing')
        self.assertEqual(update_failures(self.state, failures, 'roll_skill_check', {}, True, ''), failures)
        self.assertEqual(update_failures(self.state, failures, 'cast_spell', args, True, ''), [])
        runner = self.runner()
        result = runner._finalize_turn({'game_state':self.state.model_dump(mode='json'),
            'initial_game_state':self.state.model_dump(mode='json'), 'unresolved_operations':failures,
            'user_input':'施放魅惑人类', 'final_response':'它已经友好了。'})
        self.assertEqual(result['turn_status'], 'failed')

    def test_feedback_rolls_back_staged_effects_and_bypasses_length_editor(self):
        initial = self.state.model_copy(deep=True)
        initial.campaign.reply_min_chars = 1000
        self.cast('魅惑人类', self.ids[0])
        runner = self.runner()
        message = '本回合的动作已用完，请调整行动。'
        with patch.object(runner, '_rewrite_response_to_length', side_effect=AssertionError('不得扩写规则反馈')):
            result = runner._finalize_turn({'game_state':self.state.model_dump(mode='json'),
                'initial_game_state':initial.model_dump(mode='json'), 'user_input':'再次施法',
                'rules_feedback':{'message':message}, 'turn_status':'rules_feedback'})
        restored = GameState.model_validate(result['game_state'])
        self.assertEqual(restored.active_spell_effects, [])
        self.assertEqual(restored.get_active_char().spells.slots['1'].used, 0)
        self.assertEqual(result['final_response'], message)
        self.assertEqual(restored.chat_history[-1].narrative_mode, 'rules_feedback')

    def test_real_graph_tools_route_to_short_feedback(self):
        runner = self.runner()
        runner._model = Script([call('report_rule_conflict', message='这组施法不能同时保留效果，请调整顺序。')])
        with patch.object(runner, '_rewrite_response_to_length', side_effect=AssertionError('不得扩写')):
            result = runner.run_turn(self.state, '先施放交友术，再施放魅惑人类，同时维持它们。')
        self.assertEqual(result.turn_status, 'rules_feedback', result.response)
        self.assertEqual(result.game_state.get_active_char().spells.slots['1'].used, 0)

    def test_generic_cast_result_completes_graph_without_manual_save(self):
        runner = self.runner()
        runner._model = Script([call('cast_spell', caster_ref=self.hero, spell_name='魅惑人类', target_ref=self.ids[0]),
                                AIMessage(content='你施展魔法，地精抵抗失败，对你的态度缓和下来。')])
        with patch('game_logic.random.randint', return_value=1), capture_rolls() as rolls:
            result = runner.run_turn(self.state, '对持刀地精施放魅惑人类。')
        self.assertEqual(result.turn_status, 'completed', result.response)
        self.assertEqual(len(rolls.records), 1)
        self.assertEqual(len(result.game_state.active_spell_effects), 1)

    def test_english_spell_names_do_not_match_inside_words(self):
        class LocalLibrary:
            spells = {'test':[{'name':'援助术', 'nameEN':'Aid'}]}
        self.assertEqual(declared_spells({'turn_intent':{'intent_tags':['spell_action']},
            'user_input':'I said nothing'}, LocalLibrary()), [])

    def test_valid_multispell_sequence_executes_both_saves(self):
        runner = self.runner()
        casts = [{'spell_name':'魅惑人类', 'target_refs':[self.ids[1]]},
                 {'spell_name':'交友术', 'target_refs':[self.ids[0]]}]
        runner._model = Script([call('check_spell_sequence', caster_ref=self.hero, casts=casts),
            call('cast_spell', caster_ref=self.hero, spell_name='魅惑人类', target_ref=self.ids[1]),
            call('cast_spell', caster_ref=self.hero, spell_name='交友术', target_ref=self.ids[0]),
            AIMessage(content='两名地精都没有抵抗住魔法，你开始与它们交谈。')])
        with patch('game_logic.random.randint', return_value=1), capture_rolls() as rolls:
            result = runner.run_turn(self.state, '先对持弓地精施放魅惑人类，再对持刀地精施放交友术。')
        self.assertEqual(result.turn_status, 'completed', result.response)
        self.assertEqual(len(rolls.records), 2)
        self.assertEqual({e.rule_id for e in result.game_state.active_spell_effects}, {'friends','charm_person'})

    def test_modifier_data_changes_attack_math_and_expires(self):
        hero = self.state.get_active_char()
        hero.class_name = 'Wizard'
        hero.spells.prepared = ['Shield']
        hero.spells.cantrips = ['Blade Ward']
        self.cast('Shield', self.hero)
        with patch('game_logic.random.randint', return_value=10):
            result = GameLogic(self.state).resolve_attack(self.ids[0], self.hero, 4, '')
        self.assertEqual(result['target_ac'], hero.ac + 5)
        advance_time(GameLogic(self.state), 6)
        self.assertEqual(self.state.active_spell_effects, [])
        self.cast('Blade Ward', self.hero)
        with patch('game_logic.random.randint', side_effect=[3,10]), capture_rolls() as rolls:
            result = GameLogic(self.state).resolve_attack(self.ids[0], self.hero, 4, '')
        self.assertEqual(result['attack_total'], 11)
        self.assertEqual(len(rolls.records), 2)

    def test_second_target_failure_rolls_back_generic_cast(self):
        before = self.state.model_dump(mode='json')
        self.state.get_active_char().spells.slots['2'] = SpellSlot(total=1)
        before = self.state.model_dump(mode='json')
        with patch('game_logic.random.randint', side_effect=[1,RuntimeError('合成骰子故障')]):
            with self.assertRaises(RuntimeError):
                self.service.cast_spell(self.state, self.hero, '魅惑人类', slot_level=2, target_refs=self.ids)
        self.assertEqual(self.state.model_dump(mode='json'), before)

    def test_preflight_preserves_existing_effects_and_binds_actual_order(self):
        casts = [{'spell_name':'魅惑人类', 'target_refs':[self.ids[1]]},
                 {'spell_name':'交友术', 'target_refs':[self.ids[0]]}]
        check = self.service.check_spell_sequence(self.state, self.hero, casts)
        graph = {'game_state':self.state.model_dump(mode='json'), 'user_input':'施放魅惑人类，然后施放交友术',
            'turn_intent':{'intent_tags':['spell_action']}, 'tool_results':[check.tool_result.model_dump(mode='json')]}
        error = self.runner()._repair_tool_call_error(graph, 'cast_spell',
            {'caster_ref':self.hero, 'spell_name':'交友术', 'target_ref':self.ids[0]})
        self.assertIn('differs from the checked sequence', error)
        self.cast('交友术', self.ids[0])
        result = self.service.check_spell_sequence(self.state, self.hero, casts[:1])
        self.assertFalse(result.payload['valid'])


if __name__ == '__main__':
    unittest.main()
