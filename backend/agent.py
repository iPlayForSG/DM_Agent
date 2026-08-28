"""LangGraph-backed Dungeon Master agent facade."""

import base64
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional
from urllib import parse as urllib_parse

from dotenv import load_dotenv

try:
    import requests
except ImportError:
    requests = None

from agent_tools import AgentToolService
from dm_graph import DMGraphRunner
from model_backends import (
    OPENAI_COMPATIBLE_PROVIDER,
    SUPPORTED_MODEL_PROVIDERS,
    default_cli_command,
    probe_cli,
)
from models import ActionSuggestion, AdventureHook, Character, GameState, TurnResult
from rag import RAGEngine
from rules_catalog import RuleCatalog
from storage import MonsterStorage

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.getenv("DM_AGENT_SKIP_DOTENV", "").strip().lower() not in {"1", "true", "yes"}:
    load_dotenv(dotenv_path=env_path, override=True)


LLM_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
    "LLM_MODEL",
    "LLM_PROVIDER",
    "LLM_CLI_COMMAND",
    "LLM_CLI_TIMEOUT_S",
    "LLM_ACTIVE_PROFILE_ID",
    "LLM_PROFILES_B64",
)


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
        self.model_provider = os.getenv("LLM_PROVIDER", OPENAI_COMPATIBLE_PROVIDER).strip() or OPENAI_COMPATIBLE_PROVIDER
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.raw_base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL", "")
        self.base_url = normalize_openai_base_url(self.raw_base_url)
        default_model = "gpt-5.1" if self.model_provider == OPENAI_COMPATIBLE_PROVIDER else ""
        self.model_name = os.getenv("LLM_MODEL", default_model)
        self.cli_command = os.getenv("LLM_CLI_COMMAND", "").strip()
        self.cli_timeout_s = self._parse_cli_timeout(os.getenv("LLM_CLI_TIMEOUT_S", "300"))
        self.active_profile_id = os.getenv("LLM_ACTIVE_PROFILE_ID", "")
        self.llm_profiles = self._load_llm_profiles()
        self._ensure_active_profile()
        self.monster_storage = MonsterStorage()
        self.rules_catalog = RuleCatalog()
        self.rag_engine = RAGEngine()
        self.tool_service = AgentToolService(
            rag_engine=self.rag_engine,
            monster_storage=self.monster_storage,
            rules_catalog=self.rules_catalog,
        )
        self.dm_graph_runner = self._create_dm_graph_runner()

        self._apply_llm_environment()

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
    def agent_topology(self) -> Dict[str, List[str]]:
        return self.dm_graph_runner.registered_agent_topology()

    @property
    def base_url_normalized(self) -> bool:
        return bool(self.base_url) and self.base_url != (self.raw_base_url or "").rstrip("/")

    @staticmethod
    def _profile_id_from_label(label: str) -> str:
        normalized = str(label or "").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:36]
        digest = hashlib.md5(str(label or "llm-profile").encode("utf-8")).hexdigest()[:8]
        return f"llm-{slug or 'profile'}-{digest}"

    @staticmethod
    def _default_profile_label(
        model_name: str,
        base_url: str,
        provider: str = OPENAI_COMPATIBLE_PROVIDER,
    ) -> str:
        if provider != OPENAI_COMPATIBLE_PROVIDER:
            return f"{provider} · {model_name or 'CLI default'}"
        model = str(model_name or "model").strip()
        parsed = urllib_parse.urlparse(str(base_url or "").strip())
        host = parsed.netloc or parsed.path or "provider"
        return f"{model} @ {host}"

    @staticmethod
    def _decode_profiles(raw_b64: str) -> List[Dict[str, Any]]:
        raw = str(raw_b64 or "").strip()
        if not raw:
            return []
        try:
            decoded = base64.b64decode(raw.encode("ascii")).decode("utf-8")
            payload = json.loads(decoded)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _encode_profiles(profiles: List[Dict[str, Any]]) -> str:
        raw = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
        return base64.b64encode(raw.encode("utf-8")).decode("ascii")

    def _load_llm_profiles(self) -> List[Dict[str, Any]]:
        profiles = self._decode_profiles(os.getenv("LLM_PROFILES_B64", ""))
        normalized: List[Dict[str, Any]] = []
        for profile in profiles:
            try:
                provider = self._validate_provider(profile.get("provider", OPENAI_COMPATIBLE_PROVIDER))
            except ValueError:
                continue
            label = self._validate_env_value("profile_label", profile.get("label", ""))
            model_name = self._validate_env_value("LLM_MODEL", profile.get("model_name", ""))
            raw_base_url = self._validate_env_value("OPENAI_API_BASE", profile.get("raw_base_url") or profile.get("base_url", ""))
            api_key = self._validate_env_value("OPENAI_API_KEY", profile.get("api_key", ""))
            cli_command = self._validate_env_value("LLM_CLI_COMMAND", profile.get("cli_command", ""))
            cli_timeout_s = self._parse_cli_timeout(profile.get("cli_timeout_s", 300))
            if not label:
                continue
            if provider == OPENAI_COMPATIBLE_PROVIDER and (not model_name or not raw_base_url):
                continue
            profile_id = self._validate_env_value("profile_id", profile.get("profile_id", "")) or self._profile_id_from_label(label)
            normalized.append(
                {
                    "profile_id": profile_id,
                    "label": label,
                    "provider": provider,
                    "model_name": model_name,
                    "raw_base_url": raw_base_url,
                    "api_key": api_key,
                    "cli_command": cli_command,
                    "cli_timeout_s": cli_timeout_s,
                }
            )
        return normalized

    def _find_llm_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        for profile in self.llm_profiles:
            if profile.get("profile_id") == profile_id:
                return profile
        return None

    def _ensure_active_profile(self) -> None:
        active_profile = self._find_llm_profile(self.active_profile_id)
        if active_profile:
            self.model_provider = active_profile.get("provider", OPENAI_COMPATIBLE_PROVIDER)
            self.api_key = active_profile.get("api_key", "")
            self.raw_base_url = active_profile.get("raw_base_url", "")
            self.model_name = active_profile.get("model_name", "")
            self.cli_command = active_profile.get("cli_command", "")
            self.cli_timeout_s = self._parse_cli_timeout(active_profile.get("cli_timeout_s", 300))
            self.base_url = normalize_openai_base_url(self.raw_base_url)
            return

        label = self._default_profile_label(self.model_name, self.raw_base_url, self.model_provider)
        profile_id = self.active_profile_id or self._profile_id_from_label(label)
        profile = {
            "profile_id": profile_id,
            "label": label,
            "provider": self.model_provider,
            "model_name": self.model_name,
            "raw_base_url": self.raw_base_url,
            "api_key": self.api_key,
            "cli_command": self.cli_command,
            "cli_timeout_s": self.cli_timeout_s,
        }
        self.active_profile_id = profile_id
        if not self._find_llm_profile(profile_id):
            self.llm_profiles.append(profile)

    def _public_llm_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        raw_base_url = profile.get("raw_base_url", "")
        profile_id = profile.get("profile_id", "")
        return {
            "profile_id": profile_id,
            "label": profile.get("label", ""),
            "provider": profile.get("provider", OPENAI_COMPATIBLE_PROVIDER),
            "model_name": profile.get("model_name", ""),
            "base_url": normalize_openai_base_url(raw_base_url),
            "raw_base_url": raw_base_url,
            "api_key_configured": bool(profile.get("api_key", "")),
            "cli_command": profile.get("cli_command", ""),
            "cli_timeout_s": self._parse_cli_timeout(profile.get("cli_timeout_s", 300)),
            "active": profile_id == self.active_profile_id,
        }

    def llm_runtime_payload(self) -> Dict[str, Any]:
        configured = (
            bool(self.api_key and self.base_url and self.model_name)
            if self.model_provider == OPENAI_COMPATIBLE_PROVIDER
            else self.model_provider in SUPPORTED_MODEL_PROVIDERS
        )
        return {
            "active_profile_id": self.active_profile_id,
            "provider": self.model_provider,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "raw_base_url": self.raw_base_url,
            "base_url_normalized": self.base_url_normalized,
            "cli_command": self.cli_command,
            "cli_timeout_s": self.cli_timeout_s,
            "configured": configured,
            "api_key_configured": bool(self.api_key),
            "profiles": [self._public_llm_profile(profile) for profile in self.llm_profiles],
        }

    def probe_llm(self, timeout_s: float = 20.0) -> Dict[str, Any]:
        payload = self.llm_runtime_payload()
        if self.model_provider != OPENAI_COMPATIBLE_PROVIDER:
            return {
                **payload,
                **probe_cli(self.model_provider, self.cli_command, timeout_s=min(timeout_s, 10.0)),
                "status_code": 0,
            }
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

    def _create_dm_graph_runner(self) -> DMGraphRunner:
        model_enabled = (
            bool(self.api_key and self.base_url and self.model_name)
            if self.model_provider == OPENAI_COMPATIBLE_PROVIDER
            else self.model_provider in SUPPORTED_MODEL_PROVIDERS
        )
        return DMGraphRunner(
            rag_engine=self.rag_engine,
            tool_service=self.tool_service,
            model_name=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            model_provider=self.model_provider,
            cli_command=self.cli_command,
            cli_timeout_s=self.cli_timeout_s,
            enable_model=model_enabled,
        )

    def _apply_llm_environment(self) -> None:
        os.environ["LLM_PROVIDER"] = self.model_provider
        os.environ["LLM_CLI_COMMAND"] = self.cli_command
        os.environ["LLM_CLI_TIMEOUT_S"] = str(self.cli_timeout_s)
        if self.model_provider != OPENAI_COMPATIBLE_PROVIDER:
            # 避免上一 API 档案的凭据被无关 CLI 子进程继承；CLI 使用各自已有登录态。
            for key in ("OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
                os.environ.pop(key, None)
        elif self.api_key:
            os.environ["OPENAI_API_KEY"] = self.api_key
        if self.base_url:
            os.environ["OPENAI_API_BASE"] = self.base_url
            os.environ["OPENAI_BASE_URL"] = self.base_url
        if self.model_name:
            os.environ["LLM_MODEL"] = self.model_name

    @staticmethod
    def _validate_env_value(name: str, value: str) -> str:
        normalized = str(value or "").strip()
        if "\n" in normalized or "\r" in normalized:
            raise ValueError(f"{name} must be a single-line value.")
        return normalized

    @staticmethod
    def _validate_provider(value: str) -> str:
        provider = str(value or OPENAI_COMPATIBLE_PROVIDER).strip().lower()
        if provider not in SUPPORTED_MODEL_PROVIDERS:
            raise ValueError(f"Unsupported model provider: {provider}")
        return provider

    @staticmethod
    def _parse_cli_timeout(value: Any) -> int:
        try:
            return max(10, min(int(value or 300), 1800))
        except (TypeError, ValueError):
            return 300

    @staticmethod
    def _persist_env_values(path: str, updates: Dict[str, str]) -> None:
        sanitized = {
            key: DMAgent._validate_env_value(key, value)
            for key, value in updates.items()
            if key in LLM_ENV_KEYS
        }
        if not sanitized:
            return

        lines: List[str] = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()

        seen = set()
        next_lines: List[str] = []
        pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
        for line in lines:
            match = pattern.match(line)
            key = match.group(1) if match else ""
            if key in sanitized:
                next_lines.append(f"{key}={sanitized[key]}")
                seen.add(key)
            else:
                next_lines.append(line)

        for key in LLM_ENV_KEYS:
            if key in sanitized and key not in seen:
                next_lines.append(f"{key}={sanitized[key]}")

        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(next_lines).rstrip() + "\n")

    def _persist_current_llm_config(self) -> None:
        self._persist_env_values(
            env_path,
            {
                "OPENAI_API_KEY": self.api_key,
                "OPENAI_API_BASE": self.raw_base_url,
                "OPENAI_BASE_URL": self.raw_base_url,
                "LLM_MODEL": self.model_name,
                "LLM_PROVIDER": self.model_provider,
                "LLM_CLI_COMMAND": self.cli_command,
                "LLM_CLI_TIMEOUT_S": str(self.cli_timeout_s),
                "LLM_ACTIVE_PROFILE_ID": self.active_profile_id,
                "LLM_PROFILES_B64": self._encode_profiles(self.llm_profiles),
            },
        )

    def _activate_llm_profile(self, profile: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
        provider = self._validate_provider(profile.get("provider", OPENAI_COMPATIBLE_PROVIDER))
        api_key = profile.get("api_key", "")
        raw_base_url = profile.get("raw_base_url", "")
        model_name = profile.get("model_name", "")
        if provider == OPENAI_COMPATIBLE_PROVIDER:
            if not api_key:
                raise ValueError("API Key is required for the selected model profile.")
            if not raw_base_url:
                raise ValueError("Base URL is required for the selected model profile.")
            if not model_name:
                raise ValueError("Model name is required for the selected model profile.")

        self.close()
        self.active_profile_id = profile.get("profile_id", "")
        self.model_provider = provider
        self.api_key = api_key
        self.raw_base_url = raw_base_url
        self.base_url = normalize_openai_base_url(raw_base_url)
        self.model_name = model_name
        self.cli_command = profile.get("cli_command", "")
        self.cli_timeout_s = self._parse_cli_timeout(profile.get("cli_timeout_s", 300))
        self._apply_llm_environment()
        self.dm_graph_runner = self._create_dm_graph_runner()
        if persist:
            self._persist_current_llm_config()
        return self.llm_runtime_payload()

    def select_llm_profile(self, profile_id: str, persist: bool = True) -> Dict[str, Any]:
        normalized_profile_id = self._validate_env_value("profile_id", profile_id)
        profile = self._find_llm_profile(normalized_profile_id)
        if not profile:
            raise ValueError("Model profile was not found.")
        return self._activate_llm_profile(profile, persist=persist)

    def upsert_llm_profile(
        self,
        *,
        profile_id: str = "",
        profile_label: str,
        provider: str = OPENAI_COMPATIBLE_PROVIDER,
        model_name: str,
        base_url: str,
        api_key: Optional[str] = None,
        cli_command: str = "",
        cli_timeout_s: int = 300,
        activate: bool = True,
        persist: bool = True,
    ) -> Dict[str, Any]:
        label = self._validate_env_value("profile_label", profile_label)
        next_provider = self._validate_provider(provider)
        next_model_name = self._validate_env_value("LLM_MODEL", model_name)
        next_raw_base_url = self._validate_env_value("OPENAI_API_BASE", base_url)
        provided_api_key = self._validate_env_value("OPENAI_API_KEY", api_key) if api_key is not None else ""
        next_cli_command = self._validate_env_value("LLM_CLI_COMMAND", cli_command)
        next_cli_timeout_s = self._parse_cli_timeout(cli_timeout_s)

        if not label:
            raise ValueError("Profile name is required.")
        if next_provider == OPENAI_COMPATIBLE_PROVIDER:
            if not next_model_name:
                raise ValueError("Model name is required.")
            if not next_raw_base_url:
                raise ValueError("Base URL is required.")

        normalized_profile_id = self._validate_env_value("profile_id", profile_id) or self._profile_id_from_label(label)
        existing_profile = self._find_llm_profile(normalized_profile_id)
        existing_api_key = existing_profile.get("api_key", "") if existing_profile else ""
        next_api_key = provided_api_key or existing_api_key
        if next_provider == OPENAI_COMPATIBLE_PROVIDER and not next_api_key:
            raise ValueError("API Key is required because this profile has no saved key.")

        next_profile = {
            "profile_id": normalized_profile_id,
            "label": label,
            "provider": next_provider,
            "model_name": next_model_name,
            "raw_base_url": next_raw_base_url,
            "api_key": next_api_key,
            "cli_command": next_cli_command or default_cli_command(next_provider),
            "cli_timeout_s": next_cli_timeout_s,
        }

        replaced = False
        self.llm_profiles = [
            next_profile if profile.get("profile_id") == normalized_profile_id else profile
            for profile in self.llm_profiles
        ]
        for profile in self.llm_profiles:
            if profile.get("profile_id") == normalized_profile_id:
                replaced = True
                break
        if not replaced:
            self.llm_profiles.append(next_profile)

        if activate:
            return self._activate_llm_profile(next_profile, persist=persist)

        if persist:
            self._persist_current_llm_config()
        return self.llm_runtime_payload()

    def update_llm_config(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        label = self._default_profile_label(model_name, base_url)
        return self.upsert_llm_profile(
            profile_id=self.active_profile_id,
            profile_label=label,
            provider=OPENAI_COMPATIBLE_PROVIDER,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            activate=True,
            persist=persist,
        )

    def create_new_game(
        self, characters: List[Character], game_id: str = "", title: str = ""
    ) -> GameState:
        state = GameState(game_id=game_id, title=title or game_id)

        for character in characters:
            state.characters[character.character_id] = character
        if characters:
            state.active_character_id = characters[0].character_id

        return state

    def generate_adventure_hook(self, state: GameState) -> AdventureHook:
        return self.dm_graph_runner.generate_adventure_hook(state)

    def clean_player_response(self, response: str) -> str:
        return self.dm_graph_runner.clean_player_response(response)

    def build_action_suggestions(self, state: GameState, response: str) -> List[ActionSuggestion]:
        return self.dm_graph_runner.build_action_suggestions_for_response(state, response)

    def project_action_suggestions(
        self,
        state: GameState,
        response: str,
        user_input: str = "",
    ) -> tuple[List[ActionSuggestion], Dict[str, Any]]:
        return self.dm_graph_runner.suggestion_agent.project(state, response, user_input)

    async def run_turn(self, state: GameState, user_input: str) -> TurnResult:
        return self.dm_graph_runner.run_turn(state, user_input)

    async def resume_turn(self, state: GameState, user_input: str) -> TurnResult:
        return self.dm_graph_runner.resume_turn(state, user_input)
