"""LangGraph-backed Dungeon Master agent facade."""

import os
from typing import List

from dotenv import load_dotenv

from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from models import Character, GameState, TurnResult
from rag import RAGEngine
from rules_catalog import RuleCatalog
from storage import MonsterStorage

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)


class DMAgent:
    """
    Dungeon Master agent powered by LangGraph.
    Runtime state remains local JSON; LangGraph owns model orchestration and tool-call control flow.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL", "")
        self.model_name = os.getenv("LLM_MODEL", "gpt-5.1")
        self.monster_storage = MonsterStorage()
        self.rules_catalog = RuleCatalog()
        self.rag_engine = RAGEngine()
        self.tool_service = AgentToolService(
            rag_engine=self.rag_engine,
            monster_storage=self.monster_storage,
            rules_catalog=self.rules_catalog,
        )
        self.dm_graph_runner = DMGraphRunner(
            rag_engine=self.rag_engine,
            tool_service=self.tool_service,
            model_name=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            enable_model=True,
        )

        if self.api_key:
            os.environ.setdefault("OPENAI_API_KEY", self.api_key)
        if self.base_url:
            os.environ.setdefault("OPENAI_API_BASE", self.base_url)

    @property
    def backend_name(self) -> str:
        return "langgraph" if self.dm_graph_runner.is_available else "langgraph-unavailable"

    @property
    def checkpoint_backend(self) -> str:
        return self.dm_graph_runner.checkpoint_backend

    @property
    def checkpoint_db_path(self) -> str:
        return self.dm_graph_runner.checkpoint_db_path

    @property
    def checkpoint_warning(self) -> str:
        return self.dm_graph_runner.checkpoint_warning

    def close(self) -> None:
        self.dm_graph_runner.close()

    def create_new_game(
        self, characters: List[Character], game_id: str = "", title: str = ""
    ) -> GameState:
        state = GameState(game_id=game_id, title=title or game_id)

        if not characters:
            fallback = Character(name="Adventurer")
            state.characters[fallback.character_id] = fallback
            state.active_character_id = fallback.character_id
        else:
            for character in characters:
                state.characters[character.character_id] = character
            state.active_character_id = characters[0].character_id

        return state

    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        return self.dm_graph_runner.run_turn(state, user_input)

    async def resume_turn(self, state: GameState, user_input: str) -> TurnResult:
        return self.dm_graph_runner.resume_turn(state, user_input)
