"""Simple JSON persistence for games, characters, and monster templates."""

import glob
import json
import os
import shutil
from datetime import datetime
from typing import List, Optional

from models import Character, CharacterSummary, GameState, GameSummary, MonsterSummary, MonsterTemplate

GAME_DIR = os.path.join(os.path.dirname(__file__), "Game")
CHAR_DIR = os.path.join(os.path.dirname(__file__), "Characters")
MONSTER_DIR = os.path.join(os.path.dirname(__file__), "Monsters")
REWIND_DIR = os.path.join(GAME_DIR, "_rewind")


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

    def save_game(self, game_id: str, state: GameState) -> None:
        state.game_id = game_id
        state.title = state.title or game_id
        state.created_at = state.created_at or now_iso()
        state.updated_at = now_iso()

        path = self._get_path(game_id)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(state.model_dump_json(indent=2))

    def load_game(self, game_id: str) -> Optional[GameState]:
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
        with open(self._get_rewind_path(game_id, message_index), "w", encoding="utf-8") as handle:
            handle.write(snapshot.model_dump_json(indent=2))

    def load_rewind_snapshot(self, game_id: str, message_index: int) -> Optional[GameState]:
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

    def prune_rewind_snapshots_from(self, game_id: str, message_index: int) -> None:
        rewind_dir = self._get_rewind_dir(game_id)
        if not os.path.isdir(rewind_dir):
            return
        for path in glob.glob(os.path.join(rewind_dir, "*.json")):
            try:
                index = int(os.path.splitext(os.path.basename(path))[0])
            except ValueError:
                continue
            if index >= message_index:
                os.remove(path)


class CharacterStorage:
    # Character templates are reusable across multiple games.
    def __init__(self):
        os.makedirs(CHAR_DIR, exist_ok=True)

    def _get_path(self, character_id: str) -> str:
        return os.path.join(CHAR_DIR, f"{safe_file_stem(character_id)}.json")

    def save_character(self, char: Character) -> None:
        path = self._get_path(char.character_id)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(char.model_dump_json(indent=2))

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
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(monster.model_dump_json(indent=2))

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
