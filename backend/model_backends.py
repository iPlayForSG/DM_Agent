"""Model transport adapters used by the LangGraph workflow."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


OPENAI_COMPATIBLE_PROVIDER = "openai-compatible"
CLAUDE_CODE_PROVIDER = "claude-code"
CODEX_CLI_PROVIDER = "codex-cli"
SUPPORTED_MODEL_PROVIDERS = (
    OPENAI_COMPATIBLE_PROVIDER,
    CLAUDE_CODE_PROVIDER,
    CODEX_CLI_PROVIDER,
)

CLI_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "args_json": {"type": "string"},
                },
                "required": ["id", "name", "args_json"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["content", "tool_calls"],
    "additionalProperties": False,
}


def default_cli_command(provider: str) -> str:
    if provider == CLAUDE_CODE_PROVIDER:
        return "claude"
    if provider == CODEX_CLI_PROVIDER:
        return "codex"
    return ""


def resolve_cli_command(provider: str, configured: str = "") -> str:
    command = str(configured or default_cli_command(provider)).strip()
    if not command:
        return ""
    expanded = os.path.expanduser(command)
    if os.path.dirname(expanded):
        path = os.path.abspath(expanded)
        return path if os.path.isfile(path) else ""
    return shutil.which(expanded) or ""


def probe_cli(provider: str, configured: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
    executable = resolve_cli_command(provider, configured)
    if not executable:
        return {
            "ready": False,
            "reason": "cli_not_found",
            "detail": f"Could not find {configured or default_cli_command(provider)} on PATH.",
            "command": configured or default_cli_command(provider),
        }
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except Exception as exc:
        return {
            "ready": False,
            "reason": "cli_probe_failed",
            "detail": str(exc),
            "command": executable,
        }
    detail = (completed.stdout or completed.stderr or "").strip()[:240]
    return {
        "ready": completed.returncode == 0,
        "reason": "ok" if completed.returncode == 0 else "cli_probe_failed",
        "detail": detail,
        "command": executable,
        "probe_scope": "installation",
        "auth_verified": False,
    }


class CodingAgentCLIChatModel(BaseChatModel):
    """Expose a coding-agent CLI as a constrained LangChain chat transport."""

    provider: str
    command: str = ""
    model_name: str = ""
    timeout_s: int = Field(default=300, ge=10, le=1800)

    @property
    def _llm_type(self) -> str:
        return self.provider

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "command": self.command,
            "model_name": self.model_name,
        }

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[Any] = None,
        **kwargs: Any,
    ):
        normalized = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=normalized, tool_choice=tool_choice, **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        executable = resolve_cli_command(self.provider, self.command)
        if not executable:
            requested = self.command or default_cli_command(self.provider)
            raise RuntimeError(f"Coding-agent CLI was not found: {requested}")

        tools = list(kwargs.get("tools") or [])
        prompt = self._build_prompt(messages, tools, kwargs.get("tool_choice"))
        with tempfile.TemporaryDirectory(prefix="dm-agent-cli-") as temp_dir:
            command = self._build_command(executable, Path(temp_dir))
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=temp_dir,
                timeout=self.timeout_s,
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        if completed.returncode != 0:
            detail = self._safe_error_detail(completed.stderr or completed.stdout or "unknown CLI error")
            raise RuntimeError(f"{self.provider} exited with code {completed.returncode}: {detail}")

        payload = self._parse_output(completed.stdout)
        tool_calls = []
        for index, item in enumerate(payload.get("tool_calls") or []):
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            raw_args = item.get("args_json", item.get("args", {}))
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    raw_args = {}
            tool_calls.append(
                {
                    "id": str(item.get("id") or f"cli-call-{index + 1}"),
                    "name": str(item["name"]),
                    "args": dict(raw_args or {}) if isinstance(raw_args, dict) else {},
                }
            )
        message = AIMessage(content=str(payload.get("content") or ""), tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _build_command(self, executable: str, temp_dir: Path) -> List[str]:
        if self.provider == CODEX_CLI_PROVIDER:
            schema_path = temp_dir / "response-schema.json"
            schema_path.write_text(json.dumps(CLI_RESPONSE_SCHEMA), encoding="utf-8")
            command = [
                executable,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
            ]
            if self.model_name:
                command.extend(["--model", self.model_name])
            command.append("-")
            return command
        if self.provider == CLAUDE_CODE_PROVIDER:
            command = [
                executable,
                "-p",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(CLI_RESPONSE_SCHEMA, separators=(",", ":")),
                "--tools",
                "",
                "--no-session-persistence",
            ]
            if self.model_name:
                command.extend(["--model", self.model_name])
            return command
        raise ValueError(f"Unsupported coding-agent CLI provider: {self.provider}")

    def _parse_output(self, stdout: str) -> Dict[str, Any]:
        raw = str(stdout or "").strip()
        if not raw:
            raise RuntimeError(f"{self.provider} returned an empty response")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.provider} returned invalid JSON: {exc}") from exc
        if self.provider == CLAUDE_CODE_PROVIDER and isinstance(payload, dict):
            payload = payload.get("structured_output") or payload
        if not isinstance(payload, dict):
            raise RuntimeError(f"{self.provider} response was not a JSON object")
        return payload

    @staticmethod
    def _safe_error_detail(raw: str) -> str:
        detail = " ".join(str(raw or "").split())[-400:]
        detail = re.sub(r"(?i)(api[_ -]?key|authorization|bearer)\s*[:=]?\s*\S+", r"\1 [redacted]", detail)
        detail = re.sub(r"\b(?:sk|sess)-[A-Za-z0-9_-]{8,}\b", "[redacted]", detail)
        return detail

    @staticmethod
    def _build_prompt(messages: Sequence[BaseMessage], tools: List[Dict[str, Any]], tool_choice: Any) -> str:
        transcript = []
        for message in messages:
            entry: Dict[str, Any] = {
                "role": getattr(message, "type", message.__class__.__name__),
                "content": getattr(message, "content", ""),
            }
            message_tool_calls = getattr(message, "tool_calls", None)
            if message_tool_calls:
                entry["tool_calls"] = message_tool_calls
            tool_call_id = getattr(message, "tool_call_id", "")
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            transcript.append(entry)
        envelope = {
            "messages": transcript,
            "available_tools": tools,
            "tool_choice": tool_choice,
        }
        # CLI 仅承担模型传输；隔离临时目录与结构化协议共同阻止它越过权威工具边界。
        return (
            "You are the language-model transport inside a D&D application. "
            "Do not inspect files, run commands, or use coding-agent tools. "
            "Follow the supplied conversation and return exactly one JSON object matching the required schema. "
            "If an application tool is needed, put it in tool_calls, serialize its argument object into args_json, "
            "and leave content empty. "
            "Otherwise return the final assistant text in content and an empty tool_calls array. "
            "Never invent tool names or mutate game state yourself.\n\n"
            f"APPLICATION_INPUT_JSON:\n{json.dumps(envelope, ensure_ascii=False, default=str)}"
        )
