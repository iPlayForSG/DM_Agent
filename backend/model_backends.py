"""Model transport adapters used by the LangGraph workflow."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, message_chunk_to_message
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


OPENAI_COMPATIBLE_PROVIDER = "openai-compatible"
CLAUDE_CODE_PROVIDER = "claude-code"
CODEX_CLI_PROVIDER = "codex-cli"
DEFAULT_MODEL_PROVIDER = CODEX_CLI_PROVIDER
DEFAULT_CODEX_MODEL = "gpt-5.6-terra"
DEFAULT_CODEX_REASONING_EFFORT = "high"
CODEX_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
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


def default_model_name(provider: str) -> str:
    if provider == CODEX_CLI_PROVIDER:
        return DEFAULT_CODEX_MODEL
    if provider == OPENAI_COMPATIBLE_PROVIDER:
        return "gpt-5.1"
    return ""


def default_reasoning_effort(provider: str) -> str:
    return DEFAULT_CODEX_REASONING_EFFORT if provider == CODEX_CLI_PROVIDER else ""


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
    reasoning_effort: str = ""
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
            "reasoning_effort": self.reasoning_effort,
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
        del run_manager
        if self.provider == CODEX_CLI_PROVIDER:
            aggregate = None
            for generation in self._stream_codex(messages, stop=stop, **kwargs):
                chunk = generation.message
                aggregate = chunk if aggregate is None else aggregate + chunk
            if aggregate is None:
                raise RuntimeError("codex-cli stream returned no message")
            return ChatResult(
                generations=[ChatGeneration(message=message_chunk_to_message(aggregate))]
            )

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
        message = self._message_from_payload(payload)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del run_manager
        if self.provider == CODEX_CLI_PROVIDER:
            yield from self._stream_codex(messages, stop=stop, **kwargs)
            return

        # Claude Code 目前只有完整结构化响应；仍返回合法 chunk，让上层统一聚合消息。
        result = self._generate(messages, stop=stop, **kwargs)
        message = result.generations[0].message
        yield ChatGenerationChunk(message=self._message_to_chunk(message))

    def _stream_codex(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del stop
        executable = resolve_cli_command(self.provider, self.command)
        if not executable:
            requested = self.command or default_cli_command(self.provider)
            raise RuntimeError(f"Coding-agent CLI was not found: {requested}")

        tools = list(kwargs.get("tools") or [])
        prompt = self._build_prompt(messages, tools, kwargs.get("tool_choice"))
        final_agent_text = ""
        streamed_structured_text = ""
        streamed_content = ""
        turn_completed = False
        fatal_error = ""

        for event in self._iter_codex_json_events(executable, prompt):
            event_type = str(event.get("type") or "")
            if event_type == "error":
                fatal_error = str(event.get("message") or "codex-cli event stream failed")
                continue
            if event_type == "turn.failed":
                error = event.get("error") or {}
                detail = error.get("message") if isinstance(error, dict) else error
                raise RuntimeError(f"codex-cli turn failed: {self._safe_error_detail(str(detail or 'unknown error'))}")
            if event_type == "turn.completed":
                turn_completed = True
                continue
            if event_type in {"agent_message_delta", "item.agent_message.delta"}:
                delta_payload = event.get("delta") or ""
                if isinstance(delta_payload, dict):
                    delta_payload = delta_payload.get("text") or delta_payload.get("content") or ""
                streamed_structured_text += str(delta_payload)
                content_prefix = self._extract_partial_content(streamed_structured_text)
                if content_prefix:
                    if not content_prefix.startswith(streamed_content):
                        raise RuntimeError("codex-cli changed an already streamed content prefix")
                    delta = content_prefix[len(streamed_content):]
                    if delta:
                        streamed_content = content_prefix
                        yield ChatGenerationChunk(message=AIMessageChunk(content=delta))
                continue

            item = event.get("item") or {}
            if not isinstance(item, dict) or item.get("type") != "agent_message":
                continue
            text = str(item.get("text") or "")
            if event_type == "item.updated":
                streamed_structured_text = text
                content_prefix = self._extract_partial_content(text)
                if content_prefix:
                    if not content_prefix.startswith(streamed_content):
                        raise RuntimeError("codex-cli changed an already streamed content prefix")
                    delta = content_prefix[len(streamed_content):]
                    if delta:
                        streamed_content = content_prefix
                        yield ChatGenerationChunk(message=AIMessageChunk(content=delta))
            elif event_type == "item.completed":
                final_agent_text = text

        if fatal_error:
            raise RuntimeError(f"codex-cli event stream failed: {self._safe_error_detail(fatal_error)}")
        if not turn_completed:
            raise RuntimeError("codex-cli JSONL stream ended before turn.completed")
        if not final_agent_text:
            raise RuntimeError("codex-cli JSONL stream contained no completed agent message")

        payload = self._parse_output(final_agent_text)
        final_content = str(payload.get("content") or "")
        if not final_content.startswith(streamed_content):
            raise RuntimeError("codex-cli final content did not preserve the streamed prefix")
        remaining_content = final_content[len(streamed_content):]
        if remaining_content:
            yield ChatGenerationChunk(message=AIMessageChunk(content=remaining_content))

        tool_call_chunks = self._tool_call_chunks(payload)
        if tool_call_chunks or not final_content:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=tool_call_chunks)
            )

    def _iter_codex_json_events(self, executable: str, prompt: str) -> Iterator[Dict[str, Any]]:
        from codex_transport import stream_codex_events
        try:
            yield from stream_codex_events(executable, prompt, schema=CLI_RESPONSE_SCHEMA,
                                           model=self.model_name, effort=self.reasoning_effort, timeout_s=self.timeout_s)
        except RuntimeError as exc:
            raise RuntimeError(self._safe_error_detail(str(exc))) from exc


    @classmethod
    def _message_from_payload(cls, payload: Dict[str, Any]) -> AIMessage:
        return AIMessage(
            content=str(payload.get("content") or ""),
            tool_calls=cls._tool_calls(payload),
        )

    @classmethod
    def _message_to_chunk(cls, message: BaseMessage) -> AIMessageChunk:
        payload = {
            "tool_calls": list(getattr(message, "tool_calls", None) or []),
        }
        return AIMessageChunk(
            content=str(getattr(message, "content", "") or ""),
            tool_call_chunks=cls._tool_call_chunks(payload),
        )

    @staticmethod
    def _tool_calls(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
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
        return tool_calls

    @classmethod
    def _tool_call_chunks(cls, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "args": json.dumps(item["args"], ensure_ascii=False, separators=(",", ":")),
                "index": index,
            }
            for index, item in enumerate(cls._tool_calls(payload))
        ]

    @staticmethod
    def _extract_partial_content(raw_json: str) -> str:
        """Decode the complete prefix of the structured `content` JSON string."""

        match = re.search(r'"content"\s*:\s*"', str(raw_json or ""))
        if not match:
            return ""
        source = str(raw_json)[match.end():]
        decoded: List[str] = []
        index = 0
        escapes = {"\"": "\"", "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        while index < len(source):
            char = source[index]
            if char == '"':
                break
            if char != "\\":
                decoded.append(char)
                index += 1
                continue
            if index + 1 >= len(source):
                break
            escape = source[index + 1]
            if escape == "u":
                digits = source[index + 2:index + 6]
                if len(digits) < 4 or not re.fullmatch(r"[0-9A-Fa-f]{4}", digits):
                    break
                codepoint = int(digits, 16)
                if 0xD800 <= codepoint <= 0xDBFF:
                    low_prefix = source[index + 6:index + 8]
                    low_digits = source[index + 8:index + 12]
                    if low_prefix != "\\u" or not re.fullmatch(r"[0-9A-Fa-f]{4}", low_digits):
                        break
                    low = int(low_digits, 16)
                    if not 0xDC00 <= low <= 0xDFFF:
                        break
                    decoded.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)))
                    index += 12
                    continue
                decoded.append(chr(codepoint))
                index += 6
                continue
            if escape not in escapes:
                break
            decoded.append(escapes[escape])
            index += 2
        return "".join(decoded)

    def _build_command(self, executable: str, temp_dir: Path) -> List[str]:
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
