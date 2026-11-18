"""库存钱币唯一来源：旧存档迁移、找零、付款失败和回合事务。"""
import os,sys,json,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend')]
os.environ.setdefault('DM_AGENT_SKIP_DOTENV','1')
os.environ.setdefault('LANGGRAPH_CHECKPOINT_MODE','memory')
from models import Character,GameState,InventoryItem,PendingTurnState
from money import balance_cp,split_inventory,adjust
from game_logic import GameLogic
from rules_catalog import RuleCatalog
from inventory_narration import inventory_annotations
from test_combat_control import Script,call
import test_generic_spell_resolution as fixtures
from langchain_core.messages import AIMessage


class InventoryCurrencyTests(unittest.TestCase):
    def setUp(self):
        self.hero=Character(name='合成钱币角色',gold_gp=19,inventory=[InventoryItem(name='silver pieces',quantity=6,type='currency'),InventoryItem(name='古银币',quantity=1)])
        self.state=GameState(game_id='currency-test',characters={self.hero.character_id:self.hero},active_character_id=self.hero.character_id,scene='exploration')

    def test_legacy_migration_is_idempotent_and_keeps_collectibles(self):
        data=self.hero.model_dump(mode='json')
        self.assertNotIn('gold_gp',data)
        self.assertEqual(data['currency_inventory_version'],1)
        self.assertEqual(balance_cp(self.hero),1960)
        self.assertEqual(split_inventory(self.hero.inventory)[1]['sp'],6)
        for _ in range(4):data=Character.model_validate(data).model_dump(mode='json')
        self.assertEqual(balance_cp(Character.model_validate(data)),1960)
        self.assertIn('古银币',[item['name'] for item in data['inventory']])
        data['gold_gp']=999
        self.assertEqual(balance_cp(Character.model_validate(data)),1960)
        for field in ('gp','gold'):
            self.assertEqual(balance_cp(Character.model_validate({'name':'old','inventory':[] ,field:3})),300)

    def test_all_denominations_income_and_exact_spending(self):
        before=balance_cp(self.hero)
        for unit,value in [('cp',1),('SP',10),('银金币',50),('gold pieces',100),('pp',1000)]:
            receipt=GameLogic(self.state).adjust_currency(self.hero.character_id,2,unit,'合成奖励')
            self.assertEqual(balance_cp(self.hero),before+2*value)
            receipt=GameLogic(self.state).adjust_currency(self.hero.character_id,-2,unit,'合成付款')
            self.assertEqual(balance_cp(self.hero),before)
            self.assertFalse(receipt['change_made'])

    def test_change_and_insufficient_funds_are_atomic(self):
        result=adjust(self.hero,-7,'sp')
        self.assertTrue(result['change_made'])
        self.assertEqual(balance_cp(self.hero),1890)
        self.assertEqual(split_inventory(self.hero.inventory)[1],{'cp':0,'sp':9,'ep':0,'gp':18,'pp':0})
        before=self.hero.model_dump(mode='json')
        for amount,unit in [(-2000,'cp'),(-1,'diamond'),(True,'gp'),(1.5,'sp'),(0,'sp')]:
            with self.assertRaises(ValueError):adjust(self.hero,amount,unit)
            self.assertEqual(self.hero.model_dump(mode='json'),before)

    def test_empty_balance_has_no_zero_or_negative_coin_rows(self):
        adjust(self.hero,-1960,'cp')
        self.assertEqual(balance_cp(self.hero),0)
        self.assertEqual([i.name for i in self.hero.inventory],['古银币'])

    def test_add_item_aliases_join_the_same_money_stack(self):
        GameLogic(self.state).add_inventory_item(self.hero.character_id,'SP',3)
        GameLogic(self.state).add_inventory_item(self.hero.character_id,'银币',2,item_type='currency')
        self.assertEqual(split_inventory(self.hero.inventory)[1]['sp'],11)
        self.assertEqual(sum(i.name=='银币' for i in self.hero.inventory),1)
        before=self.hero.model_dump(mode='json')
        with self.assertRaises(ValueError):GameLogic(self.state).add_inventory_item(self.hero.character_id,'金币',-1)
        self.assertEqual(self.hero.model_dump(mode='json'),before)

    def test_money_narration_has_one_authoritative_delta(self):
        before=self.state.model_copy(deep=True)
        adjust(self.hero,6,'sp')
        records=inventory_annotations(before,self.state)
        self.assertEqual(len(records),1)
        self.assertIn('银币 +6（现有 12）',records[0][1])
        self.assertEqual(inventory_annotations(self.state,GameState.model_validate(self.state.model_dump())),[])

    def test_builder_recomputes_starting_cash_in_inventory_once(self):
        hero=Character(name='builder',class_name='Bard',gold_gp=999)
        rules=RuleCatalog();rules.apply_builder_defaults(hero)
        before=hero.model_dump(mode='json')
        self.assertGreater(balance_cp(hero),0)
        rules.apply_builder_defaults(hero)
        self.assertEqual(hero.model_dump(mode='json'),before)
        self.assertNotIn('gold_gp',before)

    def test_real_graph_income_commits_and_failed_payment_rolls_back(self):
        case=fixtures.GenericSpellTests();case.setUp();runner=case.runner();self.addCleanup(case.doCleanups)
        state=case.state;hero=state.get_active_char();adjust(hero,19,'gp')
        state.campaign.reply_min_chars=0
        runner._model=Script([call('adjust_currency',character_ref=hero.character_id,amount=6,denomination='sp',reason='表演打赏'),AIMessage(content='你收好六枚银币。')])
        result=runner.run_turn(state,'收下表演所得的六枚银币打赏。')
        self.assertEqual(result.turn_status,'completed',result.response)
        self.assertEqual(balance_cp(result.game_state.get_active_char()),1960)
        self.assertIn('银币 +6',result.response)
        runner._model=Script([call('adjust_currency',character_ref=hero.character_id,amount=-100,denomination='gp',reason='房费'),call('report_rule_conflict',message='目前钱币不足以支付100金币房费，请调整。')])
        failed=runner.run_turn(result.game_state,'支付100金币房费。')
        self.assertEqual(failed.turn_status,'rules_feedback',failed.response)
        self.assertEqual(balance_cp(failed.game_state.get_active_char()),1960)

    def test_currency_api_and_pause_guard(self):
        from fastapi.testclient import TestClient
        import main as api
        from test_main_streaming import FakeStorage
        fake=FakeStorage(self.state)
        with patch.object(api,'game_storage',fake),TestClient(api.app) as client:
            path=f'/api/v1/games/{self.state.game_id}/actions/currency'
            payload={'character_ref':self.hero.character_id,'amount':-7,'denomination':'sp','reason':'住宿费'}
            response=client.post(path,json=payload)
            self.assertEqual(response.status_code,200,response.text)
            character=response.json()['game_state']['characters'][self.hero.character_id]
            self.assertNotIn('gold_gp',character)
            self.assertEqual(balance_cp(Character.model_validate(character)),1890)
            self.state.pending_turn=PendingTurnState(thread_id='synthetic-pause')
            self.assertEqual(client.post(path,json=payload).status_code,409)
            self.assertEqual(balance_cp(self.state.get_active_char()),1890)

    def test_old_disk_game_template_and_rewind_migrate_without_read_writes(self):
        import tempfile
        import storage
        with tempfile.TemporaryDirectory() as directory,patch.object(storage,'GAME_DIR',directory+'/games'),patch.object(storage,'REWIND_DIR',directory+'/rewind'),patch.object(storage,'CHAR_DIR',directory+'/characters'):
            games=storage.GameStorage();characters=storage.CharacterStorage()
            raw=self.state.model_dump(mode='json')
            old={'name':'legacy','character_id':'legacy','gold_gp':19,'inventory':[{'name':'银币','quantity':6,'type':'currency'}]}
            raw['characters']={'legacy':old};raw['active_character_id']='legacy';raw['primary_character_id']='legacy'
            game_path=Path(games._get_path(self.state.game_id));game_path.write_text(json.dumps(raw),encoding='utf-8')
            original=game_path.read_bytes()
            loaded=games.load_game(self.state.game_id)
            self.assertEqual(balance_cp(loaded.get_active_char()),1960)
            self.assertEqual(game_path.read_bytes(),original)
            games.save_game(loaded.game_id,loaded)
            self.assertNotIn('gold_gp',json.loads(game_path.read_text())['characters']['legacy'])
            rewind=Path(games._get_rewind_path(loaded.game_id,0));rewind.parent.mkdir(parents=True,exist_ok=True);rewind.write_text(json.dumps(raw),encoding='utf-8')
            self.assertEqual(balance_cp(games.load_rewind_snapshot(loaded.game_id,0).get_active_char()),1960)
            template=Path(characters._get_path('legacy'));template.write_text(json.dumps(old),encoding='utf-8')
            char=characters.load_character('legacy');self.assertEqual(balance_cp(char),1960)
            characters.save_character(char)
            self.assertEqual(balance_cp(characters.load_character('legacy')),1960)

    def test_income_cannot_resolve_a_failed_payment(self):
        from resolution_protocol import update_failures
        payment={'character_ref':self.hero.character_id,'amount':-100,'denomination':'gp','reason':'房费'}
        failed=update_failures(self.state,[],'adjust_currency',payment,False,'insufficient')
        after=update_failures(self.state,failed,'adjust_currency',{**payment,'amount':100},True,'')
        self.assertEqual(len(after),1)
        self.assertEqual(update_failures(self.state,after,'adjust_currency',payment,True,''),[])


if __name__=='__main__':unittest.main()
