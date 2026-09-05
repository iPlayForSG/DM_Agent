import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from codex_transport import stream_codex_events, app_server_command, configured_mcp_transports
from model_backends import CLI_RESPONSE_SCHEMA


class RecordingInput:
    def __init__(self):
        self.value = ""
        self.closed = False
    def write(self, value):
        self.value += value
    def flush(self):
        pass
    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, events):
        self.stdin = RecordingInput()
        self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))
        self.stderr = io.StringIO("")
        self.returncode = None


def protocol_events(*notifications):
    return [
        {"id": 1, "result": {}},
        {"id": 2, "result": {"thread": {"id": "thread", "ephemeral": True}}},
        # 增量可能先于 turn/start 响应送达，客户端不能在等待 RPC 响应时丢失它。
        *notifications[:1],
        {"id": 3, "result": {"turn": {"id": "turn"}}},
        *notifications[1:],
    ]


def notification(method, **params):
    return {"method": method, "params": {"threadId": "thread", "turnId": "turn", **params}}


class CodexTransportTests(unittest.TestCase):
    def run_transport(self, events):
        process = FakeProcess(events)
        def start(command, **kwargs):
            self.assertIn("app-server", command)
            self.assertIn("features.hooks=false", command)
            self.assertIn("features.shell_tool=false", command)
            self.assertIn('mcp_servers.personal-server={command="codex",enabled=false}', command)
            self.assertIn("features.code_mode_host=false", command)
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            self.assertNotIn("LLM_PROFILES_B64", kwargs["env"])
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            return process
        with patch("codex_transport.configured_mcp_transports", return_value={"personal-server":"stdio"}), patch("codex_transport.subprocess.Popen", side_effect=start), patch("codex_transport._stop_process") as stop, patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic", "LLM_PROFILES_B64": "synthetic"}):
            try:
                output = list(stream_codex_events("fake", "synthetic input", schema=CLI_RESPONSE_SCHEMA,
                                                 model="gpt-5.6-terra", effort="high", timeout_s=10))
            finally:
                stop.assert_called_with(process)
                self.assertTrue(process.stdin.closed)
        return process, output

    def test_ephemeral_protocol_forwards_only_public_deltas(self):
        events = protocol_events(
            notification("item/agentMessage/delta", itemId="message", delta='{"content":"hello'),
            notification("item/reasoning/textDelta", delta="PRIVATE_SYNTHETIC_REASONING"),
            notification("item/agentMessage/delta", itemId="message", delta='","tool_calls":[]}'),
            notification("item/completed", item={"type": "agentMessage", "id": "message", "text": '{"content":"hello","tool_calls":[]}'}),
            notification("turn/completed", turn={"id": "turn", "status": "completed"}),
        )
        process, output = self.run_transport(events)
        self.assertEqual([event["type"] for event in output], ["agent_message_delta", "agent_message_delta", "item.completed", "turn.completed"])
        self.assertNotIn("PRIVATE_SYNTHETIC_REASONING", str(output))
        sent = [json.loads(line) for line in process.stdin.value.splitlines()]
        thread = next(item["params"] for item in sent if item["method"] == "thread/start")
        turn = next(item["params"] for item in sent if item["method"] == "turn/start")
        self.assertTrue(thread["ephemeral"])
        self.assertEqual(thread["selectedCapabilityRoots"], [])
        self.assertEqual(thread["sandbox"], "read-only")
        self.assertEqual(turn["outputSchema"], CLI_RESPONSE_SCHEMA)
        self.assertEqual(turn["effort"], "high")

    def test_missing_completion_fails_and_cleans_up(self):
        with self.assertRaisesRegex(RuntimeError, "closed before completion"):
            self.run_transport(protocol_events())

    def test_unexpected_host_tool_request_is_rejected(self):
        request = {"id": 99, "method": "item/tool/call", "params": {}}
        with self.assertRaisesRegex(RuntimeError, "host tool"):
            self.run_transport(protocol_events(request))

    def test_non_ephemeral_session_is_rejected(self):
        events = protocol_events()
        events[1]["result"]["thread"]["ephemeral"] = False
        with self.assertRaisesRegex(RuntimeError, "ephemeral"):
            self.run_transport(events)

    def test_personal_mcp_entries_are_explicitly_disabled_and_names_are_validated(self):
        from types import SimpleNamespace
        with patch("codex_transport.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout='[{"name":"private-mcp","transport":{"type":"stdio","env":{"TOKEN":"synthetic-secret"}}},{"name":"http-mcp","transport":{"type":"streamable_http","url":"https://private.invalid"}}]')):
            names = configured_mcp_transports("codex", directory=".", env={}, timeout_s=10)
        command = app_server_command("codex", names)
        self.assertIn('mcp_servers.private-mcp={command="codex",enabled=false}', command)
        self.assertNotIn("synthetic-secret", str(command))
        self.assertNotIn("private.invalid", str(command))
        self.assertIn('mcp_servers.http-mcp={url="http://127.0.0.1:9",enabled=false}', command)
        with self.assertRaises(RuntimeError):
            app_server_command("codex", {"bad.name.enabled":"stdio"})


if __name__ == "__main__":
    unittest.main()
