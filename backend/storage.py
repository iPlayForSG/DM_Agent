"""Simple JSON persistence for games, characters, and monster templates."""

import glob
import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from typing import List, Optional

from models import Character, CharacterSummary, GameState, GameSummary, MonsterSummary, MonsterTemplate

GAME_DIR = os.path.join(os.path.dirname(__file__), "Game")
CHAR_DIR = os.path.join(os.path.dirname(__file__), "Characters")
MONSTER_DIR = os.path.join(os.path.dirname(__file__), "Monsters")
REWIND_DIR = os.path.join(GAME_DIR, "_rewind")
PENDING_TURN_ACTION_MESSAGE = "当前有待完成的剧情选择，请先完成或取消，再执行本地动作或修改本局设置。"

_GAME_LOCKS = {}
_GAME_LOCKS_GUARD = threading.Lock()
_ACTIVE_GAME_LOCKS = threading.local()


class StateConflictError(RuntimeError):
    """旧请求不能覆盖此后已保存、删除或重建的游戏。"""


def atomic_write(path: str, content: bytes) -> None:
    """先完整写入同目录临时文件，再替换，失败时保留原文件。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".save-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_file_stem(value: str) -> str:
    safe = "".join(c for c in value if c.isalnum() or c in (" ", "_", "-")).strip()
    return safe or "untitled"


class GameStorage:
    # Game state is stored as one JSON file per game id.
    def __init__(self):
        os.makedirs(GAME_DIR, exist_ok=True)
        os.makedirs(REWIND_DIR, exist_ok=True)

    def _get_path(self, game_id: str) -> str:
        return os.path.join(GAME_DIR, f"{safe_file_stem(game_id)}.json")

    def _get_rewind_dir(self, game_id: str) -> str:
        return os.path.join(REWIND_DIR, safe_file_stem(game_id))

    def _get_rewind_path(self, game_id: str, message_index: int) -> str:
        return os.path.join(self._get_rewind_dir(game_id), f"{int(message_index):06d}.json")

    @contextmanager
    def _lock(self, game_id: str):
        key = os.path.normcase(os.path.abspath(self._get_path(game_id)))
        with _GAME_LOCKS_GUARD:
            lock = _GAME_LOCKS.setdefault(key, threading.RLock())
        with lock:
            active = getattr(_ACTIVE_GAME_LOCKS, "paths", set())
            if key in active:
                yield
                return
            # 进程内锁之外再锁稳定的旁路文件，覆盖重复启动或多 worker 的同一存档提交。
            lock_dir = os.path.join(GAME_DIR, "_locks")
            os.makedirs(lock_dir, exist_ok=True)
            with open(os.path.join(lock_dir, safe_file_stem(game_id) + ".lock"), "a+b") as handle:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                active.add(key)
                _ACTIVE_GAME_LOCKS.paths = active
                try:
                    yield
                finally:
                    active.remove(key)
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _check_version(self, game_id: str, expected_version: str, *, require_existing: bool = False) -> Optional[dict]:
        path = self._get_path(game_id)
        if not os.path.exists(path):
            if expected_version or require_existing:
                raise StateConflictError("游戏已删除或变化，请重新加载后再操作。")
            return
        with open(path, "r", encoding="utf-8") as handle:
            current = json.load(handle)
        if str(current.get("state_version") or "") != expected_version:
            raise StateConflictError("游戏已有较新的修改，本次旧结果未保存；请重新加载后重试。")
        return current

    @staticmethod
    def _save_metadata(game_id: str, state: GameState):
        return {
            "game_id": game_id, "title": state.title or game_id,
            "created_at": state.created_at or now_iso(), "updated_at": now_iso(),
            "state_version": uuid4().hex,
        }

    def save_game(self, game_id: str, state: GameState, *, expected_version: Optional[str] = None,
                  projection_only: bool = False) -> None:
        with self._lock(game_id):
            current_payload = self._check_version(game_id, state.state_version if expected_version is None else expected_version)
            # 恢复/回退走显式 save_turn；普通写入不能越过正在等待玩家选择的事务。
            if current_payload and current_payload.get("pending_turn") and not projection_only:
                raise StateConflictError(PENDING_TURN_ACTION_MESSAGE)
            metadata = self._save_metadata(game_id, state)
            if projection_only:
                # 建议缓存不是权威回合变化；主回合会合并缓存，不应因此产生业务版本冲突。
                current = self._load_game(game_id)
                def authoritative_payload(value):
                    payload = value.model_dump(mode="json")
                    for field in ("updated_at", "state_version"):
                        payload.pop(field, None)
                    for message in payload["chat_history"]:
                        message.pop("action_suggestions", None)
                        message.pop("action_suggestions_generated", None)
                    return payload
                if current is None or authoritative_payload(current) != authoritative_payload(state):
                    raise ValueError("Projection-only writes may only update existing message suggestions")
                metadata["state_version"] = state.state_version
            content = state.model_copy(update=metadata).model_dump_json(indent=2).encode("utf-8")
            atomic_write(self._get_path(game_id), content)
            for key, value in metadata.items():
                setattr(state, key, value)

    def save_turn(self, game_id: str, state: GameState, *, expected_version: str,
                  snapshots: dict[int, GameState], prune_from: int) -> None:
        # 模型完成前不碰原分支。先验证版本、完成全部序列化，再在锁内发布快照和主状态。
        with self._lock(game_id):
            self._check_version(game_id, expected_version, require_existing=True)
            metadata = self._save_metadata(game_id, state)
            game_content = state.model_copy(update=metadata).model_dump_json(indent=2).encode("utf-8")
            contents = {
                self._get_rewind_path(game_id, index): snapshot.model_dump_json(indent=2).encode("utf-8")
                for index, snapshot in snapshots.items()
            }
            previous = {}
            for path in contents:
                if os.path.exists(path):
                    with open(path, "rb") as handle:
                        previous[path] = handle.read()
                else:
                    previous[path] = None
            published = []
            try:
                for path, content in contents.items():
                    atomic_write(path, content)
                    published.append(path)
                atomic_write(self._get_path(game_id), game_content)
            except Exception:
                for path in reversed(published):
                    if previous[path] is None:
                        os.remove(path)
                    else:
                        atomic_write(path, previous[path])
                raise
            for key, value in metadata.items():
                setattr(state, key, value)
            # 旧分支清理在提交后进行；残留的未来索引不能通过消息索引校验访问。
            self.prune_rewind_snapshots_from(game_id, prune_from, keep=set(snapshots))

    def load_game(self, game_id: str) -> Optional[GameState]:
        with self._lock(game_id):
            return self._load_game(game_id)

    def _load_game(self, game_id: str) -> Optional[GameState]:
        path = self._get_path(game_id)
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            state = GameState.model_validate(data)
            if not state.game_id:
                state.game_id = game_id
            if not state.title:
                state.title = state.game_id
            return state
        except Exception as exc:
            print(f"Error loading game {game_id}: {exc}")
            return None

    def list_games(self) -> List[str]:
        return [summary.game_id for summary in self.list_game_summaries()]

    def list_game_summaries(self) -> List[GameSummary]:
        summaries: List[GameSummary] = []
        for path in glob.glob(os.path.join(GAME_DIR, "*.json")):
            game_id = os.path.splitext(os.path.basename(path))[0]
            state = self.load_game(game_id)
            if state:
                summaries.append(state.to_summary())

        summaries.sort(key=lambda item: item.updated_at or "", reverse=True)
        return summaries

    def delete_game(self, game_id: str) -> None:
        with self._lock(game_id):
            path = self._get_path(game_id)
            if os.path.exists(path):
                os.remove(path)
            rewind_dir = self._get_rewind_dir(game_id)
            if os.path.isdir(rewind_dir):
                shutil.rmtree(rewind_dir)

    def save_rewind_snapshot(self, game_id: str, message_index: int, state: GameState) -> None:
        if message_index < 0:
            return
        snapshot = state.model_copy(deep=True)
        snapshot.game_id = game_id
        snapshot.title = snapshot.title or game_id

        rewind_dir = self._get_rewind_dir(game_id)
        os.makedirs(rewind_dir, exist_ok=True)
        content = snapshot.model_dump_json(indent=2).encode("utf-8")
        with self._lock(game_id):
            atomic_write(self._get_rewind_path(game_id, message_index), content)

    def load_rewind_snapshot(self, game_id: str, message_index: int) -> Optional[GameState]:
        with self._lock(game_id):
            return self._load_rewind_snapshot(game_id, message_index)

    def _load_rewind_snapshot(self, game_id: str, message_index: int) -> Optional[GameState]:
        path = self._get_rewind_path(game_id, message_index)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            state = GameState.model_validate(data)
            state.game_id = game_id
            state.title = state.title or game_id
            return state
        except Exception as exc:
            print(f"Error loading rewind snapshot {game_id}@{message_index}: {exc}")
            return None

    def prune_rewind_snapshots_from(self, game_id: str, message_index: int, *, keep=None) -> None:
        rewind_dir = self._get_rewind_dir(game_id)
        if not os.path.isdir(rewind_dir):
            return
        for path in glob.glob(os.path.join(rewind_dir, "*.json")):
            try:
                index = int(os.path.splitext(os.path.basename(path))[0])
            except ValueError:
                continue
            if index >= message_index and index not in (keep or set()):
                try:
                    os.remove(path)
                except OSError:
                    # 已提交新状态时清理失败不能将成功事务伪装成失败；后续写入会再次清理。
                    pass


class CharacterStorage:
    # Character templates are reusable across multiple games.
    def __init__(self):
        os.makedirs(CHAR_DIR, exist_ok=True)

    def _get_path(self, character_id: str) -> str:
        return os.path.join(CHAR_DIR, f"{safe_file_stem(character_id)}.json")

    def save_character(self, char: Character) -> None:
        path = self._get_path(char.character_id)
        atomic_write(path, char.model_dump_json(indent=2).encode("utf-8"))

    def _load_path(self, path: str) -> Optional[Character]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return Character.model_validate(data)
        except Exception:
            return None

    def load_character(self, identifier: str) -> Optional[Character]:
        direct_path = self._get_path(identifier)
        if os.path.exists(direct_path):
            return self._load_path(direct_path)

        for path in glob.glob(os.path.join(CHAR_DIR, "*.json")):
            character = self._load_path(path)
            if not character:
                continue
            if character.character_id == identifier or character.name == identifier:
                return character
        return None

    def list_characters(self) -> List[str]:
        return [summary.name for summary in self.list_character_summaries()]

    def list_character_summaries(self) -> List[CharacterSummary]:
        summaries: List[CharacterSummary] = []
        for path in glob.glob(os.path.join(CHAR_DIR, "*.json")):
            character = self._load_path(path)
            if character:
                summaries.append(character.to_summary())

        summaries.sort(key=lambda item: item.name)
        return summaries

    def delete_character(self, identifier: str) -> bool:
        character = self.load_character(identifier)
        if not character:
            return False

        path = self._get_path(character.character_id)
        if not os.path.exists(path):
            return False

        os.remove(path)
        return True


class MonsterStorage:
    # Monster templates are long-lived content assets.
    def __init__(self):
        os.makedirs(MONSTER_DIR, exist_ok=True)

    def _get_path(self, monster_id: str) -> str:
        return os.path.join(MONSTER_DIR, f"{safe_file_stem(monster_id)}.json")

    def save_monster(self, monster: MonsterTemplate) -> None:
        path = self._get_path(monster.monster_id)
        atomic_write(path, monster.model_dump_json(indent=2).encode("utf-8"))

    def _load_path(self, path: str) -> Optional[MonsterTemplate]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return MonsterTemplate.model_validate(data)
        except Exception:
            return None

    def load_monster(self, identifier: str) -> Optional[MonsterTemplate]:
        direct_path = self._get_path(identifier)
        if os.path.exists(direct_path):
            return self._load_path(direct_path)

        for path in glob.glob(os.path.join(MONSTER_DIR, "*.json")):
            monster = self._load_path(path)
            if not monster:
                continue
            if monster.monster_id == identifier or monster.name == identifier:
                return monster
        return None

    def list_monster_summaries(self) -> List[MonsterSummary]:
        summaries: List[MonsterSummary] = []
        for path in glob.glob(os.path.join(MONSTER_DIR, "*.json")):
            monster = self._load_path(path)
            if monster:
                summaries.append(monster.to_summary())

        summaries.sort(key=lambda item: item.name)
        return summaries
