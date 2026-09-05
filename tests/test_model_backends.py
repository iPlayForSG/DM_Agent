import json
import os
import sys
import unittest
from functools import reduce
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from langchain_core.messages import HumanMessage, message_chunk_to_message

from model_backends import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    CodingAgentCLIChatModel,
    probe_cli,
)






class CodingAgentCLIChatModelTests(unittest.TestCase):
    def test_codex_cli_returns_langchain_tool_call_in_read_only_temp_directory(self) -> None:
        captured = {}
        payload = {
            "content": "",
            "tool_calls": [
                {"id": "call-1", "name": "lookup_rules", "args_json": "{\"query\":\"grapple\"}"}
            ],
        }
        events = [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"id": "item-1", "type": "agent_message", "text": json.dumps(payload)},
            },
            {"type": "turn.completed", "usage": {}},
        ]

        def fake_stream(executable, prompt, **kwargs):
            captured.update(executable=executable, prompt=prompt, **kwargs)
            yield from events

        model = CodingAgentCLIChatModel(
            provider="codex-cli",
            command="codex",
            model_name=DEFAULT_CODEX_MODEL,
            reasoning_effort=DEFAULT_CODEX_REASONING_EFFORT,
            timeout_s=30,
        )
        tools = [{
            "type": "function",
            "function": {
                "name": "lookup_rules",
                "description": "Search rules",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }]
        with patch("model_backends.resolve_cli_command", return_value="/fake/codex"), patch(
            "codex_transport.stream_codex_events", side_effect=fake_stream
        ):
            response = model.bind_tools(tools).invoke([HumanMessage(content="How does grapple work?")])

        prompt = captured["prompt"]
        self.assertEqual(response.tool_calls[0]["name"], "lookup_rules")
        self.assertEqual(response.tool_calls[0]["args"], {"query": "grapple"})
        self.assertEqual(captured["executable"], "/fake/codex")
        self.assertEqual(captured["model"], "gpt-5.6-terra")
        self.assertEqual(captured["effort"], "high")
        self.assertFalse(captured["schema"]["additionalProperties"])
        self.assertIn("Do not inspect files", prompt)
        self.assertIn("lookup_rules", prompt)

    def test_codex_cli_streams_content_prefix_and_rebuilds_final_tool_calls(self) -> None:
        captured = {}
        final_payload = {
            "content": "先观察，再行动。",
            "tool_calls": [
                {"id": "call-2", "name": "lookup_rules", "args_json": "{\"query\":\"伏击\"}"}
            ],
        }
        events = [
            {"type": "thread.started", "thread_id": "thread-2"},
            {"type": "turn.started"},
            {
                "type": "agent_message_delta",
                "delta": '{"content":"先观察',
            },
            {
                "type": "agent_message_delta",
                "delta": '，再行动。","tool_calls":[',
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "item-2",
                    "type": "agent_message",
                    "text": json.dumps(final_payload, ensure_ascii=False),
                },
            },
            {"type": "turn.completed", "usage": {}},
        ]

        def fake_stream(executable, prompt, **kwargs):
            captured.update(executable=executable, **kwargs)
            yield from events

        model = CodingAgentCLIChatModel(provider="codex-cli", command="codex", timeout_s=30)
        with patch("model_backends.resolve_cli_command", return_value="/fake/codex"), patch(
            "codex_transport.stream_codex_events", side_effect=fake_stream
        ):
            chunks = list(model.stream([HumanMessage(content="观察并查规则")]))

        text_chunks = [chunk.content for chunk in chunks if chunk.content]
        self.assertEqual(text_chunks, ["先观察", "，再行动。"])
        aggregate = reduce(lambda left, right: left + right, chunks)
        response = message_chunk_to_message(aggregate)
        self.assertEqual(response.content, "先观察，再行动。")
        self.assertEqual(response.tool_calls[0]["name"], "lookup_rules")
        self.assertEqual(response.tool_calls[0]["args"], {"query": "伏击"})
        self.assertEqual(captured["executable"], "/fake/codex")

    def test_partial_content_decoder_waits_for_incomplete_escape(self) -> None:
        self.assertEqual(
            CodingAgentCLIChatModel._extract_partial_content('{"content":"第一行\\n第二行\\'),
            "第一行\n第二行",
        )
        self.assertEqual(
            CodingAgentCLIChatModel._extract_partial_content('{"content":"完成 \\ud83d\\ude00'),
            "完成 😀",
        )

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

    @unittest.skipUnless(
        os.getenv("DM_AGENT_RUN_CODEX_CLI_STREAM_TEST") == "1",
        "set DM_AGENT_RUN_CODEX_CLI_STREAM_TEST=1 to call the installed Codex CLI",
    )
    def test_real_codex_cli_jsonl_stream_contract(self) -> None:
        model = CodingAgentCLIChatModel(
            provider="codex-cli",
            command="codex",
            model_name=os.getenv("DM_AGENT_CODEX_STREAM_TEST_MODEL", DEFAULT_CODEX_MODEL),
            reasoning_effort=os.getenv("DM_AGENT_CODEX_STREAM_TEST_REASONING", "low"),
            timeout_s=180,
        )

        chunks = list(model.stream([HumanMessage(content="Return exactly CLI_STREAM_OK")]))
        aggregate = reduce(lambda left, right: left + right, chunks)
        response = message_chunk_to_message(aggregate)

        self.assertEqual(response.content.strip(), "CLI_STREAM_OK")
        self.assertEqual(response.tool_calls, [])


if __name__ == "__main__":
    unittest.main()
