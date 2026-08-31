"""Request-local public progress events for one DM turn."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, Optional


TurnStreamEmitter = Callable[[str, Dict[str, Any]], None]

_TURN_STREAM_EMITTER: ContextVar[Optional[TurnStreamEmitter]] = ContextVar(
    "dm_agent_turn_stream_emitter",
    default=None,
)


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
