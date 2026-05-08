"""LangGraph-backed Dungeon Master agent facade."""

import json
import os
from typing import Any, Dict, List
from urllib import parse as urllib_parse

from dotenv import load_dotenv

try:
    import requests
except ImportError:
    requests = None

from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from models import Character, GameState, TurnResult
from rag import RAGEngine
from rules_catalog import RuleCatalog
from storage import MonsterStorage

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)


def normalize_openai_base_url(base_url: str) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return ""

    parsed = urllib_parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/")

    path = (parsed.path or "").rstrip("/")
    if path:
        return raw.rstrip("/")

    normalized = parsed._replace(path="/v1")
    return urllib_parse.urlunparse(normalized).rstrip("/")


class DMAgent:
    """
    Dungeon Master agent powered by LangGraph.
    Runtime state remains local JSON; LangGraph owns model orchestration and tool-call control flow.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.raw_base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL", "")
        self.base_url = normalize_openai_base_url(self.raw_base_url)
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
            os.environ["OPENAI_API_BASE"] = self.base_url
            os.environ["OPENAI_BASE_URL"] = self.base_url

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

    @property
    def base_url_normalized(self) -> bool:
        return bool(self.base_url) and self.base_url != (self.raw_base_url or "").rstrip("/")

    def llm_runtime_payload(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "raw_base_url": self.raw_base_url,
            "base_url_normalized": self.base_url_normalized,
            "configured": bool(self.api_key and self.base_url),
        }

    def probe_llm(self, timeout_s: float = 20.0) -> Dict[str, Any]:
        payload = self.llm_runtime_payload()
        if not payload["configured"]:
            return {
                **payload,
                "ready": False,
                "status_code": 0,
                "reason": "missing_configuration",
                "detail": "OPENAI_API_KEY or OPENAI_API_BASE is missing.",
            }

        probe_url = f"{self.base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if requests is None:
            return {
                **payload,
                "ready": False,
                "status_code": 0,
                "reason": "missing_dependency",
                "detail": "requests is not installed.",
                "probe_url": probe_url,
            }
        try:
            response = requests.get(probe_url, headers=headers, timeout=timeout_s)
            detail = response.text[:240]
            try:
                parsed = response.json()
                detail = str(parsed.get("error", {}).get("message") or detail)
            except json.JSONDecodeError:
                pass
            return {
                **payload,
                "ready": response.ok,
                "status_code": int(response.status_code),
                "reason": "ok" if response.ok else "http_error",
                "detail": detail,
                "probe_url": probe_url,
            }
        except Exception as exc:
            return {
                **payload,
                "ready": False,
                "status_code": 0,
                "reason": "request_failed",
                "detail": str(exc),
                "probe_url": probe_url,
            }

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
