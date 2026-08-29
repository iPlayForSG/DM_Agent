import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from langchain_core.messages import HumanMessage

from model_backends import CodingAgentCLIChatModel, probe_cli


class CodingAgentCLIChatModelTests(unittest.TestCase):
    def test_codex_cli_returns_langchain_tool_call_in_read_only_temp_directory(self) -> None:
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["prompt"] = kwargs["input"]
            captured["cwd"] = kwargs["cwd"]
            schema_index = command.index("--output-schema") + 1
            self.assertTrue(Path(command[schema_index]).is_file())
            self.assertEqual(kwargs["cwd"], str(Path(command[schema_index]).parent))
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "content": "",
                    "tool_calls": [{"id": "call-1", "name": "lookup_rules", "args_json": "{\"query\":\"grapple\"}"}],
                }),
                stderr="",
            )

        model = CodingAgentCLIChatModel(provider="codex-cli", command="codex", timeout_s=30)
        tools = [{
            "type": "function",
            "function": {
                "name": "lookup_rules",
                "description": "Search rules",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }]
        with patch("model_backends.resolve_cli_command", return_value="/fake/codex"), patch(
            "model_backends.subprocess.run", side_effect=fake_run
        ):
            response = model.bind_tools(tools).invoke([HumanMessage(content="How does grapple work?")])

        self.assertEqual(response.tool_calls[0]["name"], "lookup_rules")
        self.assertEqual(response.tool_calls[0]["args"], {"query": "grapple"})
        self.assertIn("exec", captured["command"])
        self.assertIn("read-only", captured["command"])
        self.assertIn("--ephemeral", captured["command"])
        self.assertIn("Do not inspect files", captured["prompt"])
        self.assertIn("lookup_rules", captured["prompt"])

    def test_claude_cli_unwraps_structured_output_and_disables_cli_tools(self) -> None:
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "type": "result",
                    "structured_output": {"content": "规则回答", "tool_calls": []},
                }),
                stderr="",
            )

        model = CodingAgentCLIChatModel(provider="claude-code", command="claude", timeout_s=30)
        with patch("model_backends.resolve_cli_command", return_value="/fake/claude"), patch(
            "model_backends.subprocess.run", side_effect=fake_run
        ):
            response = model.invoke([HumanMessage(content="回答规则")])

        self.assertEqual(response.content, "规则回答")
        tools_index = captured["command"].index("--tools")
        self.assertEqual(captured["command"][tools_index + 1], "")
        self.assertIn("--no-session-persistence", captured["command"])

    def test_probe_cli_checks_version_without_model_invocation(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="codex-cli 0.146.0\n", stderr="")
        with patch("model_backends.resolve_cli_command", return_value="/fake/codex"), patch(
            "model_backends.subprocess.run", return_value=completed
        ) as run:
            payload = probe_cli("codex-cli", "codex")

        self.assertTrue(payload["ready"])
        self.assertEqual(run.call_args.args[0], ["/fake/codex", "--version"])


if __name__ == "__main__":
    unittest.main()
