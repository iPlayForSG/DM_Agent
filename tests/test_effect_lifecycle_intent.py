"""已存在法术的等待/维持不触发重施；状态及反馈来自实际效果。"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from spell_rules import declared_spells
from game_logic import GameLogic
from combat_status import combat_status_entries
from dm_graph import DMGraphRunner
from roll_capture import capture_rolls
from langchain_core.messages import AIMessage
from test_combat_control import Script,call
import test_generic_spell_resolution as spell_fixtures

USER_ACTION='那么，默默等待交友术的60秒结束，同时悄悄往后退一步，让持弓的地精将自己护在身前，只等交友术结束就主动发难，将手中的弯刀扔向持刀地精。'
FALSE_FEEDBACK='当前法术状态需要先完成规则层面的核验，才能继续裁定等待结束、目标反应与投掷弯刀的行动。请先确认或重新声明需要维持的法术效果。'


class EffectLifecycleIntentTests(unittest.TestCase):
    def setUp(self):
        fixture=spell_fixtures.GenericSpellTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.state,self.service,self.ids,self.hero=fixture.state,fixture.service,fixture.ids,fixture.hero
        fixture.cast('魅惑人类',self.ids[1]);fixture.cast('交友术',self.ids[0])
        for slot in self.state.get_active_char().spells.slots.values():slot.used=slot.total
        self.library=self.service.library

    def declared(self,text):
        return declared_spells({'user_input':text,'turn_intent':{'intent_tags':['spell_action'],
            'suggested_tools':['cast_spell'],'turn_type':'action_resolution'}},self.library)

    def test_effect_lifecycle_mentions_are_not_new_casts(self):
        for text in [USER_ACTION,'等待交友术结束。','我专注于交友术。','继续维持塔莎狂笑术的专注。',
                     '等交友术60秒。','结束交友术的专注。','交友术还在吗？','检查魅惑类人的剩余持续时间。',
                     'Wait for Friends to expire, then step back.','Maintain concentration on Friends.']:
            with self.subTest(text=text):self.assertEqual(self.declared(text),[])

    def test_mixed_casts_and_recasts_still_require_resolution(self):
        for text,expected in [('维持交友术，同时施放魅惑人类。',['魅惑类人']),
            ('等待交友术结束后再次施放交友术。',['交友术']),('继续释放塔莎狂笑术，让它失能。',['塔莎狂笑术']),
            ('对地精用交友术。',['交友术']),('交友术，目标持刀地精。',['交友术']),
            ('取消交友术，然后施放魅惑类人。',['魅惑类人']),('不要施放交友术。',[])]:
            with self.subTest(text=text):self.assertEqual(self.declared(text),expected)

    def test_authoritative_summary_has_real_triggers_and_concentration(self):
        summary=GameLogic(self.state).get_state_summary()
        self.assertIn('Concentration: 交友术',summary)
        self.assertIn('concentration=not required',summary)
        self.assertIn('remaining 60s',summary)
        self.assertIn('repeat saves: none',summary)
        self.assertNotIn('Turn-end save; damage save has advantage',summary)
        self.state.active_spell_effects[0].save_name=''
        self.assertIn('no initial saving throw required',GameLogic(self.state).get_state_summary())

    def test_wait_expires_only_friends_without_new_saves_or_slot_spending(self):
        slots=deepcopy(self.state.get_active_char().spells.slots)
        entries=combat_status_entries(self.state,self.hero)
        concentration=next(e for e in entries if e['kind']=='concentration')
        self.assertIn('持刀地精',concentration['source']);self.assertIn('60',concentration['source'])
        with capture_rolls() as rolls:
            result=self.service.advance_time(self.state,60,'按玩家声明等待一分钟')
        self.assertTrue(result.ok,result.error)
        self.assertEqual(rolls.records,[])
        self.assertEqual(self.state.get_active_char().spells.slots,slots)
        self.assertEqual(self.state.get_active_char().concentration_spell,'')
        self.assertEqual([e.rule_id for e in self.state.active_spell_effects],['charm_person'])
        self.assertEqual(self.state.active_spell_effects[0].expires_at_seconds-self.state.rules_time_seconds,3540)
        self.assertFalse(any(e['kind']=='concentration' for e in combat_status_entries(self.state,self.hero)))

    def test_internal_verification_cannot_be_reported_as_player_rule_conflict(self):
        before=self.state.model_dump(mode='json')
        result=self.service.report_rule_conflict(self.state,FALSE_FEEDBACK)
        self.assertFalse(result.ok)
        self.assertEqual(self.state.model_dump(mode='json'),before)
        self.assertTrue(self.service.report_rule_conflict(self.state,'同一回合的动作已经用完，请选择合法的附赠动作或结束回合。').ok)

    def test_full_graph_recovers_from_vague_feedback_and_resolves_wait(self):
        runner=DMGraphRunner(self.service.rag_engine,tool_service=self.service,enable_model=True,checkpoint_mode='memory')
        self.addCleanup(runner.close)
        runner._model=Script([call('report_rule_conflict',message=FALSE_FEEDBACK),
            call('advance_time',seconds=60,reason='玩家明确等待交友术结束'),
            AIMessage(content='一分钟过去，持刀地精身上的交友术结束；持弓地精的魅惑类人仍在持续。你后退一步。')])
        with capture_rolls() as rolls:
            result=runner.run_turn(self.state,'默默等待交友术的60秒结束，然后后退一步。')
        self.assertEqual(result.turn_status,'completed',result.response)
        self.assertEqual(result.game_state.rules_time_seconds,60)
        self.assertEqual(rolls.records,[])
        self.assertEqual([e.rule_id for e in result.game_state.active_spell_effects],['charm_person'])
        self.assertNotIn('magic.cast_spell',[r.tool_name for r in result.tool_results])


if __name__=='__main__':unittest.main()
