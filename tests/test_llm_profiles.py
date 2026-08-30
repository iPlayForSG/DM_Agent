import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ["DM_AGENT_SKIP_DOTENV"] = "1"

from agent import DMAgent
from model_backends import DEFAULT_CODEX_MODEL, DEFAULT_CODEX_REASONING_EFFORT


class _Runner:
    def close(self):
        return None


def profile_agent() -> DMAgent:
    agent = DMAgent.__new__(DMAgent)
    agent.model_provider = "openai-compatible"
    agent.api_key = "api-secret"
    agent.raw_base_url = "https://example.test"
    agent.base_url = "https://example.test/v1"
    agent.model_name = "test-model"
    agent.reasoning_effort = ""
    agent.cli_command = ""
    agent.cli_timeout_s = 300
    agent.active_profile_id = "api-profile"
    agent.llm_profiles = [{
        "profile_id": "api-profile",
        "label": "API",
        "provider": "openai-compatible",
        "model_name": "test-model",
        "reasoning_effort": "",
        "raw_base_url": "https://example.test",
        "api_key": "api-secret",
        "cli_command": "",
        "cli_timeout_s": 300,
    }]
    agent.dm_graph_runner = _Runner()
    return agent


class LLMProfileTests(unittest.TestCase):
    def test_cli_profile_does_not_require_api_fields_or_expose_api_key(self) -> None:
        agent = profile_agent()
        payload = agent.upsert_llm_profile(
            profile_label="Codex local",
            provider="codex-cli",
            model_name="",
            base_url="",
            cli_command="codex",
            activate=False,
            persist=False,
        )

        cli_profile = next(profile for profile in payload["profiles"] if profile["label"] == "Codex local")
        self.assertEqual(cli_profile["provider"], "codex-cli")
        self.assertEqual(cli_profile["model_name"], DEFAULT_CODEX_MODEL)
        self.assertEqual(cli_profile["reasoning_effort"], DEFAULT_CODEX_REASONING_EFFORT)
        self.assertEqual(cli_profile["cli_command"], "codex")
        self.assertNotIn("api_key", cli_profile)
        self.assertFalse(cli_profile["api_key_configured"])

    def test_switching_to_cli_clears_api_credentials_from_child_environment(self) -> None:
        agent = profile_agent()
        cli_profile = {
            "profile_id": "codex-local",
            "label": "Codex local",
            "provider": "codex-cli",
            "model_name": DEFAULT_CODEX_MODEL,
            "reasoning_effort": DEFAULT_CODEX_REASONING_EFFORT,
            "raw_base_url": "",
            "api_key": "",
            "cli_command": "codex",
            "cli_timeout_s": 120,
        }
        agent.llm_profiles.append(cli_profile)
        agent._create_dm_graph_runner = lambda: _Runner()
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "must-not-leak",
            "OPENAI_API_BASE": "https://old.test/v1",
        }, clear=False):
            payload = agent.select_llm_profile("codex-local", persist=False)
            self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertNotIn("OPENAI_API_BASE", os.environ)

        self.assertEqual(payload["provider"], "codex-cli")
        self.assertEqual(payload["model_name"], DEFAULT_CODEX_MODEL)
        self.assertEqual(payload["reasoning_effort"], DEFAULT_CODEX_REASONING_EFFORT)
        self.assertTrue(payload["configured"])

    def test_unconfigured_runtime_defaults_to_codex_terra_high(self) -> None:
        empty_model_env = {
            "LLM_PROVIDER": "",
            "LLM_MODEL": "",
            "LLM_REASONING_EFFORT": "",
            "LLM_CLI_COMMAND": "",
            "LLM_ACTIVE_PROFILE_ID": "",
            "LLM_PROFILES_B64": "",
            "OPENAI_API_KEY": "",
            "OPENAI_API_BASE": "",
            "OPENAI_BASE_URL": "",
        }
        with patch.dict(os.environ, empty_model_env, clear=False), patch("agent.MonsterStorage"), patch(
            "agent.RuleCatalog"
        ), patch("agent.RAGEngine"), patch("agent.AgentToolService"), patch.object(
            DMAgent,
            "_create_dm_graph_runner",
            return_value=_Runner(),
        ):
            agent = DMAgent()

        self.assertEqual(agent.model_provider, "codex-cli")
        self.assertEqual(agent.model_name, DEFAULT_CODEX_MODEL)
        self.assertEqual(agent.reasoning_effort, DEFAULT_CODEX_REASONING_EFFORT)
        self.assertEqual(agent.cli_command, "codex")

    def test_invalid_codex_reasoning_effort_is_rejected(self) -> None:
        agent = profile_agent()
        with self.assertRaisesRegex(ValueError, "Unsupported Codex reasoning effort"):
            agent.upsert_llm_profile(
                profile_label="Invalid Codex",
                provider="codex-cli",
                model_name=DEFAULT_CODEX_MODEL,
                reasoning_effort="extreme",
                base_url="",
                persist=False,
            )

    def test_unknown_provider_is_rejected(self) -> None:
        agent = profile_agent()
        with self.assertRaisesRegex(ValueError, "Unsupported model provider"):
            agent.upsert_llm_profile(
                profile_label="Unknown",
                provider="shell",
                model_name="",
                base_url="",
                activate=False,
                persist=False,
            )


if __name__ == "__main__":
    unittest.main()
