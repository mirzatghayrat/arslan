"""Per-turn full tool-call trace via a contextvar (mirrors usage_sink). Populated by the
tool loop, drained by RunRecorder.finalize into RunStep.detail — kept OUT of the WS stream
so full args/raw results never bloat client traffic."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar

from server.services.run_recorder import RUN_RAW_CAP

_trace: ContextVar[list[dict] | None] = ContextVar("run_trace", default=None)


def _cap(s: str) -> str:
    return s if len(s) <= RUN_RAW_CAP else s[:RUN_RAW_CAP]


def record(*, tool: str, args, result, ok: bool, error: str | None, ms: int | None) -> None:
    buf = _trace.get()
    if buf is None:
        return
    try:
        args_full = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        args_full = str(args)
    result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    buf.append({
        "tool": tool,
        "args_full": _cap(args_full),
        "result_raw": _cap(result_str),
        "ok": bool(ok),
        "error": (_cap(error) if error else None),
        "ms": ms,
    })


def snapshot() -> list[dict]:
    return list(_trace.get() or [])


@contextmanager
def collecting():
    buf: list[dict] = []
    token = _trace.set(buf)
    try:
        yield buf
    finally:
        _trace.reset(token)
