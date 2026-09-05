"""暂停事务拒绝局部写入，但允许继续、取消和明确的历史回退。"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DM_AGENT_SKIP_DOTENV", "1")
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")

from fastapi.testclient import TestClient
import main as api
import storage as storage_module
from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from models import ChatMessage, InventoryItem
from rules_catalog import RuleCatalog
from storage import GameStorage, MonsterStorage, StateConflictError, atomic_write
import test_dm_graph_workflow as fixtures


class PendingTurnWriteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="dm-pending-writes-")
        self.addCleanup(self.directory.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(storage_module, "GAME_DIR", str(Path(self.directory.name) / "games")))
        self.stack.enter_context(patch.object(storage_module, "REWIND_DIR", str(Path(self.directory.name) / "rewind")))
        self.storage = GameStorage()
        state = fixtures.DMGraphWorkflowTests()._build_state(with_selected_adventure=True)
        self.hero = state.active_character_id
        self.game_id = state.game_id
        self.initial_hp = state.characters[self.hero].hp_current
        state.characters[self.hero].inventory.append(InventoryItem(name="Test token", quantity=2))
        state.chat_history = [ChatMessage(role="user", content="earlier action"), ChatMessage(role="assistant", content="earlier reply")]
        self.storage.save_game(self.game_id, state)
        self.initial = state.model_copy(deep=True)
        rag = fixtures.DummyRAGEngine()
        service = AgentToolService(rag, MonsterStorage(), RuleCatalog())
        self.runner = DMGraphRunner(rag_engine=rag, tool_service=service, enable_model=True,
                                    api_key="synthetic-test", checkpoint_mode="memory")
        self.addCleanup(self.runner.close)
        self.runner._model = fixtures.StagedWriteThenChoiceModel(self.hero)
        paused = self.runner.run_turn(state, "我检查伤口，结算一点伤势，但还没决定是否继续追赶。")
        self.assertEqual(paused.turn_status, "input_required")
        self.storage.save_game(self.game_id, paused.game_state)
        runner = self.runner

        class Agent:
            checkpoint_backend = "memory"
            checkpoint_db_path = ""
            async def run_turn(self, state, message):
                return runner.run_turn(state, message)
            async def resume_turn(self, state, message):
                return runner.resume_turn(state, message)

        self.stack.enter_context(patch.object(api, "agent", Agent()))
        self.stack.enter_context(patch.object(api, "game_storage", self.storage))
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)
        self.prefix = f"/api/v1/games/{self.game_id}"

    def quantity(self, state):
        return next(item.quantity for item in state.characters[self.hero].inventory if item.name == "Test token")

    def use_token(self):
        return self.client.post(self.prefix + "/actions/use-item", json={"user_ref": self.hero, "item_name": "Test token", "quantity": 1})

    def test_every_local_write_route_rejects_pending_without_mutation(self):
        requests = [
            ("reply-length", {"min_chars": 100, "max_chars": 200}),
            ("select-adventure", {"adventure_id": "missing"}),
            ("encounters/start", {"enemy_names": ["Enemy"]}),
            ("encounters/add-enemy", {"name": "Enemy"}),
            ("encounters/spawn-template", {"monster_id": "missing"}),
            ("encounters/end", {}),
            ("encounters/remove-combatant", {"combatant_ref": "missing"}),
            ("encounters/set-initiative", {"combatant_ref": "missing", "initiative": 10}),
            ("encounters/roll-initiative", {"combatant_ref": "missing"}),
            ("actions/advance-turn", {}),
            ("actions/attack", {"attacker_ref": self.hero, "target_ref": "missing"}),
            ("actions/skill-check", {"actor_ref": self.hero, "skill_name": "Perception"}),
            ("actions/saving-throw", {"target_ref": self.hero, "save_name": "constitution", "dc": 10}),
            ("actions/cast-spell", {"caster_ref": self.hero, "spell_name": "Fire Bolt"}),
            ("actions/use-item", {"user_ref": self.hero, "item_name": "Test token"}),
            ("actions/use-feature", {"actor_ref": self.hero, "feature_name": "Second Wind"}),
        ]
        path = Path(self.storage._get_path(self.game_id))
        before = path.read_bytes()
        for suffix, payload in requests:
            with self.subTest(route=suffix):
                response = self.client.post(self.prefix + "/" + suffix, json=payload)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("剧情选择", response.json()["detail"])
                self.assertEqual(path.read_bytes(), before)

    def test_storage_backstop_rejects_ordinary_pending_write(self):
        state = self.storage.load_game(self.game_id)
        next(item for item in state.characters[self.hero].inventory if item.name == "Test token").quantity = 1
        with self.assertRaises(StateConflictError):
            self.storage.save_game(self.game_id, state)
        self.assertEqual(self.quantity(self.storage.load_game(self.game_id)), 2)

    def test_read_routes_remain_available_without_setup_backfill(self):
        path = Path(self.storage._get_path(self.game_id))
        before = path.read_bytes()
        with patch.object(api, "ensure_adventure_generation_option", side_effect=AssertionError("GET mutated paused game")):
            self.assertEqual(self.client.get(self.prefix).status_code, 200)
        options = self.client.get(self.prefix + "/action-options").json()
        self.assertEqual(options["state_version"], self.storage.load_game(self.game_id).state_version)
        self.assertFalse(options["local_actions_allowed"])
        self.assertIn("剧情选择", options["local_actions_block_reason"])
        self.assertEqual(self.client.get(self.prefix + "/traces").status_code, 200)
        self.assertEqual(path.read_bytes(), before)

    def test_resume_commits_staged_changes_then_local_actions_work(self):
        self.assertEqual(self.use_token().status_code, 409)
        response = self.client.post(self.prefix + "/turns", json={"message": "继续追赶"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["turn_status"], "completed")
        saved = self.storage.load_game(self.game_id)
        self.assertIsNone(saved.pending_turn)
        self.assertEqual(saved.characters[self.hero].hp_current, self.initial_hp - 1)
        self.assertEqual(self.quantity(saved), 2)
        self.assertTrue(self.client.get(self.prefix + "/action-options").json()["local_actions_allowed"])
        self.assertEqual(self.use_token().status_code, 200)
        self.assertEqual(self.quantity(self.storage.load_game(self.game_id)), 1)

    def test_cancel_discards_staged_changes_and_unlocks_local_actions(self):
        response = self.client.post(self.prefix + "/turns", json={"message": "取消"})
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.storage.load_game(self.game_id)
        self.assertIsNone(saved.pending_turn)
        self.assertEqual(saved.characters[self.hero].hp_current, self.initial_hp)
        self.assertEqual(self.quantity(saved), 2)
        self.assertEqual(self.use_token().status_code, 200)

    def test_stream_resume_keeps_choice_available_while_local_writes_are_blocked(self):
        self.assertEqual(self.use_token().status_code, 409)
        response = self.client.post(self.prefix + "/turns/stream", json={"message": "继续追赶"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: turn.completed", response.text)
        saved = self.storage.load_game(self.game_id)
        self.assertIsNone(saved.pending_turn)
        self.assertEqual(self.quantity(saved), 2)

    def test_suggestion_cache_and_storage_metadata_do_not_invalidate_resume(self):
        state = self.storage.load_game(self.game_id)
        state.chat_history[-1].action_suggestions_generated = True
        self.storage.save_game(self.game_id, state, projection_only=True)
        response = self.client.post(self.prefix + "/turns", json={"message": "继续追赶"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["turn_status"], "completed")
        self.assertTrue(self.storage.load_game(self.game_id).chat_history[1].action_suggestions_generated)

    def test_legacy_pending_drift_preserves_saved_inventory_and_aborts_checkpoint(self):
        changed = self.storage.load_game(self.game_id)
        next(item for item in changed.characters[self.hero].inventory if item.name == "Test token").quantity = 1
        changed.state_version = "legacy-write-version"
        # 模拟旧版本已写入的合成存档；不通过新保护入口写入，也不读取玩家实际文件。
        atomic_write(self.storage._get_path(self.game_id), changed.model_dump_json().encode("utf-8"))
        response = self.client.post(self.prefix + "/turns", json={"message": "继续追赶"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["turn_status"], "failed")
        self.assertIn("已保存的物品和进度保留", response.json()["response"])
        saved = self.storage.load_game(self.game_id)
        self.assertIsNone(saved.pending_turn)
        self.assertEqual(self.quantity(saved), 1)
        self.assertEqual(saved.characters[self.hero].hp_current, self.initial_hp)
        self.assertEqual(self.use_token().status_code, 200)

    def test_explicit_rewind_during_pause_restores_historical_resources(self):
        snapshot = self.initial.model_copy(deep=True)
        snapshot.chat_history = []
        next(item for item in snapshot.characters[self.hero].inventory if item.name == "Test token").quantity = 3
        self.storage.save_rewind_snapshot(self.game_id, 0, snapshot)
        response = self.client.post(self.prefix + "/messages/0/delete")
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.storage.load_game(self.game_id)
        self.assertIsNone(saved.pending_turn)
        self.assertEqual(self.quantity(saved), 3)
        self.assertEqual(self.use_token().status_code, 200)


if __name__ == "__main__":
    unittest.main()
