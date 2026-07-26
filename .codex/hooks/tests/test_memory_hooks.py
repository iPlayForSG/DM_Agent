"""项目记忆 hooks 的端到端与策略回归测试。"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HOOKS_DIR = Path(__file__).resolve().parents[1]
PROJECT_CODEX_DIR = HOOKS_DIR.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import memory_hook_core as core  # noqa: E402


class MemoryHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="dm-agent-memory-hook-")
        self.root = Path(self.temp_dir.name) / "repo"
        self.root.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "hooks@example.invalid")
        self._git("config", "user.name", "Hook Tests")

        initial_files = {
            "backend/main.py": "API = 'v1'\n",
            "backend/models.py": "SCHEMA = 1\n",
            "backend/helper.py": "VALUE = 1\n",
            "frontend/package.json": '{"scripts":{"build":"vite build"}}\n',
            "frontend/src/api.js": "export const API = '/api/v1';\n",
            "frontend/src/helper.js": "export const value = 1;\n",
            "frontend/src/index.css": "body { color: black; }\n",
            "start.cmd": "@echo off\n",
            "README.md": "# Fixture\n",
            ".agent/prompts/incremental-memory-maintenance.md": "# Fixture maintenance\n只维护记忆。\n",
            ".agent/tasks/active.md": "# Active\n\nStatus: active\n",
        }
        for index in range(6):
            initial_files[f"misc/file-{index}.txt"] = f"value={index}\n"
        for path, content in initial_files.items():
            self._write(path, content)

        policy = json.loads((PROJECT_CODEX_DIR / "memory-policy.json").read_text(encoding="utf-8"))
        self._write(".codex/memory-policy.json", json.dumps(policy, ensure_ascii=False, indent=2) + "\n")
        self._git("add", ".")
        self._git("commit", "-m", "fixture")

        self.session_id = "session-测试 with space"
        self.session_event = {
            "session_id": self.session_id,
            "cwd": str(self.root),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
        core.handle_session_start(self.session_event)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(cwd or self.root), *args],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def _write(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _observe(self, tool_name: str = "Bash") -> dict:
        return core.handle_post_tool_use(
            {
                "session_id": self.session_id,
                "turn_id": "turn-1",
                "cwd": str(self.root),
                "hook_event_name": "PostToolUse",
                "tool_name": tool_name,
                "tool_input": {"command": "fixture"},
                "tool_response": {},
            }
        )

    def _stop(self, active: bool = False) -> dict:
        return core.handle_stop(
            {
                "session_id": self.session_id,
                "turn_id": "turn-1",
                "cwd": str(self.root),
                "hook_event_name": "Stop",
                "stop_hook_active": active,
                "last_assistant_message": "fixture",
            }
        )

    def _state(self) -> dict:
        path = core.state_path_for(self.root, self.session_id)
        self.assertIsNotNone(path)
        return core.load_state(path)  # type: ignore[arg-type]

    def assert_blocked(self, payload: dict) -> None:
        self.assertEqual(payload.get("decision"), "block")
        self.assertIsInstance(payload.get("reason"), str)
        self.assertTrue(payload["reason"].strip())

    def test_no_code_change_does_not_trigger_maintenance(self) -> None:
        self._observe()
        self.assertEqual(self._stop(), {"continue": True})

    def test_markdown_and_agent_changes_do_not_recurse(self) -> None:
        self._write("README.md", "# Changed prose\n")
        self._write(".agent/prompts/incremental-memory-maintenance.md", "# Changed memory prompt\n")
        self._observe("apply_patch")
        self.assertEqual(self._stop(), {"continue": True})

    def test_preexisting_dirty_file_is_not_misclassified(self) -> None:
        self._write("backend/main.py", "API = 'dirty-before-session'\n")
        core.handle_session_start(self.session_event)
        self._observe()
        self.assertEqual(self._stop(), {"continue": True})

    def test_further_change_to_preexisting_dirty_file_is_detected(self) -> None:
        self._write("backend/main.py", "API = 'dirty-before-session'\n")
        core.handle_session_start(self.session_event)
        self._write("backend/main.py", "API = 'changed-during-session'\n")
        self._observe()
        self.assert_blocked(self._stop())

    def test_package_script_change_suggests_commands_memory(self) -> None:
        self._write("frontend/package.json", '{"scripts":{"build":"vite build","check":"eslint ."}}\n')
        self._observe()
        payload = self._stop()
        self.assert_blocked(payload)
        self.assertIn("commands-and-ci", payload["reason"])
        self.assertIn(".agent/memory/commands.md", payload["reason"])

    def test_api_and_schema_change_triggers_architecture_review(self) -> None:
        self._write("backend/models.py", "SCHEMA = 2\n")
        self._observe()
        payload = self._stop()
        self.assert_blocked(payload)
        self.assertIn("api-and-schema", payload["reason"])
        self.assertIn("architecture-map.md", payload["reason"])

    def test_small_style_or_markdown_copy_change_does_not_trigger(self) -> None:
        self._write("frontend/src/index.css", "body { color: navy; }\n")
        self._write("README.md", "# Copy only\n")
        self._observe()
        self.assertEqual(self._stop(), {"continue": True})

    def test_cross_module_change_triggers(self) -> None:
        self._write("backend/helper.py", "VALUE = 2\n")
        self._write("frontend/src/helper.js", "export const value = 2;\n")
        self._observe()
        payload = self._stop()
        self.assert_blocked(payload)
        self.assertIn("cross-module-change", payload["reason"])

    def test_large_change_set_triggers(self) -> None:
        for index in range(6):
            self._write(f"misc/file-{index}.txt", f"changed={index}\n")
        self._observe()
        payload = self._stop()
        self.assert_blocked(payload)
        self.assertIn("large-change-set", payload["reason"])

    def test_first_stop_returns_legal_continuation_prompt(self) -> None:
        self._write("backend/main.py", "API = 'v2'\n")
        self._observe()
        payload = self._stop()
        self.assert_blocked(payload)
        json.dumps(payload, ensure_ascii=False)
        self.assertIn("Hook 触发证据", payload["reason"])
        self.assertNotIn("diff --git", payload["reason"])

    def test_stop_hook_active_audits_and_does_not_continue_again(self) -> None:
        self._write("backend/main.py", "API = 'v2'\n")
        self._observe()
        first = self._stop()
        self.assert_blocked(first)
        pending = self._state()["pending_fingerprint"]
        self.assertEqual(self._stop(active=True), {"continue": True})
        state = self._state()
        self.assertIn(pending, state["audited_fingerprints"])
        self.assertEqual(state["pending_fingerprint"], "")

    def test_same_diff_fingerprint_does_not_repeat(self) -> None:
        self._write("backend/main.py", "API = 'v2'\n")
        self._observe()
        self.assert_blocked(self._stop())
        self._stop(active=True)
        self.assertEqual(self._stop(), {"continue": True})

    def test_new_diff_fingerprint_can_trigger_again(self) -> None:
        self._write("backend/main.py", "API = 'v2'\n")
        self._observe()
        self.assert_blocked(self._stop())
        self._stop(active=True)
        self._write("backend/main.py", "API = 'v3'\n")
        self._observe()
        self.assert_blocked(self._stop())

    def test_empty_malformed_non_git_and_git_failure_degrade_safely(self) -> None:
        self.assertEqual(core.read_event(io.StringIO("not-json")), {})
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        self.assertEqual(core.handle_stop({"cwd": str(outside), "session_id": "x"}), {"continue": True})
        with mock.patch.object(core, "_run_git", side_effect=core.HookError("fixture")):
            self.assertEqual(core.handle_stop({"cwd": str(self.root), "session_id": "x"}), {"continue": True})

    def test_script_outputs_are_valid_for_each_event(self) -> None:
        session_id = "subprocess-session"
        events = [
            (
                "memory_session.py",
                {"session_id": session_id, "cwd": str(self.root), "hook_event_name": "SessionStart", "source": "startup"},
            ),
            (
                "memory_observe.py",
                {
                    "session_id": session_id,
                    "cwd": str(self.root),
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {},
                    "tool_response": {},
                },
            ),
            (
                "memory_stop.py",
                {"session_id": session_id, "cwd": str(self.root), "hook_event_name": "Stop", "stop_hook_active": False},
            ),
        ]
        for script, event in events:
            result = subprocess.run(
                [sys.executable, str(HOOKS_DIR / script)],
                input=json.dumps(event, ensure_ascii=True).encode("ascii"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            parsed = json.loads(result.stdout.decode("ascii"))
            self.assertIsInstance(parsed, dict)

    def test_stop_script_escapes_continuation_prompt_as_valid_json(self) -> None:
        session_id = "escaped-continuation"

        def invoke(script: str, event: dict) -> dict:
            result = subprocess.run(
                [sys.executable, str(HOOKS_DIR / script)],
                input=json.dumps(event, ensure_ascii=True).encode("ascii"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return json.loads(result.stdout.decode("ascii"))

        invoke(
            "memory_session.py",
            {"session_id": session_id, "cwd": str(self.root), "hook_event_name": "SessionStart", "source": "startup"},
        )
        self._write("backend/main.py", "API = 'escaped-v2'\n")
        invoke(
            "memory_observe.py",
            {
                "session_id": session_id,
                "cwd": str(self.root),
                "hook_event_name": "PostToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "fixture"},
                "tool_response": {},
            },
        )
        payload = invoke(
            "memory_stop.py",
            {
                "session_id": session_id,
                "cwd": str(self.root),
                "hook_event_name": "Stop",
                "stop_hook_active": False,
            },
        )
        self.assert_blocked(payload)
        self.assertIn("只维护记忆", payload["reason"])

    def test_space_chinese_and_rename_paths_are_parsed(self) -> None:
        old_path = "backend/旧 文件.py"
        new_path = "backend/新 文件.py"
        self._write(old_path, "VALUE = 1\n")
        self._git("add", old_path)
        self._git("commit", "-m", "unicode path")
        core.handle_session_start(self.session_event)
        self._git("mv", old_path, new_path)
        self._observe()
        payload = self._stop()
        self.assert_blocked(payload)
        self.assertIn("新 文件.py", payload["reason"])

    def test_state_is_written_under_git_dir_not_worktree(self) -> None:
        state_path = core.state_path_for(self.root, self.session_id)
        self.assertIsNotNone(state_path)
        self.assertTrue(str(state_path).startswith(str((self.root / ".git").resolve())))
        self.assertFalse((self.root / "codex-memory-hook").exists())

    def test_read_only_git_dir_falls_back_to_isolated_temp_state(self) -> None:
        blocked_parent = self.root / "blocked-parent"
        blocked_parent.write_text("not a directory", encoding="utf-8")
        preferred = blocked_parent / "codex-memory-hook"
        with mock.patch.object(core, "resolve_state_dir", return_value=preferred):
            state_dir = core.runtime_state_dir(self.root)
        self.assertNotEqual(state_dir, preferred)
        self.assertIn("codex-memory-hook", str(state_dir))

    def test_linked_worktree_gets_worktree_specific_state_dir(self) -> None:
        worktree = Path(self.temp_dir.name) / "linked worktree"
        self._git("worktree", "add", "-b", "hook-worktree", str(worktree))
        try:
            state_dir = core.resolve_state_dir(worktree)
            normalized = str(state_dir).replace("\\", "/")
            self.assertIn("/.git/worktrees/", normalized)
            self.assertTrue(normalized.endswith("/codex-memory-hook"))
        finally:
            self._git("worktree", "remove", "--force", str(worktree))


if __name__ == "__main__":
    unittest.main()
