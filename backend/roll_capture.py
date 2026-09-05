"""请求局部的骰点观察；记录真实随机结果，不修改 GameState。"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from models import RollRecord
from turn_stream import emit_turn_stream_event


@dataclass
class RollCapture:
    records: list[RollRecord] = field(default_factory=list)


_capture: ContextVar[RollCapture | None] = ContextVar("roll_capture", default=None)
_metadata: ContextVar[dict] = ContextVar("roll_metadata", default={})
_last_roll: ContextVar[RollRecord | None] = ContextVar("last_roll", default=None)


@contextmanager
def capture_rolls(initial=()):
    capture = RollCapture([item.model_copy(deep=True) for item in initial])
    token = _capture.set(capture)
    last_token = _last_roll.set(None)
    try:
        yield capture
    finally:
        _last_roll.reset(last_token)
        _capture.reset(token)


@contextmanager
def dice_context(**metadata):
    token = _metadata.set({**_metadata.get(), **metadata})
    try:
        yield
    finally:
        _metadata.reset(token)


def record_roll(*, expression, dice, kept, modifier, total, detail, roll_mode="normal"):
    capture = _capture.get()
    if capture is None:
        return
    record = RollRecord(
        record_id=uuid4().hex, expression=expression, dice=list(dice), kept=list(kept),
        modifier=modifier, total=total, detail=detail, roll_mode=roll_mode, **_metadata.get(),
    )
    capture.records.append(record)
    _last_roll.set(record)
    emit_turn_stream_event("roll.recorded", {"roll_records": [record.model_dump(mode="json")]})


def annotate_last_roll(**values):
    record = _last_roll.get()
    if record is None or _capture.get() is None:
        return
    for key, value in values.items():
        setattr(record, key, value)
    emit_turn_stream_event("roll.recorded", {"roll_records": [record.model_dump(mode="json")]})


@contextmanager
def tool_roll_context(**metadata):
    capture = _capture.get()
    start = len(capture.records) if capture else 0
    outcome = {"ok": False}
    with dice_context(**metadata):
        try:
            yield outcome
        finally:
            if capture:
                for record in capture.records[start:]:
                    record.tool_status = "succeeded" if outcome["ok"] else "failed"


def settle_rolls(records, turn_status):
    settlement = {"completed": "committed", "failed": "rolled_back"}.get(turn_status, "pending")
    return [record.model_copy(update={"settlement": "not_applied" if record.tool_status == "failed" else settlement})
            for record in records]
