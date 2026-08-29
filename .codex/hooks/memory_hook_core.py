"""DM_Agent 项目记忆 hooks 的确定性核心。

脚本只观察 Git 工作树和维护少量本地状态，不读取 transcript、不调用模型，
也不修改产品或项目文档。语义判断始终交给当前 Codex continuation。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional


STATE_VERSION = 1
DEFAULT_SUCCESS: Dict[str, Any] = {"continue": True}
SESSION_CONTEXT = (
    "先读取仓库根 AGENTS.md；不要盲目加载所有 memory。"
    "非简单任务只按需读取相关 .agent/memory，并检查 .agent/tasks 中的 active ExecPlan。"
    "代码、测试、配置和 Accepted ADR 是事实源；SessionStart 只建立基线，不修改 memory。"
)


class HookError(RuntimeError):
    """可安全降级的 hook 环境错误。"""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalize_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def read_event(stream: Any = None) -> Dict[str, Any]:
    stream = stream or sys.stdin
    try:
        payload = json.load(stream)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_git(cwd: Path | str, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, ValueError) as exc:
        raise HookError(f"git unavailable: {exc}") from exc


def find_repo_root(cwd: str | Path) -> Optional[Path]:
    candidate = Path(cwd or os.getcwd()).resolve()
    result = _run_git(candidate, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    text = result.stdout.decode("utf-8", errors="replace").strip()
    return Path(text).resolve() if text else None


def resolve_state_dir(root: Path) -> Path:
    result = _run_git(root, "rev-parse", "--git-path", "codex-memory-hook")
    if result.returncode != 0:
        raise HookError("cannot resolve git state path")
    raw = result.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        raise HookError("empty git state path")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def runtime_state_dir(root: Path) -> Path:
    preferred = resolve_state_dir(root)
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        # 某些 Codex 沙箱把 .git 设为只读；用首选 git-path 的哈希保持普通仓库/worktree 隔离。
        digest = hashlib.sha256(str(preferred).encode("utf-8", errors="replace")).hexdigest()[:20]
        fallback = Path(tempfile.gettempdir()) / "codex-memory-hook" / digest
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()


def _safe_session_name(session_id: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip("-._")[:48]
    digest = hashlib.sha256(session_id.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{readable or 'session'}-{digest}.json"


def state_path_for(root: Path, session_id: str) -> Optional[Path]:
    if not session_id:
        return None
    return runtime_state_dir(root) / "sessions" / _safe_session_name(session_id)


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)


@contextlib.contextmanager
def _state_lock(state_path: Path, timeout_seconds: float = 3.0) -> Iterator[None]:
    """串行化同一 session 的 hook 写入，避免并行工具完成时互相覆盖观察结果。"""

    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: Optional[int] = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode("ascii", errors="ignore"))
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    lock_path.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise HookError("timed out waiting for hook state lock")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            lock_path.unlink()


def _decode_git_path(raw: bytes) -> str:
    return normalize_path(raw.decode("utf-8", errors="surrogateescape"))


def git_status(root: Path) -> Dict[str, Dict[str, str]]:
    result = _run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0:
        raise HookError("git status failed")

    parts = result.stdout.split(b"\0")
    status: Dict[str, Dict[str, str]] = {}
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if not record or len(record) < 3:
            continue
        code = record[:2].decode("ascii", errors="replace")
        path_bytes = record[3:] if record[2:3] == b" " else record[2:].lstrip()
        path = _decode_git_path(path_bytes)
        if not path:
            continue
        metadata: Dict[str, str] = {"code": code}
        if ("R" in code or "C" in code) and index < len(parts):
            metadata["old_path"] = _decode_git_path(parts[index])
            index += 1
        status[path] = metadata
    return status


def fingerprint_path(root: Path, relative_path: str) -> str:
    path = root / Path(relative_path)
    try:
        stat = path.lstat()
    except OSError:
        return "missing"

    digest = hashlib.sha256()
    digest.update(str(stat.st_mode).encode("ascii"))
    if path.is_symlink():
        try:
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        except OSError:
            return "unreadable-symlink"
        return f"symlink:{digest.hexdigest()}"
    if path.is_dir():
        return f"directory:{digest.hexdigest()}"
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unreadable"
    return f"file:{digest.hexdigest()}"


def capture_baseline(root: Path) -> Dict[str, Any]:
    status = git_status(root)
    paths: Dict[str, Dict[str, str]] = {}
    for path, metadata in status.items():
        paths[path] = {
            "code": metadata.get("code", ""),
            "fingerprint": fingerprint_path(root, path),
            **({"old_path": metadata["old_path"]} if metadata.get("old_path") else {}),
        }
    head_result = _run_git(root, "rev-parse", "HEAD")
    head = head_result.stdout.decode("ascii", errors="replace").strip() if head_result.returncode == 0 else ""
    return {"created_at": utc_now(), "head": head, "paths": paths}


def new_state(root: Path, session_id: str) -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "session_id": session_id,
        "repo_root": str(root),
        "baseline": capture_baseline(root),
        "observed_paths": [],
        "observed_tools": [],
        "pending_fingerprint": "",
        "audited_fingerprints": {},
        "trigger_counts": {},
        "updated_at": utc_now(),
    }


def load_state(path: Path) -> Dict[str, Any]:
    state = _read_json(path, {})
    return state if isinstance(state, dict) and state.get("version") == STATE_VERSION else {}


def save_state(path: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    _atomic_write_json(path, state)


def changes_since_baseline(root: Path, baseline: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
    current = git_status(root)
    baseline_paths = baseline.get("paths", {}) if isinstance(baseline.get("paths", {}), dict) else {}
    changed: Dict[str, Dict[str, str]] = {}

    for path, metadata in current.items():
        current_fingerprint = fingerprint_path(root, path)
        previous = baseline_paths.get(path)
        if isinstance(previous, dict) and previous.get("fingerprint") == current_fingerprint:
            # 仅 staged/unstaged 标记变化不代表文件内容相对会话基线发生了变化。
            continue
        changed[path] = {
            "code": metadata.get("code", ""),
            "fingerprint": current_fingerprint,
            **({"old_path": metadata["old_path"]} if metadata.get("old_path") else {}),
        }

    # 会话前已脏的文件如果被进一步修改、删除或恢复到 HEAD，也必须能被识别。
    for path, previous in baseline_paths.items():
        if path in current or not isinstance(previous, dict):
            continue
        current_fingerprint = fingerprint_path(root, path)
        if current_fingerprint != previous.get("fingerprint"):
            changed[path] = {
                "code": "D " if current_fingerprint == "missing" else "BASELINE_CHANGED",
                "fingerprint": current_fingerprint,
            }
    return changed


def load_policy(root: Path) -> Dict[str, Any]:
    policy = _read_json(root / ".codex" / "memory-policy.json", {})
    return policy if isinstance(policy, dict) else {}


def _path_matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path.casefold(), normalize_path(pattern).casefold())


def is_ignored(path: str, policy: Mapping[str, Any]) -> bool:
    normalized = normalize_path(path)
    # 文档维护本身不应再次触发维护；顶层 Markdown 也属于这一规则。
    if normalized.casefold().endswith(".md"):
        return True
    ignore = policy.get("ignore", {}) if isinstance(policy.get("ignore", {}), dict) else {}
    return any(_path_matches(normalized, pattern) for pattern in ignore.get("path_globs", []) or [])


def _module_for(path: str, policy: Mapping[str, Any]) -> str:
    mapping = policy.get("major_module_prefixes", {})
    if not isinstance(mapping, dict):
        return ""
    folded = normalize_path(path).casefold()
    for module, prefixes in mapping.items():
        for prefix in prefixes or []:
            if folded.startswith(normalize_path(prefix).casefold()):
                return str(module)
    return ""


def _active_exec_plans(root: Path, policy: Mapping[str, Any]) -> list[str]:
    config = policy.get("active_exec_plan", {})
    if not isinstance(config, dict):
        return []
    directory = root / str(config.get("directory") or ".agent/tasks")
    pattern = str(config.get("glob") or "*.md")
    try:
        status_pattern = re.compile(str(config.get("status_regex") or r"(?im)^Status:\s*active\s*$"))
    except re.error:
        return []
    active: list[str] = []
    for path in sorted(directory.glob(pattern)) if directory.is_dir() else []:
        if path.name.casefold() == "readme.md":
            continue
        try:
            content = path.read_text(encoding="utf-8")[:32768]
        except OSError:
            continue
        if status_pattern.search(content):
            active.append(normalize_path(str(path.relative_to(root))))
    return active


def evaluate_changes(
    root: Path,
    changes: Mapping[str, Mapping[str, str]],
    policy: Mapping[str, Any],
) -> Dict[str, Any]:
    effective = {path: dict(meta) for path, meta in changes.items() if not is_ignored(path, policy)}
    categories: set[str] = set()
    suggested_docs: set[str] = set()
    modules = {module for path in effective for module in [_module_for(path, policy)] if module}

    for rule in policy.get("high_signal_rules", []) or []:
        if not isinstance(rule, dict):
            continue
        patterns = rule.get("patterns", []) or []
        if any(any(_path_matches(path, pattern) for pattern in patterns) for path in effective):
            categories.add(str(rule.get("id") or "path-rule"))
            suggested_docs.update(str(item) for item in rule.get("suggested_docs", []) or [])

    structural_prefixes = [normalize_path(item).casefold() for item in policy.get("major_structure_prefixes", []) or []]
    for path, metadata in effective.items():
        code = str(metadata.get("code") or "")
        if any(path.casefold().startswith(prefix) for prefix in structural_prefixes) and (
            code == "??" or any(flag in code for flag in ("R", "C", "D"))
        ):
            categories.add("major-module-structure")
            suggested_docs.update({".agent/memory/module-map.md", ".agent/memory/architecture-map.md"})

    thresholds = policy.get("thresholds", {}) if isinstance(policy.get("thresholds", {}), dict) else {}
    file_threshold = max(1, int(thresholds.get("file_count", 6) or 6))
    module_threshold = max(1, int(thresholds.get("cross_module_count", 2) or 2))
    if len(effective) >= file_threshold:
        categories.add("large-change-set")
        suggested_docs.update({".agent/memory/module-map.md", ".agent/memory/architecture-map.md"})
    if len(modules) >= module_threshold:
        categories.add("cross-module-change")
        suggested_docs.update({".agent/memory/module-map.md", ".agent/memory/architecture-map.md"})

    active_plans = _active_exec_plans(root, policy) if categories else []
    suggested_docs.update(active_plans)
    max_files = max(1, int(policy.get("max_evidence_files", 12) or 12))
    return {
        "needs_maintenance": bool(categories),
        "categories": sorted(categories),
        "files": sorted(effective)[:max_files],
        "file_count": len(effective),
        "modules": sorted(modules),
        "suggested_docs": sorted(suggested_docs),
        "active_exec_plans": active_plans,
    }


def diff_fingerprint(changes: Mapping[str, Mapping[str, str]]) -> str:
    compact = [
        {
            "path": normalize_path(path),
            "code": str(metadata.get("code") or ""),
            "fingerprint": str(metadata.get("fingerprint") or ""),
            "old_path": normalize_path(str(metadata.get("old_path") or "")),
        }
        for path, metadata in sorted(changes.items())
    ]
    encoded = json.dumps(compact, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prune_mapping(mapping: Mapping[str, Any], limit: int = 50) -> Dict[str, Any]:
    items = list(mapping.items())[-limit:]
    return dict(items)


def build_continuation_prompt(root: Path, evidence: Mapping[str, Any]) -> str:
    prompt_path = root / ".agent" / "prompts" / "incremental-memory-maintenance.md"
    try:
        base_prompt = prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        base_prompt = "只维护项目记忆；读取 AGENTS.md，核对代码事实，并最小更新相关文档。"
    if len(base_prompt) > 6500:
        base_prompt = base_prompt[:6500].rstrip() + "\n[提示文件已按 hook 输出上限截断]"

    lines = [base_prompt, "", "## Hook 触发证据"]
    lines.append(f"- 变化类别：{', '.join(evidence.get('categories', [])) or '未分类'}")
    lines.append(f"- 涉及模块：{', '.join(evidence.get('modules', [])) or '未识别'}")
    lines.append(f"- 会话内高信号文件数：{evidence.get('file_count', 0)}")
    files = evidence.get("files", []) or []
    if files:
        lines.append("- 相关文件：" + "、".join(f"`{path}`" for path in files))
    docs = evidence.get("suggested_docs", []) or []
    if docs:
        lines.append("- 建议检查：" + "、".join(f"`{path}`" for path in docs))
    lines.append("- 证据仅包含路径分类和指纹；请自行读取必要代码，不要要求完整 diff 或 transcript。")
    return "\n".join(lines)


def _event_root(event: Mapping[str, Any]) -> Optional[Path]:
    cwd = str(event.get("cwd") or os.getcwd())
    try:
        return find_repo_root(cwd)
    except (HookError, OSError, RuntimeError):
        return None


def handle_session_start(event: Mapping[str, Any]) -> Dict[str, Any]:
    root = _event_root(event)
    session_id = str(event.get("session_id") or "").strip()
    if root and session_id:
        path = state_path_for(root, session_id)
        if path is not None:
            with _state_lock(path):
                state = load_state(path)
                source = str(event.get("source") or "startup")
                # resume/compact 必须保留原始基线；startup/clear 则代表新的观察窗口。
                if source in {"startup", "clear"} or not state:
                    state = new_state(root, session_id)
                    save_state(path, state)
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": SESSION_CONTEXT,
        },
    }


def handle_post_tool_use(event: Mapping[str, Any]) -> Dict[str, Any]:
    root = _event_root(event)
    session_id = str(event.get("session_id") or "").strip()
    if not root or not session_id:
        return {}
    path = state_path_for(root, session_id)
    if path is None:
        return {}
    with _state_lock(path):
        state = load_state(path)
        if not state:
            # 缺少 SessionStart 时宁可从当前状态建立晚基线，也不要把旧脏文件误报为本会话变化。
            state = new_state(root, session_id)
            save_state(path, state)
            return {}
        changed = changes_since_baseline(root, state.get("baseline", {}))
        observed = set(str(item) for item in state.get("observed_paths", []) or [])
        observed.update(changed)
        state["observed_paths"] = sorted(observed)
        tools = list(state.get("observed_tools", []) or [])
        tool_name = str(event.get("tool_name") or "")
        if tool_name and tool_name not in tools:
            tools.append(tool_name)
        state["observed_tools"] = tools[-16:]
        save_state(path, state)
    return {}


def handle_stop(event: Mapping[str, Any]) -> Dict[str, Any]:
    root = _event_root(event)
    session_id = str(event.get("session_id") or "").strip()
    if not root or not session_id:
        return dict(DEFAULT_SUCCESS)
    path = state_path_for(root, session_id)
    if path is None:
        return dict(DEFAULT_SUCCESS)

    with _state_lock(path):
        state = load_state(path)
        if not state:
            return dict(DEFAULT_SUCCESS)
        all_changes = changes_since_baseline(root, state.get("baseline", {}))
        observed = set(str(item) for item in state.get("observed_paths", []) or [])
        changes = {path: metadata for path, metadata in all_changes.items() if path in observed}
        policy = load_policy(root)
        evidence = evaluate_changes(root, changes, policy)
        fingerprint = diff_fingerprint(changes) if changes else ""

        if bool(event.get("stop_hook_active")):
            # continuation 完成后无条件审计本次指纹；即使 AI 判断无需更新，也必须断开 Stop 循环。
            audit_fingerprint = fingerprint or str(state.get("pending_fingerprint") or "")
            if audit_fingerprint:
                audited = dict(state.get("audited_fingerprints", {}) or {})
                audited[audit_fingerprint] = {"audited_at": utc_now()}
                state["audited_fingerprints"] = _prune_mapping(audited)
            state["pending_fingerprint"] = ""
            save_state(path, state)
            return dict(DEFAULT_SUCCESS)

        if not evidence.get("needs_maintenance") or not fingerprint:
            save_state(path, state)
            return dict(DEFAULT_SUCCESS)

        audited = dict(state.get("audited_fingerprints", {}) or {})
        counts = dict(state.get("trigger_counts", {}) or {})
        max_triggers = max(1, int(policy.get("max_triggers_per_fingerprint", 1) or 1))
        if fingerprint in audited or int(counts.get(fingerprint, 0) or 0) >= max_triggers:
            save_state(path, state)
            return dict(DEFAULT_SUCCESS)

        counts[fingerprint] = int(counts.get(fingerprint, 0) or 0) + 1
        state["trigger_counts"] = _prune_mapping(counts)
        state["pending_fingerprint"] = fingerprint
        state["last_evidence"] = {
            "categories": evidence.get("categories", []),
            "files": evidence.get("files", []),
            "modules": evidence.get("modules", []),
            "suggested_docs": evidence.get("suggested_docs", []),
        }
        save_state(path, state)
        return {"decision": "block", "reason": build_continuation_prompt(root, evidence)}


def emit(payload: Mapping[str, Any]) -> None:
    # Windows 重定向 stdout 可能使用本地代码页；ASCII JSON 转义可确保 Codex 始终按 UTF-8/JSON 安全解析。
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    sys.stdout.write("\n")


def main(mode: str) -> int:
    event = read_event()
    try:
        if mode == "session":
            payload = handle_session_start(event)
        elif mode == "observe":
            payload = handle_post_tool_use(event)
        elif mode == "stop":
            payload = handle_stop(event)
        else:
            payload = dict(DEFAULT_SUCCESS)
    except Exception:
        # Hook 不能因异常 JSON、Git 故障或文件竞争破坏正常 Codex 回合。
        payload = dict(DEFAULT_SUCCESS) if mode in {"session", "stop"} else {}
    emit(payload)
    return 0
