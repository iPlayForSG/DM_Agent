"""Request-local public progress events for one DM turn."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, Optional
import time


TurnStreamEmitter = Callable[[str, Dict[str, Any]], None]

_TURN_STREAM_EMITTER: ContextVar[Optional[TurnStreamEmitter]] = ContextVar(
    "dm_agent_turn_stream_emitter",
    default=None,
)
_TURN_DEADLINE: ContextVar[Optional[float]] = ContextVar("dm_agent_turn_deadline", default=None)


@contextmanager
def turn_time_budget(seconds: float):
    """多次模型调用共用一个请求预算，避免每次工具之后重新获得完整等待窗口。"""
    token = _TURN_DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _TURN_DEADLINE.reset(token)


def remaining_turn_seconds(call_timeout=None):
    deadline = _TURN_DEADLINE.get()
    if deadline is None:
        return call_timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("本轮处理已超过等待时限，暂存动作未提交。")
    return min(remaining, call_timeout) if call_timeout is not None else remaining


@contextmanager
def turn_stream_context(emitter: Optional[TurnStreamEmitter]) -> Iterator[None]:
    """Bind an observation-only event sink to the current turn execution context."""

    token = _TURN_STREAM_EMITTER.set(emitter)
    try:
        yield
    finally:
        _TURN_STREAM_EMITTER.reset(token)


def turn_stream_active() -> bool:
    return _TURN_STREAM_EMITTER.get() is not None


def emit_turn_stream_event(event: str, data: Dict[str, Any]) -> None:
    emitter = _TURN_STREAM_EMITTER.get()
    if emitter is None:
        return
    try:
        # 流式展示只是观察通道；浏览器断线或队列关闭不能反向破坏权威回合事务。
        emitter(event, dict(data or {}))
    except Exception:
        return
