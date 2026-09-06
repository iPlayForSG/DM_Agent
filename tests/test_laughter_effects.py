"""控制法术须通过实际豁免驱动状态与后续事件。"""
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ.setdefault('DM_AGENT_SKIP_DOTENV','1');os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE','memory')
from models import Character,SpellSlot,InventoryItem,GameState,MonsterTemplate
from game_logic import GameLogic
from agent_tools import AgentToolService
from action_service import GameActionService
from rules_catalog import RuleCatalog
from storage import MonsterStorage
from roll_capture import capture_rolls
from combat_status import combat_status_entries
from spell_effects import canonical_condition
from dm_graph import DMGraphRunner
from langchain_core.messages import AIMessage
import test_dm_graph_workflow as fixtures


class LaughterEffectTests(unittest.TestCase):
    def setUp(self):
        self.state=fixtures.DMGraphWorkflowTests()._build_state(True)
        hero=self.state.get_active_char();hero.class_name='Bard';hero.stats.charisma=16
        hero.spells.prepared=['塔莎狂笑术','英雄气概'];hero.spells.slots={'1':SpellSlot(total=4),'3':SpellSlot(total=2)}
        hero.inventory=[InventoryItem(name='Dagger',type='weapon')]
        self.hero=hero.character_id
        logic=GameLogic(self.state);enc=logic.start_encounter(['Goblin'],enemy_hp=20,enemy_ac=12)
        self.enemy=next(c.combatant_id for c in enc.combatants.values() if c.side=='enemy')
        for c in enc.combatants.values():logic.set_initiative(c.combatant_id,20 if c.side=='party' else 10)
        self.service=AgentToolService(fixtures.DummyRAGEngine(),MonsterStorage(),RuleCatalog())

    def cast(self,die=1,**kwargs):
        with patch('game_logic.random.randint',return_value=die),capture_rolls() as rolls:
            result=self.service.cast_spell(self.state,self.hero,'塔莎狂笑术',target_ref=self.enemy,**kwargs)
        self.assertTrue(result.ok,result.error)
        return result,rolls.records

    def conditions(self):return self.state.encounter.combatants[self.enemy].status_effects

    def test_initial_save_is_real_and_failure_applies_exact_conditions(self):
        before_inventory=self.state.characters[self.hero].inventory.copy()
        result,rolls=self.cast()
        self.assertEqual(len(rolls),1);self.assertEqual(rolls[0].kind,'save');self.assertEqual(rolls[0].dc,13)
        self.assertEqual(set(self.conditions()),{'Incapacitated','Prone'})
        self.assertEqual(len(self.state.active_spell_effects),1)
        self.assertEqual(self.state.characters[self.hero].spells.slots['1'].used,1)
        self.assertEqual(self.state.characters[self.hero].inventory,before_inventory)
        self.assertEqual(result.payload['effect_resolution'],'completed')

    def test_successful_initial_save_does_not_apply_effect_or_hold_empty_concentration(self):
        result,rolls=self.cast(20)
        self.assertTrue(rolls[0].success);self.assertEqual(self.conditions(),[])
        self.assertEqual(self.state.active_spell_effects,[])
        self.assertEqual(self.state.characters[self.hero].concentration_spell,'')
        self.assertEqual(result.payload['current_concentration_spell'],'')
        self.assertTrue(self.state.encounter.turn_action_used)

    def test_invalid_missing_duplicate_and_excess_targets_are_atomic(self):
        cases=[{}, {'target_ref':'missing'}, {'target_refs':[self.enemy,self.enemy]}, {'target_refs':[self.enemy,self.hero]}]
        for args in cases:
            with self.subTest(args=args):
                before=self.state.model_dump(mode='json')
                with capture_rolls() as rolls:
                    result=self.service.cast_spell(self.state,self.hero,'塔莎狂笑术',**args)
                self.assertFalse(result.ok);self.assertEqual(rolls.records,[])
                self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_upcast_resolves_each_distinct_target_once(self):
        logic=GameLogic(self.state)
        extra=[logic.add_enemy('Second'),logic.add_enemy('Third')]
        for c in extra:logic.set_initiative(c.combatant_id,5)
        with patch('game_logic.random.randint',side_effect=[1,20,1]),capture_rolls() as rolls:
            result=self.service.cast_spell(self.state,self.hero,'塔莎狂笑术',slot_level=3,target_refs=[self.enemy,*[c.combatant_id for c in extra]])
        self.assertTrue(result.ok,result.error);self.assertEqual(len(rolls.records),3)
        self.assertEqual(len(self.state.active_spell_effects),2)
        self.assertEqual(self.state.characters[self.hero].spells.slots['3'].used,1)

    def test_failed_multi_target_roll_does_not_commit_partial_spell(self):
        before=self.state.model_dump(mode='json')
        with patch('game_logic.random.randint',side_effect=[1,RuntimeError('synthetic dice failure')]),self.assertRaises(RuntimeError):
            self.service.cast_spell(self.state,self.hero,'塔莎狂笑术',slot_level=3,target_refs=[self.enemy,self.hero])
        self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_end_turn_save_occurs_even_though_target_cannot_act(self):
        self.cast()
        with patch('game_logic.random.randint',return_value=20),capture_rolls() as rolls:
            result=self.service.advance_turn(self.state)
        self.assertTrue(result.ok);self.assertEqual(len(rolls.records),1)
        self.assertEqual(self.state.encounter.get_current_combatant().linked_character_id,self.hero)
        self.assertEqual(self.state.encounter.round_number,2)
        self.assertEqual(self.conditions(),[])
        self.assertEqual(self.state.characters[self.hero].concentration_spell,'')
        self.assertTrue(any(e['type']=='turn_skipped' for e in result.payload['effect_events']))

    def test_failed_end_turn_save_keeps_effect(self):
        self.cast()
        with patch('game_logic.random.randint',return_value=1),capture_rolls() as rolls:
            self.service.advance_turn(self.state)
        self.assertEqual(len(rolls.records),1);self.assertEqual(len(self.state.active_spell_effects),1)
        self.assertIn('Incapacitated',self.conditions())
        self.assertEqual(self.state.encounter.get_current_combatant().linked_character_id,self.hero)

    def test_damage_triggers_advantage_save_even_when_temp_hp_absorbs_damage(self):
        self.cast();self.state.encounter.combatants[self.enemy].temp_hp=5
        with patch('game_logic.random.randint',side_effect=[1,20]),capture_rolls() as rolls:
            result=GameLogic(self.state).update_target_hp(self.enemy,-1)
        self.assertEqual(len(rolls.records),1);self.assertEqual(rolls.records[0].dice,[1,20]);self.assertEqual(rolls.records[0].roll_mode,'advantage')
        self.assertEqual(self.conditions(),[]);self.assertEqual(result['target'].hp_current,20)
        self.assertEqual(result['effect_events'][0]['trigger'],'受到伤害')

    def test_failed_damage_save_keeps_control_and_does_not_use_reaction(self):
        self.cast()
        with patch('game_logic.random.randint',return_value=1),capture_rolls() as rolls:
            GameLogic(self.state).update_target_hp(self.enemy,-1)
        self.assertEqual(len(rolls.records[0].dice),2)
        self.assertIn('Incapacitated',self.conditions());self.assertEqual(self.state.encounter.reactions_used,{})

    def test_zero_damage_does_not_trigger_a_save(self):
        self.cast()
        with capture_rolls() as rolls:GameLogic(self.state).update_target_hp(self.enemy,0)
        self.assertEqual(rolls.records,[])

    def test_caster_concentration_failure_cleans_target_effect(self):
        self.cast()
        with patch('game_logic.random.randint',return_value=1),capture_rolls() as rolls:
            result=GameLogic(self.state).update_target_hp(self.hero,-1)
        self.assertEqual(len(rolls.records),1);self.assertEqual(rolls.records[0].label,'constitution')
        self.assertTrue(result['concentration_check']['broken']);self.assertEqual(self.conditions(),[])
        self.assertEqual(self.state.active_spell_effects,[])

    def test_caster_incapacitated_or_dead_clears_effects_without_save(self):
        for mode in ['condition','hp']:
            with self.subTest(mode=mode):
                self.setUp();self.cast()
                with capture_rolls() as rolls:
                    if mode=='condition':GameLogic(self.state).add_status(self.hero,'Stunned')
                    else:GameLogic(self.state).update_target_hp(self.hero,-100)
                self.assertEqual(self.conditions(),[]);self.assertEqual(rolls.records,[])

    def test_target_death_cleans_effect_without_redundant_save(self):
        self.cast()
        with capture_rolls() as rolls:GameLogic(self.state).set_defeat_state(self.enemy,'dead')
        self.assertEqual(rolls.records,[]);self.assertEqual(self.state.active_spell_effects,[])
        self.assertIn('Dead',self.conditions())

    def test_replacing_concentration_ends_old_effect(self):
        self.cast();self.state.encounter.active=False
        result=self.service.cast_spell(self.state,self.hero,'英雄气概')
        self.assertTrue(result.ok,result.error);self.assertEqual(self.conditions(),[])
        self.assertEqual(self.state.active_spell_effects,[])
        self.assertEqual(self.state.characters[self.hero].concentration_spell,'英雄气概')

    def test_preexisting_same_condition_survives_spell_end(self):
        GameLogic(self.state).add_status(self.enemy,'Prone');self.cast()
        self.service.end_concentration(self.state,self.hero)
        self.assertEqual(self.conditions(),['Prone'])

    def test_manual_same_condition_added_later_survives_spell_end(self):
        self.cast();GameLogic(self.state).add_status(self.enemy,'Prone')
        self.service.end_concentration(self.state,self.hero)
        self.assertEqual(self.conditions(),['Prone'])

    def test_target_cannot_remove_managed_conditions_manually(self):
        self.cast();before=self.state.model_dump(mode='json')
        for status in ['Prone','倒地','Incapacitated','失能']:
            with self.assertRaises(ValueError):GameLogic(self.state).remove_status(self.enemy,status)
        self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_overlapping_sources_transfer_condition_ownership(self):
        self.cast();self.state.encounter.active=False
        second=Character(name='Second caster',class_name='Bard');second.spells.prepared=['塔莎狂笑术'];second.spells.slots={'1':SpellSlot(total=2)}
        self.state.characters[second.character_id]=second
        with patch('game_logic.random.randint',return_value=1):
            result=self.service.cast_spell(self.state,second.character_id,'塔莎狂笑术',target_ref=self.enemy)
        self.assertTrue(result.ok,result.error)
        self.service.end_concentration(self.state,self.hero);self.assertIn('Incapacitated',self.conditions())
        self.service.end_concentration(self.state,second.character_id);self.assertEqual(self.conditions(),[])

    def test_duration_expires_after_ten_rounds_without_erasing_saved_preferences(self):
        self.cast()
        with patch('game_logic.random.randint',return_value=1):
            for _ in range(10):self.service.advance_turn(self.state)
        self.assertEqual(self.state.rules_time_seconds,60);self.assertEqual(self.state.active_spell_effects,[])
        self.assertEqual(self.conditions(),[])

    def test_noncombat_elapsed_time_resolves_saves_and_expiry(self):
        self.cast();self.state.encounter.active=False
        with patch('game_logic.random.randint',return_value=1),capture_rolls() as rolls:
            result=self.service.advance_time(self.state,60,'等待一分钟')
        self.assertTrue(result.ok,result.error);self.assertEqual(len(rolls.records),9)
        self.assertEqual(self.state.active_spell_effects,[]);self.assertEqual(self.conditions(),[])

    def test_time_advance_cannot_bypass_active_initiative(self):
        self.cast();before=self.state.model_dump(mode='json')
        result=self.service.advance_time(self.state,60,'等待')
        self.assertFalse(result.ok);self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_serialization_keeps_effect_sources_and_save_dc(self):
        self.cast();restored=GameState.model_validate(self.state.model_dump(mode='json'))
        self.assertEqual(restored.active_spell_effects[0].save_dc,13)
        with patch('game_logic.random.randint',return_value=20):self.service.advance_turn(restored)
        self.assertEqual(restored.active_spell_effects,[])

    def test_old_saves_do_not_invent_effects_from_concentration_name(self):
        old=self.state.model_dump(mode='json');old.pop('active_spell_effects');old.pop('rules_time_seconds')
        old['characters'][self.hero]['concentration_spell']='塔莎狂笑术'
        restored=GameState.model_validate(old)
        self.assertEqual(restored.active_spell_effects,[])

    def test_local_action_path_uses_same_save_and_status_rules(self):
        with patch('game_logic.random.randint',return_value=1),capture_rolls() as rolls:
            result=GameActionService().cast_spell(self.state,self.hero,'塔莎狂笑术',target_ref=self.enemy)
        self.assertEqual(len(rolls.records),1);self.assertEqual(len(result['game_state'].active_spell_effects),1)
        self.assertIn('Incapacitated',self.conditions())

    def test_immunity_is_respected_without_faking_successful_save(self):
        template=MonsterTemplate(name='Immune target',condition_immunities=['Incapacitated','Prone'])
        self.state.monster_templates[template.monster_id]=template
        self.state.encounter.combatants[self.enemy].monster_template_id=template.monster_id
        _,rolls=self.cast();self.assertEqual(len(rolls),1)
        self.assertFalse(rolls[0].success);self.assertEqual(self.conditions(),[])

    def test_status_projection_shows_buffs_debuffs_concentration_and_source(self):
        self.cast();self.state.characters[self.hero].temp_hp=3
        self.state.characters[self.hero].inspiration=True
        target=combat_status_entries(self.state,self.enemy);caster=combat_status_entries(self.state,self.hero)
        self.assertTrue(any('失能' in e['summary'] and '倒地' in e['summary'] for e in target))
        self.assertIn('凯德',target[0]['source']);self.assertIn('受到伤害',target[0]['description'])
        self.assertTrue(any(e['kind']=='concentration' for e in caster));self.assertTrue(any(e['kind']=='buff' for e in caster))

    def test_real_graph_cannot_finish_without_spell_save(self):
        from test_combat_control import Script,call
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),tool_service=self.service,enable_model=True,checkpoint_mode='memory')
        self.addCleanup(runner.close)
        runner._model=Script([call('cast_spell',caster_ref=self.hero,spell_name='塔莎狂笑术',target_ref=self.enemy),call('advance_turn'),AIMessage(content='地精笑倒，回合末也没能挣脱。现在轮到你。')])
        with patch('game_logic.random.randint',return_value=1),capture_rolls() as rolls:
            result=runner.run_turn(self.state,'继续施放塔莎狂笑术，让地精失能。')
        self.assertEqual(result.turn_status,'completed',result.response)
        self.assertEqual(len(rolls.records),2)
        self.assertEqual(result.game_state.encounter.get_current_combatant().linked_character_id,self.hero)
        self.assertEqual(result.response.count('*骰点｜'),2)
        self.assertEqual(len(result.game_state.active_spell_effects),1)

    def test_missing_save_cannot_be_bypassed_with_prose(self):
        from test_combat_control import Script
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),tool_service=self.service,enable_model=True,checkpoint_mode='memory');self.addCleanup(runner.close)
        runner._model=Script([AIMessage(content='地精已经失能。'),AIMessage(content='地精已经失能。')])
        result=runner.run_turn(self.state,'施放塔莎狂笑术，让地精失能。')
        self.assertEqual(result.turn_status,'failed');self.assertEqual(result.game_state.active_spell_effects,[])

    def test_incapacitating_character_breaks_untracked_concentration_too(self):
        self.state.encounter.active=False
        target=Character(name='Concentrating ally',class_name='Bard',concentration_spell='英雄气概')
        self.state.characters[target.character_id]=target
        with patch('game_logic.random.randint',return_value=1):
            result=self.service.cast_spell(self.state,self.hero,'塔莎狂笑术',target_ref=target.character_id)
        self.assertTrue(result.ok,result.error)
        self.assertEqual(self.state.characters[target.character_id].concentration_spell,'')
        self.assertIn('Incapacitated',self.state.characters[target.character_id].status_effects)

    def test_rule_question_does_not_require_casting(self):
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),checkpoint_mode='memory');self.addCleanup(runner.close)
        self.assertFalse(runner._managed_spell_pending({'user_input':'塔莎狂笑术怎样施放？','turn_intent':{'turn_type':'rules_reference','suggested_tools':['lookup_rules']}}))

    def test_managed_saves_cannot_be_rolled_twice_through_generic_save_tools(self):
        self.cast();before=self.state.model_dump(mode='json')
        with capture_rolls() as rolls:
            result=self.service.roll_saving_throw(self.state,self.enemy,'wisdom',source_ref=self.hero,spell_name='塔莎狂笑术')
            self.assertFalse(result.ok)
            with self.assertRaises(ValueError):GameActionService().saving_throw(self.state,self.enemy,'wisdom',source_ref=self.hero,spell_name='塔莎狂笑术')
        self.assertEqual(rolls.records,[]);self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_negated_cast_does_not_force_a_spell(self):
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),checkpoint_mode='memory');self.addCleanup(runner.close)
        self.assertFalse(runner._managed_spell_pending({'user_input':'不施放塔莎狂笑术，我改用匕首。','turn_intent':{'turn_type':'action_resolution','suggested_tools':['cast_spell']}}))

    def test_failure_during_repeat_saves_rolls_back_the_whole_advance(self):
        second=GameLogic(self.state).add_enemy('Second');GameLogic(self.state).set_initiative(second.combatant_id,5)
        with patch('game_logic.random.randint',return_value=1):
            result=self.service.cast_spell(self.state,self.hero,'塔莎狂笑术',slot_level=3,target_refs=[self.enemy,second.combatant_id])
        self.assertTrue(result.ok)
        before=self.state.model_dump(mode='json')
        with patch('game_logic.random.randint',side_effect=[20,RuntimeError('synthetic failure')]),self.assertRaises(RuntimeError):
            self.service.advance_turn(self.state)
        self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_failure_during_damage_save_does_not_leave_partial_hp_change(self):
        self.cast();before=self.state.model_dump(mode='json')
        with patch('game_logic.random.randint',side_effect=RuntimeError('synthetic failure')),self.assertRaises(RuntimeError):
            GameLogic(self.state).update_target_hp(self.enemy,-2)
        self.assertEqual(self.state.model_dump(mode='json'),before)

    def test_nonlethal_damage_does_not_end_effect_as_if_target_died(self):
        self.cast()
        with patch('game_logic.random.randint',side_effect=[10,20,1,1]),capture_rolls() as rolls:
            result=GameLogic(self.state).resolve_attack(self.hero,self.enemy,4,'1d20',resolution_mode='nonlethal')
        self.assertEqual(result['target_defeat_state'],'unconscious')
        self.assertEqual(len(self.state.active_spell_effects),1)
        self.assertEqual(rolls.records[-1].roll_mode,'advantage')
        self.assertEqual(rolls.records[-1].kind,'save')

    def test_target_save_modifier_comes_from_its_authoritative_sheet(self):
        self.state.encounter.combatants[self.enemy].saving_throws['wisdom']=5
        _,rolls=self.cast(8)
        self.assertEqual(rolls[0].modifier,5);self.assertEqual(rolls[0].total,13)
        self.assertEqual(self.state.active_spell_effects,[])

    def test_api_cast_and_action_options_expose_effect_status(self):
        from fastapi.testclient import TestClient
        import main as api
        from test_main_streaming import FakeStorage,patched_runtime
        store=FakeStorage(self.state)
        with patch.object(api,'game_storage',store),TestClient(api.app) as client:
            with patch('game_logic.random.randint',return_value=1):
                response=client.post(f'/api/v1/games/{self.state.game_id}/actions/cast-spell',json={'caster_ref':self.hero,'spell_name':'塔莎狂笑术','target_ref':self.enemy})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['game_state']['active_spell_effects']),1)
            options=client.get(f'/api/v1/games/{self.state.game_id}/action-options').json()
            enemy=next(a for a in options['actors'] if a['ref']==self.enemy)
            self.assertTrue(any('感知 DC 13' in e['summary'] for e in enemy['status_entries']))

    def test_api_rejects_missing_target_without_changing_state(self):
        from fastapi.testclient import TestClient
        import main as api
        from test_main_streaming import FakeStorage
        store=FakeStorage(self.state);before=self.state.model_dump(mode='json')
        with patch.object(api,'game_storage',store),TestClient(api.app) as client:
            response=client.post(f'/api/v1/games/{self.state.game_id}/actions/cast-spell',json={'caster_ref':self.hero,'spell_name':'塔莎狂笑术'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(store.state.model_dump(mode='json'),before)

    def test_missing_spell_slots_fails_without_repeated_impossible_repairs(self):
        from test_combat_control import Script,call
        for slot in self.state.characters[self.hero].spells.slots.values():slot.used=slot.total
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),tool_service=self.service,enable_model=True,checkpoint_mode='memory');self.addCleanup(runner.close)
        model=Script([call('cast_spell',caster_ref=self.hero,spell_name='塔莎狂笑术',target_ref=self.enemy)])
        runner._model=model
        result=runner.run_turn(self.state,'施放塔莎狂笑术，让地精失能。')
        self.assertEqual(result.turn_status,'failed');self.assertEqual(model.calls,1)
        self.assertEqual(result.game_state.active_spell_effects,[])

    def test_player_spell_is_not_forced_during_initial_dm_turn(self):
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),checkpoint_mode='memory');self.addCleanup(runner.close)
        self.assertFalse(runner._managed_spell_pending({'user_input':'施放塔莎狂笑术','combat_flow':{'stop_at_player':True,'action_done':False},'turn_intent':{'intent_tags':['spell_action']}}))

    def test_legacy_concentration_record_is_not_presented_as_confirmed_control(self):
        self.state.characters[self.hero].concentration_spell='塔莎狂笑术'
        entries=combat_status_entries(self.state,self.hero)
        self.assertTrue(any(e['summary']=='尚无已确认的目标效果' for e in entries))
        self.assertEqual(combat_status_entries(self.state,self.enemy),[])

    def test_maintaining_concentration_does_not_force_recasting(self):
        runner=DMGraphRunner(fixtures.DummyRAGEngine(),checkpoint_mode='memory');self.addCleanup(runner.close)
        self.assertFalse(runner._managed_spell_pending({'user_input':'我继续维持塔莎狂笑术的专注。','turn_intent':{'intent_tags':['spell_action'],'suggested_tools':['cast_spell'],'turn_type':'action_resolution'}}))

    def test_atomic_cast_keeps_actor_selected_when_initiative_starts(self):
        self.state.encounter.turn_order_started=False
        self.state.encounter.current_combatant_id=None
        self.state.active_character_id=None
        result,_=self.cast()
        self.assertEqual(self.state.active_character_id,self.hero)
        self.assertEqual(result.state_patch['active_character_id'],self.hero)

    def test_skipped_incapacitated_turn_still_refreshes_own_reaction(self):
        self.state.encounter.reactions_used[self.enemy]=True
        self.cast()
        with patch('game_logic.random.randint',return_value=20):self.service.advance_turn(self.state)
        self.assertNotIn(self.enemy,self.state.encounter.reactions_used)
        self.assertEqual(self.conditions(),[])
