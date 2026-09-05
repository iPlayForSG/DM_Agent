"""Codex app-server 的临时、只读模型传输；仅转发公开正文的真实增量。"""

from collections import deque
import json
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time


def app_server_command(executable: str, mcp_transports=None) -> list[str]:
    overrides = {
        "notify": "[]", "model_provider": '"openai"',
        "project_doc_max_bytes": "0", "web_search": '"disabled"',
        "features.hooks": "false", "features.plugins": "false", "features.apps": "false",
        "features.shell_tool": "false", "features.browser_use": "false",
        "features.computer_use": "false", "features.image_generation": "false",
        "features.memories": "false", "agents.enabled": "false",
        "features.multi_agent": "false", "features.view_image": "false", "features.code_mode": "false",
        "features.code_mode_host": "false", "features.in_app_browser": "false",
        "features.skip_host_skill_discovery": "true", "features.skill_search": "false",
        "features.unbounded_connection_retries": "false",
        "service_tier": '"default"', "otel.log_user_prompt": "false",
    }
    command = [executable, "app-server", "--stdio"]
    for key, value in overrides.items():
        command.extend(["--config", f"{key}={value}"])
    # 空表覆盖会与用户配置合并，不能清空已有 MCP；必须逐项明确禁用。
    for name, transport in (mcp_transports or {}).items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise RuntimeError("Cannot safely disable a configured Codex MCP server")
        # 部分运行时注入的服务器只有客户端描述；覆盖整个条目，避免 enabled-only 条目缺少 transport。
        if transport == "stdio":
            definition = '{command="codex",enabled=false}'
        elif transport == "streamable_http":
            definition = '{url="http://127.0.0.1:9",enabled=false}'
        else:
            raise RuntimeError("Cannot safely disable an unknown Codex MCP transport")
        command.extend(["--config", f"mcp_servers.{name}={definition}"])
    return command


def configured_mcp_transports(executable, *, directory, env, timeout_s):
    result = subprocess.run([executable, "mcp", "list", "--json"], cwd=directory, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=min(10, timeout_s), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # 只取名称和协议类型，不复制原命令、URL、环境变量或服务器凭据。
    try:
        servers = json.loads(result.stdout) if result.returncode == 0 else None
        if not isinstance(servers, list):
            raise ValueError("invalid server list")
        return {server["name"]: server["transport"]["type"] for server in servers}
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Cannot inspect Codex MCP names for transport isolation") from exc


def _stop_process(process) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # npm 的 .cmd 入口可能带有 Node/原生子进程；仅结束外壳会留下 stdout 和正在计费的请求。
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def stream_codex_events(executable: str, prompt: str, *, schema: dict, model: str,
                        effort: str, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    with tempfile.TemporaryDirectory(prefix="dm-agent-codex-") as directory:
        env = dict(os.environ)
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE", "LLM_PROFILES_B64"):
            env.pop(key, None)
        env["NO_COLOR"] = "1"
        mcp_transports = configured_mcp_transports(executable, directory=directory, env=env, timeout_s=timeout_s)
        timeout_s = max(0.01, deadline - time.monotonic())
        process = subprocess.Popen(
            app_server_command(executable, mcp_transports), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=directory, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt",
        )
        messages = queue.Queue()
        errors = deque(maxlen=8)
        expired = threading.Event()

        def read_output():
            try:
                for line in process.stdout:
                    try:
                        messages.put(json.loads(line))
                    except ValueError:
                        messages.put({"transport_error": "Codex app-server returned invalid JSON"})
            finally:
                messages.put(None)

        def read_errors():
            for line in process.stderr:
                errors.append(line[-400:])

        def timeout():
            expired.set()
            _stop_process(process)

        readers = [threading.Thread(target=read_output, daemon=True), threading.Thread(target=read_errors, daemon=True)]
        for reader in readers:
            reader.start()
        timer = threading.Timer(timeout_s, timeout)
        timer.daemon = True
        timer.start()

        def send(value):
            process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
            process.stdin.flush()

        def receive():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or expired.is_set():
                raise RuntimeError(f"codex-cli timed out after {timeout_s}s")
            try:
                value = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise RuntimeError(f"codex-cli timed out after {timeout_s}s") from exc
            if value is None:
                raise RuntimeError("Codex app-server closed before completion: " + " ".join(errors))
            if not isinstance(value, dict) or value.get("transport_error"):
                raise RuntimeError("Codex app-server returned an invalid protocol event")
            if "method" in value and "id" in value:
                # 这是模型传输而不是另一个自主编程代理；拒绝意外的客户端工具/审批请求。
                send({"id": value["id"], "error": {"code": -32601, "message": "Host tools are disabled for this transport"}})
                raise RuntimeError("Codex requested a host tool in transport-only mode")
            return value

        def request(method, request_id, params, buffered=None):
            send({"id": request_id, "method": method, "params": params})
            while True:
                value = receive()
                if value.get("id") == request_id:
                    if "error" in value:
                        raise RuntimeError(f"Codex {method} failed: {value['error'].get('message', 'protocol error')}")
                    return value.get("result", {})
                if buffered is not None:
                    buffered.append(value)

        try:
            request("initialize", 1, {"clientInfo": {"name": "dm_agent", "version": "1.0.0"},
                                      "capabilities": {"experimentalApi": True}})
            send({"method": "initialized"})
            thread = request("thread/start", 2, {
                "cwd": directory, "model": model or None, "modelProvider": "openai",
                "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True,
                "selectedCapabilityRoots": [], "environments": [],
                "runtimeWorkspaceRoots": [directory],
                "baseInstructions": "You are a JSON language-model transport. Follow the supplied application conversation. Do not use host tools, read files, or execute commands.",
                "developerInstructions": "Return only the schema-constrained response for the application.",
            })
            thread_id = thread.get("thread", {}).get("id")
            if not thread_id or thread.get("thread", {}).get("ephemeral") is not True:
                raise RuntimeError("Codex did not create an ephemeral transport session")
            pending = deque()
            result = request("turn/start", 3, {
                "threadId": thread_id, "input": [{"type": "text", "text": prompt}],
                "model": model or None, "effort": effort or None, "summary": "none",
                "outputSchema": schema, "serviceTierForTurn": "default",
                "sandboxPolicy": {"type": "readOnly"},
            }, buffered=pending)
            turn_id = result.get("turn", {}).get("id")
            while True:
                value = pending.popleft() if pending else receive()
                method, params = value.get("method"), value.get("params", {})
                if params.get("threadId") != thread_id or (params.get("turnId") and params["turnId"] != turn_id):
                    continue
                if method == "item/agentMessage/delta":
                    yield {"type": "agent_message_delta", "delta": params.get("delta", ""), "item_id": params.get("itemId", "")}
                elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                    item = params["item"]
                    yield {"type": "item.completed", "item": {"type": "agent_message", "text": item.get("text", ""), "id": item.get("id", "")}}
                elif method == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("status") != "completed":
                        raise RuntimeError(f"Codex turn {turn.get('status')}: {turn.get('error') or 'not completed'}")
                    yield {"type": "turn.completed"}
                    break
                # reasoning/* 等内部事件不属于公开剧情正文，不进入应用 UI 或持久化记录。
        finally:
            timer.cancel()
            _stop_process(process)
            for reader in readers:
                reader.join(timeout=2)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
