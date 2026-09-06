"""外部损坏数据可降级，内部契约错误不能被伪装成正常结果。"""

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

from pydantic import ValidationError

from dm_graph import DMGraphRunner
from models import Character, GameState, MonsterTemplate
import storage


class StorageReadContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="dm-read-contract-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        for name in ("GAME_DIR", "REWIND_DIR", "CHAR_DIR", "MONSTER_DIR"):
            patcher = patch.object(storage, name, str(self.directory / name))
            patcher.start()
            self.addCleanup(patcher.stop)
        games = storage.GameStorage()
        characters = storage.CharacterStorage()
        monsters = storage.MonsterStorage()
        self.loaders = (
            (GameState, Path(games._get_path("test")), lambda: games.load_game("test")),
            (GameState, Path(games._get_rewind_path("test", 0)), lambda: games.load_rewind_snapshot("test", 0)),
            (Character, Path(characters._get_path("test")), lambda: characters.load_character("test")),
            (MonsterTemplate, Path(monsters._get_path("test")), lambda: monsters.load_monster("test")),
        )

    def test_unreadable_or_invalid_saved_data_still_returns_none(self):
        for _, path, load in self.loaders:
            path.parent.mkdir(parents=True, exist_ok=True)
            for content in (b"\xff", b"{invalid", b"[]"):
                with self.subTest(path=path.name, content=content):
                    path.write_bytes(content)
                    self.assertIsNone(load())

    def test_internal_validation_bug_is_not_reported_as_missing_save(self):
        for model, path, load in self.loaders:
            with self.subTest(model=model.__name__, path=str(path)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
                with patch.object(model, "model_validate", side_effect=RuntimeError("internal bug")):
                    with self.assertRaisesRegex(RuntimeError, "internal bug"):
                        load()


class DMStateContractTests(unittest.TestCase):
    def test_invalid_running_state_cannot_silently_skip_enemy_turn(self):
        with self.assertRaises(ValidationError):
            DMGraphRunner._dm_controlled_turn_pending({"game_state": {"encounter": "invalid"}})
        with self.assertRaises(KeyError):
            DMGraphRunner._dm_controlled_turn_pending({})

    def test_failed_turn_does_not_require_staged_state_to_route_out(self):
        self.assertFalse(DMGraphRunner._dm_controlled_turn_pending({"turn_status": "failed"}))


if __name__ == "__main__":
    unittest.main()
